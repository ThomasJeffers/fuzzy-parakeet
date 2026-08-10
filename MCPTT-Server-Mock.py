#!/usr/bin/env python3
"""
=============================================================================
MCPTT Server Mock
=============================================================================
Architecture & Standards:
    - 3GPP TS 24.379 (SIP Call Control)
    - 3GPP TS 24.380 (Media & Floor Control - MBCP)
    - 3GPP TS 26.179 (Codec: AMR-WB)
    - Tested for MCOP MCPTT Client v3.0 & Kamailio IMS Core
=============================================================================
"""

import logging
import re
import socket
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, Set


# ============================================================================
# CONFIGURATION
# ============================================================================

SIP_BIND_IP = "0.0.0.0"
SIP_PORT = 5060

# IP address reachable from RTP-Engine / UEs side
ADVERTISE_IP = "172.30.104.240"
RTP_BIND_IP = "0.0.0.0"

RTP_PORT_START = 10000
RTP_PORT_END = 20000

MAX_UE_PER_SESSION = 2
MAX_UDP_PACKET = 65535

# Codec settings - AMR-WB is the primary MCPTT standard codec
PREFERRED_CODEC = {
    "payload": 99,
    "name": "AMR-WB",
    "clock": 16000,
    "channels": 1,
    "fmtp": "octet-align=1"
}

# Reserve/Fallback codecs
FALLBACK_CODECS = {
    8: {"name": "PCMA", "clock": 8000, "channels": 1, "fmtp": None},
    0: {"name": "PCMU", "clock": 8000, "channels": 1, "fmtp": None},
}


# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(threadName)-15s | %(message)s",
)
logger = logging.getLogger("MCPTT-SERVER-MOCK")


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class SDPInfo:
    """Information extracted from the client's SDP Offer"""
    connection_ip: Optional[str] = None
    audio_port: Optional[int] = None
    rtcp_port: Optional[int] = None
    payload_types: list = field(default_factory=list)
    selected_codec: dict = field(default_factory=dict)
    raw_sdp: str = ""


@dataclass
class CallLeg:
    """Represents a SIP/Media connection for a UE"""
    call_id: str
    from_header: str
    to_header: str
    remote_sip_addr: Tuple[str, int]
    local_tag: str
    remote_media_ip: str
    remote_rtp_port: int
    remote_rtcp_port: int
    local_rtp_port: int
    local_rtcp_port: int
    rtp_socket: socket.socket
    rtcp_socket: socket.socket
    sdp: SDPInfo
    created_at: float = field(default_factory=time.time)
    active: bool = True

    # Statistics counters
    rtp_rx_packets: int = 0
    rtp_tx_packets: int = 0
    rtcp_rx_packets: int = 0
    rtcp_tx_packets: int = 0


@dataclass
class MCPTTSession:
    """Represents an MCPTT group or conversation session containing up to 2 UEs"""
    session_id: str
    group_uri: str
    legs: Dict[str, CallLeg] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def generate_tag() -> str:
    return uuid.uuid4().hex[:12]

def parse_sip_message(data: bytes) -> dict:
    text = data.decode("utf-8", errors="replace")
    header_part, _, body = text.partition("\r\n\r\n")
    lines = header_part.split("\r\n")
    if not lines:
        return {"start_line": "", "headers": {}, "body": body}

    start_line = lines[0]
    headers = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key in headers:
            if isinstance(headers[key], list):
                headers[key].append(value)
            else:
                headers[key] = [headers[key], value]
        else:
            headers[key] = value

    return {"start_line": start_line, "headers": headers, "body": body}

def get_header(headers: dict, name: str, default: str = "") -> str:
    name_lower = name.lower()
    for key, value in headers.items():
        if key.lower() == name_lower:
            return value[-1] if isinstance(value, list) else value
    return default

def get_method(start_line: str) -> Optional[str]:
    if not start_line or start_line.startswith("SIP/2.0"):
        return None
    parts = start_line.split()
    return parts[0].upper() if parts else None

def add_or_replace_tag(header_value: str, tag: str) -> str:
    if not header_value:
        return f"<sip:unknown>;tag={tag}"
    if re.search(r"(?:^|;)\s*tag=", header_value):
        return re.sub(r"(;tag=)[^;>\s]+", rf"\1{tag}", header_value, count=1)
    return f"{header_value};tag={tag}"


# ============================================================================
# SDP PARSER & BUILDER
# ============================================================================

