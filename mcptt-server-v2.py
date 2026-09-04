#!/usr/bin/env python3
import asyncio
import logging
import random
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field

###############################################################################
# CONFIGURATION
###############################################################################

SIP_BIND_IP = "0.0.0.0"
SIP_BIND_PORT = 5070

RTP_BIND_IP = "172.30.104.240"
RTP_PORT_MIN = 10000
RTP_PORT_MAX = 20000

ADVERTISE_IP = "172.30.104.240"

###############################################################################
# LOGGING
###############################################################################

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s"
)

###############################################################################
# SIP UTILITIES
###############################################################################

def generate_tag():
    return hex(random.randint(0x10000, 0xFFFFF))[2:]

def generate_branch():
    return "z9hG4bK-" + hex(random.randint(0x10000, 0xFFFFFF))[2:]

def parse_sip_headers(msg):
    headers = {}
    lines = msg.split("\r\n")
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return headers

###############################################################################
# SIP TRANSACTION STATE
###############################################################################

@dataclass
class SipTransaction:
    call_id: str
    cseq: str
    method: str
    via: str
    from_hdr: str
    to_hdr: str
    contact: str
    dialog_tag: str = None
    last_response: str = None
    created: float = field(default_factory=time.time)
    ack_received: bool = False

###############################################################################
# MCPTT SESSION MODEL
###############################################################################

@dataclass
class McpttSession:
    call_id: str
    group_uri: str
    origin_uri: str
    rtp_port: int
    state: str = "INVITING"

###############################################################################
# GLOBAL STATE
###############################################################################

transactions = {}
sessions = {}

###############################################################################
# SIP SERVER
###############################################################################

class SipServer(asyncio.DatagramProtocol):

    def connection_made(self, transport):
        self.transport = transport
        logging.info(f"MCPTT AS listening on {SIP_BIND_IP}:{SIP_BIND_PORT}")

    def datagram_received(self, data, addr):
        msg = data.decode(errors="ignore")
        src_ip, src_port = addr

        logging.info(f"SIP RX from {src_ip}:{src_port}\n{msg}")

        if msg.startswith("INVITE"):
            self.handle_invite(msg, addr)
        elif msg.startswith("ACK"):
            self.handle_ack(msg, addr)
        elif msg.startswith("BYE"):
            self.handle_bye(msg, addr)
        else:
            self.send_simple_response(msg, addr, "200 OK")

    ###########################################################################
    # INVITE HANDLING
    ###########################################################################

    def handle_invite(self, msg, addr):
        headers = parse_sip_headers(msg)
        call_id = headers.get("call-id")
        cseq = headers.get("cseq")
        via = headers.get("via")
        from_hdr = headers.get("from")
        to_hdr = headers.get("to")
        contact = headers.get("contact")

        # Create transaction
        tag = generate_tag()
        to_tagged = f"{to_hdr};tag={tag}"

        tx = SipTransaction(
            call_id=call_id,
            cseq=cseq,
            method="INVITE",
            via=via,
            from_hdr=from_hdr,
            to_hdr=to_tagged,
            contact=contact,
            dialog_tag=tag
        )
        transactions[call_id] = tx

        # Create MCPTT session
        group_uri = msg.split()[1]
        rtp_port = random.randint(RTP_PORT_MIN, RTP_PORT_MAX)

        sessions[call_id] = McpttSession(
            call_id=call_id,
            group_uri=group_uri,
            origin_uri=from_hdr,
            rtp_port=rtp_port
        )

        # Build 200 OK
        response = (
            f"SIP/2.0 200 OK\r\n"
            f"{via}\r\n"
            f"{from_hdr}\r\n"
            f"{to_tagged}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            f"Contact: <sip:{ADVERTISE_IP}:{SIP_BIND_PORT}>\r\n"
            f"Content-Type: application/sdp\r\n"
            f"Content-Length: {len(self.build_sdp(rtp_port))}\r\n"
            f"\r\n"
            f"{self.build_sdp(rtp_port)}"
        )

        tx.last_response = response

        logging.info(f"SIP TX 200 OK for Call-ID {call_id}")
        self.transport.sendto(response.encode(), addr)

    ###########################################################################
    # ACK HANDLING
    ###########################################################################

    def handle_ack(self, msg, addr):
        headers = parse_sip_headers(msg)
        call_id = headers.get("call-id")

        if call_id in transactions:
            tx = transactions[call_id]
            tx.ack_received = True
            logging.info(f"ACK received for Call-ID {call_id}")
        else:
            logging.warning(f"ACK for unknown Call-ID {call_id}")

    ###########################################################################
    # BYE HANDLING
    ###########################################################################

    def handle_bye(self, msg, addr):
        headers = parse_sip_headers(msg)
        call_id = headers.get("call-id")

        response = (
            "SIP/2.0 200 OK\r\n"
            f"{headers.get('via')}\r\n"
            f"{headers.get('from')}\r\n"
            f"{headers.get('to')}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {headers.get('cseq')}\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        self.transport.sendto(response.encode(), addr)
        logging.info(f"BYE completed for Call-ID {call_id}")

    ###########################################################################
    # SIMPLE RESPONSE
    ###########################################################################

    def send_simple_response(self, msg, addr, status):
        headers = parse_sip_headers(msg)
        call_id = headers.get("call-id", "unknown")
        cseq = headers.get("cseq", "1")

        response = (
            f"SIP/2.0 {status}\r\n"
            f"{headers.get('via')}\r\n"
            f"{headers.get('from')}\r\n"
            f"{headers.get('to')}\r\n"
            f"Call-ID: {call_id}\r\n"
            f"CSeq: {cseq}\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        self.transport.sendto(response.encode(), addr)

    ###########################################################################
    # SDP GENERATION
    ###########################################################################

    def build_sdp(self, rtp_port):
        return (
            "v=0\r\n"
            f"o=- 1 1 IN IP4 {ADVERTISE_IP}\r\n"
            "s=MCPTT\r\n"
            f"c=IN IP4 {ADVERTISE_IP}\r\n"
            "t=0 0\r\n"
            f"m=audio {rtp_port} RTP/AVP 0\r\n"
            "a=rtpmap:0 PCMU/8000\r\n"
            "a=sendrecv\r\n"
            "a=mcptt\r\n"
        )

###############################################################################
# MAIN
###############################################################################

async def main():
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: SipServer(),
        local_addr=(SIP_BIND_IP, SIP_BIND_PORT)
    )
    try:
        await asyncio.sleep(10**9)
    finally:
        transport.close()

if __name__ == "__main__":
    asyncio.run(main())