def parse_sdp(sdp_text: str) -> SDPInfo:
    info = SDPInfo(raw_sdp=sdp_text)
    session_connection_ip = None
    media_connection_ip = None
    current_audio = False

    for line in sdp_text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("c=IN IP4 "):
            ip = line[9:].strip()
            if current_audio:
                media_connection_ip = ip
            else:
                session_connection_ip = ip

        elif line.startswith("m=audio "):
            current_audio = True
            parts = line.split()
            if len(parts) >= 4:
                try:
                    info.audio_port = int(parts[1])
                except ValueError:
                    pass
                for payload in parts[3:]:
                    try:
                        info.payload_types.append(int(payload))
                    except ValueError:
                        pass

        elif line.startswith("a=rtcp:"):
            value = line[len("a=rtcp:"):].strip()
            parts = value.split()
            if parts:
                try:
                    info.rtcp_port = int(parts[0])
                except ValueError:
                    pass

    info.connection_ip = media_connection_ip or session_connection_ip
    if info.rtcp_port is None and info.audio_port is not None:
        info.rtcp_port = info.audio_port + 1

    # Select codec (priority AMR-WB)
    if 99 in info.payload_types or "AMR-WB" in sdp_text.upper():
        info.selected_codec = PREFERRED_CODEC.copy()
    else:
        # Fallback to other codecs if AMR-WB is not present
        info.selected_codec = PREFERRED_CODEC.copy()
        for pt in info.payload_types:
            if pt in FALLBACK_CODECS:
                info.selected_codec = FALLBACK_CODECS[pt].copy()
                info.selected_codec["payload"] = pt
                break

    return info

def build_sdp_answer(media_ip: str, rtp_port: int, rtcp_port: int, codec: dict) -> str:
    session_id = int(time.time() * 1000)
    pt = codec["payload"]
    c_name = codec["name"]
    clock = codec["clock"]

    sdp_lines = [
        "v=0",
        f"o=mcptt-server {session_id} 1 IN IP4 {media_ip}",
        "s=MCPTT-Mock",
        f"c=IN IP4 {media_ip}",
        "t=0 0",
        f"m=audio {rtp_port} RTP/AVP {pt}",
        f"a=rtpmap:{pt} {c_name}/{clock}/1",
    ]

    if codec.get("fmtp"):
        sdp_lines.append(f"a=fmtp:{pt} {codec['fmtp']}")

    sdp_lines.extend([
        f"a=rtcp:{rtcp_port}",
        "a=sendrecv\r\n"
    ])

    return "\r\n".join(sdp_lines)


# ============================================================================
# MAIN MCPTT SERVER CLASS
# ============================================================================

class MCPTTServer:
    def __init__(
        self,
        sip_bind_ip: str = SIP_BIND_IP,
        sip_port: int = SIP_PORT,
        advertise_ip: str = ADVERTISE_IP,
        rtp_bind_ip: str = RTP_BIND_IP,
        rtp_start: int = RTP_PORT_START,
        rtp_end: int = RTP_PORT_END,
    ):
        self.sip_bind_ip = sip_bind_ip
        self.sip_port = sip_port
        self.advertise_ip = advertise_ip
        self.rtp_bind_ip = rtp_bind_ip
        self.rtp_start = rtp_start
        self.rtp_end = rtp_end

        self.sessions: Dict[str, MCPTTSession] = {}
        self.call_to_session: Dict[str, str] = {}
        self.used_ports: Set[int] = set()

        self.lock = threading.RLock()
        self.running = True

        # Set up SIP socket
        self.sip_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sip_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sip_socket.bind((self.sip_bind_ip, self.sip_port))

        logger.info(f"MCPTT Server Listening on SIP {self.sip_bind_ip}:{self.sip_port}")

        # Start main SIP Receiver thread
        self.sip_thread = threading.Thread(target=self.sip_loop, name="SIP-Receiver", daemon=True)
        self.sip_thread.start()

    # ------------------------------------------------------------------------
    # MEDIA PORT MANAGEMENT
    # ------------------------------------------------------------------------

    def allocate_media_ports(s) -> Tuple[int, int]:
        with s.lock:
            port = s.rtp_start
            while port <= s.rtp_end - 1:
                if port not in s.used_ports and (port + 1) not in s.used_ports:
                    s.used_ports.add(port)
                    s.used_ports.add(port + 1)
                    return port, port + 1
                port += 2
        raise RuntimeError("RTP/RTCP port range is exhausted.")

    def release_media_ports(s, rtp_port: int, rtcp_port: int):
        with s.lock:
            s.used_ports.discard(rtp_port)
            s.used_ports.discard(rtcp_port)

    # ------------------------------------------------------------------------
    # SIP RECEIVE LOOP
    # ------------------------------------------------------------------------

    def sip_loop(self):
        while self.running:
            try:
                data, addr = self.sip_socket.recvfrom(MAX_UDP_PACKET)
                threading.Thread(target=self.handle_sip, args=(data, addr), daemon=True).start()
            except OSError:
                if not self.running:
                    break

    def handle_sip(self, data: bytes, addr: Tuple[str, int]):
        msg = parse_sip_message(data)
        start_line = msg["start_line"]
        headers = msg["headers"]
        body = msg["body"]
        method = get_method(start_line)

        if not method:
            return

        logger.info(f"SIP RX [{method}] from {addr[0]}:{addr[1]}")

        if method == "INVITE":
            self.handle_invite(headers, body, addr)
        elif method == "ACK":
            logger.info(f"ACK received for Call-ID={get_header(headers, 'Call-ID')}")
        elif method == "BYE":
            self.handle_bye(headers, addr)
        elif method == "CANCEL":
            self.handle_cancel(headers, addr)
        elif method == "OPTIONS":
            self.handle_options(headers, addr)

    # ------------------------------------------------------------------------
    # SIP HANDLERS
    # ------------------------------------------------------------------------

    def handle_invite(self, headers: dict, body: str, addr: Tuple[str, int]):
        call_id = get_header(headers, "Call-ID")
        from_hdr = get_header(headers, "From")
        to_hdr = get_header(headers, "To")
        cseq = get_header(headers, "CSeq")

        if not call_id or not body:
            self.send_simple_response(addr, 400, "Bad Request", headers)
            return

        with self.lock:
            if call_id in self.call_to_session:
                logger.warning(f"Duplicate INVITE request for Call-ID={call_id}")
                return

        sdp = parse_sdp(body)
        if not sdp.connection_ip or not sdp.audio_port:
            self.send_simple_response(addr, 400, "Invalid SDP", headers)
            return

        group_uri = re.sub(r";tag=[^;>\s]+", "", to_hdr)

        with self.lock:
            session = self.find_session_by_group(group_uri)
            if session is None:
                session = MCPTTSession(session_id=uuid.uuid4().hex, group_uri=group_uri)
                self.sessions[session.session_id] = session
                logger.info(f"Creating new MCPTT session ID={session.session_id}")

            if len(session.legs) >= MAX_UE_PER_SESSION:
                logger.warning(f"Number of users in session {session.session_id} reached the maximum (2).")
                self.send_simple_response(addr, 486, "Busy Here", headers)
                return

        try:
            local_rtp_p, local_rtcp_p = self.allocate_media_ports()
        except RuntimeError:
            self.send_simple_response(addr, 503, "Service Unavailable", headers)
            return

        try:
            rtp_s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            rtp_s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            rtp_s.bind((self.rtp_bind_ip, local_rtp_p))

            rtcp_s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            rtcp_s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            rtcp_s.bind((self.rtp_bind_ip, local_rtcp_p))
        except OSError as e:
            self.release_media_ports(local_rtp_p, local_rtcp_p)
            logger.error(f"Error creating media sockets: {e}")
            self.send_simple_response(addr, 500, "Server Internal Error", headers)
            return

        local_tag = generate_tag()
        to_with_tag = add_or_replace_tag(to_hdr, local_tag)

        leg = CallLeg(
            call_id=call_id,
            from_header=from_hdr,
            to_header=to_with_tag,
            remote_sip_addr=addr,
            local_tag=local_tag,
            remote_media_ip=sdp.connection_ip,
            remote_rtp_port=sdp.audio_port,
            remote_rtcp_port=sdp.rtcp_port,
            local_rtp_port=local_rtp_p,
            local_rtcp_port=local_rtcp_p,
            rtp_socket=rtp_s,
            rtcp_socket=rtcp_s,
            sdp=sdp
        )

        with self.lock:
            session.legs[call_id] = leg
            self.call_to_session[call_id] = session.session_id

        answer_sdp = build_sdp_answer(self.advertise_ip, local_rtp_p, local_rtcp_p, sdp.selected_codec)

        resp_headers = {
            "Via": get_header(headers, "Via"),
            "From": from_hdr,
            "To": to_with_tag,
            "Call-ID": call_id,
            "CSeq": cseq,
            "Contact": f"<sip:{self.advertise_ip}:{self.sip_port}>",
            "Content-Type": "application/sdp"
        }

        self.send_sip_response(addr, 200, "OK", resp_headers, answer_sdp)
        logger.info(f"200 OK Sent | Call-ID={call_id} | Codec={sdp.selected_codec['name']} | RTP Port={local_rtp_p}")

        # Start audio processing and Floor Control threads
        threading.Thread(target=self.rtp_loop, args=(call_id,), name=f"RTP-{call_id[:6]}", daemon=True).start()
        threading.Thread(target=self.rtcp_loop, args=(call_id,), name=f"RTCP-{call_id[:6]}", daemon=True).start()

    def handle_bye(self, headers: dict, addr: Tuple[str, int]):
        call_id = get_header(headers, "Call-ID")
        self.send_simple_response(addr, 200, "OK", headers)
        if call_id:
            self.remove_call_leg(call_id)

    def handle_cancel(self, headers: dict, addr: Tuple[str, int]):
        call_id = get_header(headers, "Call-ID")
        self.send_simple_response(addr, 200, "OK", headers)
        if call_id:
            self.remove_call_leg(call_id)

    def handle_options(self, headers: dict, addr: Tuple[str, int]):
        resp_headers = {
            "Via": get_header(headers, "Via"),
            "From": get_header(headers, "From"),
            "To": get_header(headers, "To"),
            "Call-ID": get_header(headers, "Call-ID"),
            "CSeq": get_header(headers, "CSeq"),
            "Allow": "INVITE, ACK, BYE, CANCEL, OPTIONS"
        }
        self.send_sip_response(addr, 200, "OK", resp_headers)

    # ------------------------------------------------------------------------
    # RTP / RTCP MEDIA LOOPS & 3GPP FLOOR CONTROL
    # ------------------------------------------------------------------------

    def rtp_loop(self, call_id: str):
        leg, session = self.get_leg_and_session(call_id)
        if not leg or not session: return

        sock = leg.rtp_socket
        logger.info(f"RTP Forwarder started for Call-ID={call_id}")

        while self.running and leg.active:
            try:
                data, _ = sock.recvfrom(MAX_UDP_PACKET)
            except OSError:
                break

            if not data or len(data) < 12: continue
            leg.rtp_rx_packets += 1

            # Relay RTP packets to other users in the same session
            with self.lock:
                targets = [l for cid, l in session.legs.items() if cid != call_id and l.active]

            for dest in targets:
                try:
                    sock.sendto(data, (dest.remote_media_ip, dest.remote_rtp_port))
                    dest.rtp_tx_packets += 1
                except OSError as e:
                    logger.error(f"Error sending RTP to {dest.remote_media_ip}:{dest.remote_rtp_port} -> {e}")

    def rtcp_loop(self, call_id: str):
        leg, session = self.get_leg_and_session(call_id)
        if not leg or not session: return

        sock = leg.rtcp_socket
        logger.info(f"RTCP & Floor Control Handler started for Call-ID={call_id}")

        while self.running and leg.active:
            try:
                data, _ = sock.recvfrom(MAX_UDP_PACKET)
            except OSError:
                break

            if not data or len(data) < 4: continue
            leg.rtcp_rx_packets += 1

            # Processing 3GPP TS 24.380 Floor Control (MBCP) protocol
            # Check to identify RTCP APP packet (Packet Type 204)
            if len(data) >= 12 and data[1] == 204:
                name = data[8:12].decode('ascii', errors='ignore')
                if name == 'MCPT':
                    subtype = data[0] & 0x1F
                    logger.info(f"[3GPP TS 24.380] Received Floor Request packet (Subtype {subtype}) from Call-ID={call_id}")
                    # Automatically send Floor Granted response to the same client
                    self.send_3gpp_floor_grant(leg)

            # Also relay normal RTCP packets to the opposite client
            with self.lock:
                targets = [l for cid, l in session.legs.items() if cid != call_id and l.active]

            for dest in targets:
                try:
                    sock.sendto(data, (dest.remote_media_ip, dest.remote_rtcp_port))
                    dest.rtcp_tx_packets += 1
                except OSError:
                    pass

    def send_3gpp_floor_grant(self, leg: CallLeg):
        """
        Construct and send standard 3GPP TS 24.380 Floor Granted (MBCP) packet
        """
        # Byte 0: V=2 (10), P=0 (0), Subtype=2 Floor Granted (00010) -> 0x82
        # Byte 1: Packet Type = 204 (APP)
        # Bytes 2-3: Length = 3 words
        header = struct.pack('!BBH', 0x82, 204, 3)
        ssrc = 0x12345678  # Server SSRC
        name = b'MCPT'
        payload = struct.pack('!I', 0)  # Dummy Floor ID / Track ID TLV

        packet = header + struct.pack('!I', ssrc) + name + payload
        dest = (leg.remote_media_ip, leg.remote_rtcp_port)

        try:
            leg.rtcp_socket.sendto(packet, dest)
            logger.info(f"[3GPP TS 24.380] Sending Floor Granted to {leg.call_id} at {dest[0]}:{dest[1]}")
        except OSError as e:
            logger.error(f"Error sending Floor Granted packet: {e}")

    # ------------------------------------------------------------------------
    # SESSION & UTILITY HELPERS
    # ------------------------------------------------------------------------

    def get_leg_and_session(self, call_id: str) -> Tuple[Optional[CallLeg], Optional[MCPTTSession]]:
        with self.lock:
            session_id = self.call_to_session.get(call_id)
            if not session_id: return None, None
            session = self.sessions.get(session_id)
            if not session: return None, None
            return session.legs.get(call_id), session
        return None, None

    def find_session_by_group(self, group_uri: str) -> Optional[MCPTTSession]:
        for session in self.sessions.values():
            if session.group_uri == group_uri and len(session.legs) < MAX_UE_PER_SESSION:
                return session
        return None

    def send_sip_response(self, addr: Tuple[str, int], code: int, reason: str, headers: dict, body: str = ""):
        body_bytes = body.encode("utf-8") if body else b""
        lines = [f"SIP/2.0 {code} {reason}"]
        for k, v in headers.items():
            if v is not None:
                lines.append(f"{k}: {v}")
        lines.append(f"Content-Length: {len(body_bytes)}")

        msg = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8") + body_bytes
        try:
            self.sip_socket.sendto(msg, addr)
        except OSError as e:
            logger.error(f"Error sending SIP response to {addr}: {e}")

    def send_simple_response(self, addr: Tuple[str, int], code: int, reason: str, request_headers: dict):
        headers = {
            "Via": get_header(request_headers, "Via"),
            "From": get_header(request_headers, "From"),
            "To": get_header(request_headers, "To"),
            "Call-ID": get_header(request_headers, "Call-ID"),
            "CSeq": get_header(request_headers, "CSeq"),
        }
        self.send_sip_response(addr, code, reason, headers)

    def remove_call_leg(self, call_id: str):
        with self.lock:
            session_id = self.call_to_session.pop(call_id, None)
            if not session_id: return
            session = self.sessions.get(session_id)
            if not session: return
            leg = session.legs.pop(call_id, None)
            if not leg: return

            leg.active = False
            try: leg.rtp_socket.close()
            except OSError: pass
            try: leg.rtcp_socket.close()
            except OSError: pass

            self.release_media_ports(leg.local_rtp_port, leg.local_rtcp_port)

            logger.info(
                f"Removing Call-ID={call_id} | Statistics: "
                f"RTP RX={leg.rtp_rx_packets} TX={leg.rtp_tx_packets} | "
                f"RTCP RX={leg.rtcp_rx_packets} TX={leg.rtcp_tx_packets}"
            )

            if not session.legs:
                self.sessions.pop(session_id, None)
                logger.info(f"MCPTT session with ID {session_id} removed because it became empty.")

    def shutdown(self):
        logger.info("Shutting down MCPTT Server Mock...")
        self.running = False
        try: self.sip_socket.close()
        except OSError: pass

        with self.lock:
            calls = list(self.call_to_session.keys())
        for cid in calls:
            self.remove_call_leg(cid)
        logger.info("Server successfully shut down.")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    print("=" * 65)
    print("      MCPTT PHASE 1 UNIFIED SERVER MOCK (PRODUCTION READY)")
    print("=" * 65)
    print(f"SIP Listening     : {SIP_BIND_IP}:{SIP_PORT}")
    print(f"RTP Advertise IP  : {ADVERTISE_IP}")
    print(f"Codec Preference  : AMR-WB (PT 99, 16kHz)")
    print(f"Floor Control     : Enabled (3GPP TS 24.380 Auto-Grant)")
    print("=" * 65)

    server = MCPTTServer(
        sip_bind_ip=SIP_BIND_IP,
        sip_port=SIP_PORT,
        advertise_ip=ADVERTISE_IP,
        rtp_bind_ip=RTP_BIND_IP,
        rtp_start=RTP_PORT_START,
        rtp_end=RTP_PORT_END,
    )

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Exit key pressed by user.")
    finally:
        server.shutdown()