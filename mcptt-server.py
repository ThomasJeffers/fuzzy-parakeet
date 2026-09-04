#!/usr/bin/env python3
"""
=============================================================================
MCPTT Demo Application Server (single-file)
=============================================================================
UDP SIP AS + RTP mixer for the Android MCPTT PoC.

  python3 mcptt-server.py --advertise 172.30.104.240

Bind SIP/RTP to the advertise IP so replies keep the same 5-tuple the UPF
NATed (UE → advertise_ip:5070). Binding 0.0.0.0 often replies from docker0
and REGISTER/INVITE 200 never reach the phones.

Firewall: UDP 5070 and UDP 10000-20000.
=============================================================================
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import socket
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


SIP_PORT = 5070
ADVERTISE_IP = os.environ.get("ADVERTISE_IP", "172.30.104.240")
RTP_PORT_START = 10000
RTP_PORT_END = 20000
MAX_UE_PER_SESSION = 4
MAX_UDP_PACKET = 65535

PREFERRED_G711 = {"payload": 0, "name": "PCMU", "clock": 8000, "channels": 1, "fmtp": None}
FALLBACK_CODECS = {
    0: {"name": "PCMU", "clock": 8000, "channels": 1, "fmtp": None},
    8: {"name": "PCMA", "clock": 8000, "channels": 1, "fmtp": None},
    99: {"name": "AMR-WB", "clock": 16000, "channels": 1, "fmtp": "octet-align=1"},
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(threadName)-15s | %(message)s",
)
logger = logging.getLogger("MCPTT-AS")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class SDPInfo:
    connection_ip: Optional[str] = None
    audio_port: Optional[int] = None
    rtcp_port: Optional[int] = None
    payload_types: list = field(default_factory=list)
    selected_codec: dict = field(default_factory=dict)
    raw_sdp: str = ""


@dataclass
class CallLeg:
    call_id: str
    from_header: str
    to_header: str
    remote_sip_addr: Tuple[str, int]
    local_tag: str
    remote_tag: str
    remote_media_ip: str
    remote_rtp_port: int
    remote_rtcp_port: int
    local_rtp_port: int
    local_rtcp_port: int
    rtp_socket: socket.socket
    rtcp_socket: socket.socket
    sdp: SDPInfo
    media_learned: bool = False
    created_at: float = field(default_factory=time.time)
    active: bool = True
    rtp_rx_packets: int = 0
    rtp_tx_packets: int = 0
    rtcp_rx_packets: int = 0
    rtcp_tx_packets: int = 0


@dataclass
class MCPTTSession:
    session_id: str
    group_uri: str
    legs: Dict[str, CallLeg] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    floor_holder_call_id: Optional[str] = None


@dataclass
class Registration:
    user: str
    aor: str
    from_header: str
    contact: str
    addr: Tuple[str, int]
    updated_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# SIP helpers
# ---------------------------------------------------------------------------

def generate_tag() -> str:
    return uuid.uuid4().hex[:12]


def parse_sip_message(data: bytes) -> dict:
    """Parse SIP even when the client used LF, leftover indent, or a
    whitespace-only 'blank' line between headers and SDP (Kotlin trimIndent)."""
    text = data.decode("utf-8", errors="replace")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    header_part = normalized
    body = ""
    split = re.search(r"\n[ \t]*\n", normalized)
    if split:
        header_part = normalized[: split.start()]
        body = normalized[split.end() :]

    if "v=0" not in body:
        idx = normalized.find("\nv=0")
        if idx >= 0:
            body = normalized[idx + 1 :]
        elif normalized.lstrip().startswith("v=0"):
            body = normalized.lstrip()

    lines = [ln.strip() for ln in header_part.split("\n")]
    start_line = lines[0] if lines else ""
    headers: dict = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if key in headers:
            prev = headers[key]
            if not isinstance(prev, list):
                prev = [prev]
            prev.append(value)
            headers[key] = prev
        else:
            headers[key] = value

    return {
        "start_line": start_line.strip(),
        "headers": headers,
        "body": body.strip("\n") + ("\n" if body.strip() else ""),
        "raw": text,
    }


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


def extract_uri_user(header_or_uri: str) -> str:
    m = re.search(r"sip:([^@>;\s]+)", header_or_uri, re.IGNORECASE)
    return m.group(1).lower() if m else "unknown"


def canonical_uri(value: str) -> str:
    m = re.search(r"sip:[^>;\s]+", value, re.IGNORECASE)
    return m.group(0).rstrip(">").lower() if m else value.strip().lower()


def extract_from_tag(from_header: str) -> str:
    m = re.search(r"(?:^|;)\s*tag=([^;>\s]+)", from_header)
    return m.group(1) if m else ""


def parse_floor_action(body: str) -> Optional[str]:
    for line in body.splitlines():
        line = line.strip()
        if line.lower().startswith("action="):
            return line.split("=", 1)[1].strip().lower()
    lower = body.lower()
    if "floor-grant" in lower:
        return "floor-granted"
    if "floor-request" in lower:
        return "floor-request"
    if "floor-taken" in lower:
        return "floor-taken"
    if "floor-idle" in lower:
        return "floor-idle"
    if "floor-release" in lower:
        return "floor-release"
    return None


def bind_udp(ip: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((ip, port))
        return sock
    except OSError as exc:
        if ip in ("0.0.0.0", ""):
            sock.close()
            raise
        logger.warning("Bind %s:%s failed (%s) — falling back to 0.0.0.0:%s", ip, port, exc, port)
        sock.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        return sock


# ---------------------------------------------------------------------------
# SDP
# ---------------------------------------------------------------------------

def parse_sdp(sdp_text: str) -> SDPInfo:
    info = SDPInfo(raw_sdp=sdp_text)
    session_ip = None
    media_ip = None
    in_audio = False

    for raw in sdp_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("c=IN IP4 "):
            ip = line[9:].strip().split()[0]
            if in_audio:
                media_ip = ip
            else:
                session_ip = ip
        elif line.startswith("m=audio "):
            in_audio = True
            parts = line.split()
            if len(parts) >= 2:
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
            port_part = line.split(":", 1)[1].split()[0]
            try:
                info.rtcp_port = int(port_part)
            except ValueError:
                pass

    info.connection_ip = media_ip or session_ip
    if info.rtcp_port is None and info.audio_port is not None:
        info.rtcp_port = info.audio_port + 1

    selected = None
    for pt in info.payload_types:
        if pt in (0, 8) and pt in FALLBACK_CODECS:
            selected = FALLBACK_CODECS[pt].copy()
            selected["payload"] = pt
            break
    if selected is None:
        for pt in info.payload_types:
            if pt in FALLBACK_CODECS:
                selected = FALLBACK_CODECS[pt].copy()
                selected["payload"] = pt
                break
    info.selected_codec = selected or PREFERRED_G711.copy()
    return info


def build_sdp_answer(media_ip: str, rtp_port: int, rtcp_port: int, codec: dict) -> str:
    session_id = int(time.time() * 1000)
    pt = codec["payload"]
    lines = [
        "v=0",
        f"o=mcptt-server {session_id} 1 IN IP4 {media_ip}",
        "s=MCPTT-Mock",
        f"c=IN IP4 {media_ip}",
        "t=0 0",
        f"m=audio {rtp_port} RTP/AVP {pt}",
        f"a=rtpmap:{pt} {codec['name']}/{codec['clock']}",
    ]
    if codec.get("fmtp"):
        lines.append(f"a=fmtp:{pt} {codec['fmtp']}")
    lines.extend([f"a=rtcp:{rtcp_port} IN IP4 {media_ip}", "a=sendrecv", "a=mcptt"])
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class MCPTTServer:
    def __init__(
        self,
        sip_bind_ip: str,
        sip_port: int,
        advertise_ip: str,
        rtp_bind_ip: str,
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
        self.call_id_canonical: Dict[str, str] = {}
        self.registrations: Dict[str, Registration] = {}
        self.used_ports: Set[int] = set()

        self.lock = threading.RLock()
        self.running = True
        self._cseq_counter = 1000

        self.sip_socket = bind_udp(self.sip_bind_ip, self.sip_port)
        bound = self.sip_socket.getsockname()
        logger.info("SIP bound %s:%s (advertise %s)", bound[0], bound[1], self.advertise_ip)

        self.sip_thread = threading.Thread(target=self.sip_loop, name="SIP-Receiver", daemon=True)
        self.sip_thread.start()

    # -- lifecycle ----------------------------------------------------------

    def allocate_media_ports(self) -> Tuple[int, int]:
        with self.lock:
            port = self.rtp_start
            while port <= self.rtp_end - 1:
                if port not in self.used_ports and (port + 1) not in self.used_ports:
                    self.used_ports.add(port)
                    self.used_ports.add(port + 1)
                    return port, port + 1
                port += 2
        raise RuntimeError("RTP/RTCP port range is exhausted.")

    def release_media_ports(self, rtp_port: int, rtcp_port: int) -> None:
        with self.lock:
            self.used_ports.discard(rtp_port)
            self.used_ports.discard(rtcp_port)

    def next_cseq(self) -> int:
        with self.lock:
            self._cseq_counter += 1
            return self._cseq_counter

    def sip_loop(self) -> None:
        while self.running:
            try:
                data, addr = self.sip_socket.recvfrom(MAX_UDP_PACKET)
                threading.Thread(target=self.handle_sip, args=(data, addr), daemon=True).start()
            except OSError:
                if not self.running:
                    break

    def handle_sip(self, data: bytes, addr: Tuple[str, int]) -> None:
        try:
            msg = parse_sip_message(data)
            start_line = msg["start_line"]
            headers = msg["headers"]
            body = msg["body"]
            method = get_method(start_line)

            if not method:
                return

            call_id = get_header(headers, "Call-ID")
            logger.info(
                "SIP RX [%s] from %s:%s Call-ID=%s body=%sB",
                method,
                addr[0],
                addr[1],
                call_id or "-",
                len(body.strip()),
            )

            if method == "REGISTER":
                self.handle_register(headers, addr)
            elif method == "INVITE":
                self.handle_invite(headers, body, addr)
            elif method == "ACK":
                self.touch_leg_addr(call_id, addr)
                logger.info("ACK Call-ID=%s", call_id)
            elif method == "BYE":
                self.handle_bye(headers, addr)
            elif method == "CANCEL":
                self.handle_cancel(headers, addr)
            elif method == "OPTIONS":
                self.handle_options(headers, addr)
            elif method == "SUBSCRIBE":
                self.handle_subscribe(headers, addr)
            elif method == "INFO":
                self.handle_info(headers, body, addr)
            elif method == "MESSAGE":
                self.handle_message(headers, body, addr)
            else:
                self.send_simple_response(addr, 405, "Method Not Allowed", headers)
        except Exception:
            logger.exception("handle_sip crashed from %s", addr)

    def response_headers(self, request_headers: dict, extra: Optional[dict] = None) -> dict:
        headers = {
            "Via": get_header(request_headers, "Via"),
            "From": get_header(request_headers, "From"),
            "To": get_header(request_headers, "To"),
            "Call-ID": get_header(request_headers, "Call-ID"),
            "CSeq": get_header(request_headers, "CSeq"),
            "User-Agent": "MCPTT-Server-Mock/1.1",
        }
        if extra:
            headers.update(extra)
        return headers

    # -- REGISTER / SUBSCRIBE ----------------------------------------------

    def handle_register(self, headers: dict, addr: Tuple[str, int]) -> None:
        from_hdr = get_header(headers, "From")
        to_hdr = get_header(headers, "To")
        contact = get_header(headers, "Contact") or f"<sip:{self.advertise_ip}:{self.sip_port}>"
        expires = get_header(headers, "Expires") or "3600"
        user = extract_uri_user(from_hdr)
        aor = canonical_uri(from_hdr)

        if expires == "0" or "expires=0" in contact.lower():
            with self.lock:
                self.registrations.pop(user, None)
            logger.info("REGISTER de-register %s", user)
        else:
            with self.lock:
                self.registrations[user] = Registration(
                    user=user,
                    aor=aor,
                    from_header=from_hdr,
                    contact=contact,
                    addr=addr,
                )
            logger.info("REGISTER stored %s -> %s", user, addr)

        to_with_tag = add_or_replace_tag(to_hdr, generate_tag())
        self.send_sip_response(
            addr,
            200,
            "OK",
            self.response_headers(
                headers,
                {
                    "To": to_with_tag,
                    "Contact": contact,
                    "Expires": expires,
                    "Allow": "INVITE, ACK, BYE, CANCEL, OPTIONS, INFO, MESSAGE, REGISTER, SUBSCRIBE",
                },
            ),
        )

    def handle_subscribe(self, headers: dict, addr: Tuple[str, int]) -> None:
        to_hdr = add_or_replace_tag(get_header(headers, "To"), generate_tag())
        self.send_sip_response(
            addr,
            200,
            "OK",
            self.response_headers(headers, {"To": to_hdr, "Expires": get_header(headers, "Expires") or "3600"}),
        )
        logger.info("SUBSCRIBE accepted from %s", addr)

    # -- INVITE / dialog ---------------------------------------------------

    def handle_invite(self, headers: dict, body: str, addr: Tuple[str, int]) -> None:
        call_id = get_header(headers, "Call-ID")
        from_hdr = get_header(headers, "From")
        to_hdr = get_header(headers, "To")

        if not call_id:
            logger.warning("INVITE missing Call-ID from %s; headers=%s", addr, list(headers.keys()))
            self.send_simple_response(addr, 400, "Bad Request", headers)
            return

        self.send_simple_response(addr, 100, "Trying", headers)

        sdp = parse_sdp(body)
        if not sdp.audio_port:
            logger.warning(
                "INVITE Call-ID=%s has no m=audio (body_len=%s preview=%r)",
                call_id,
                len(body),
                body[:180],
            )
            self.send_simple_response(addr, 400, "Invalid SDP", headers)
            return

        if not sdp.connection_ip:
            sdp.connection_ip = addr[0]
            logger.info("INVITE missing c= — using packet source %s", addr[0])

        group_uri = canonical_uri(to_hdr)

        with self.lock:
            existing = self.get_leg_and_session(call_id)
            if existing[0] is not None:
                leg, _session = existing
                leg.remote_sip_addr = addr
                logger.warning("Retransmitted INVITE Call-ID=%s — re-sending 200 OK", call_id)
                answer_sdp = build_sdp_answer(
                    self.advertise_ip, leg.local_rtp_port, leg.local_rtcp_port, leg.sdp.selected_codec
                )
                self.send_sip_response(
                    addr,
                    200,
                    "OK",
                    self.response_headers(
                        headers,
                        {
                            "To": leg.to_header,
                            "Contact": f"<sip:{self.advertise_ip}:{self.sip_port}>",
                            "Content-Type": "application/sdp",
                            "Allow": "INVITE, ACK, BYE, CANCEL, OPTIONS, INFO, MESSAGE",
                        },
                    ),
                    answer_sdp,
                )
                return

            session = self.find_session_by_group(group_uri)
            if session is None:
                session = MCPTTSession(session_id=uuid.uuid4().hex, group_uri=group_uri)
                self.sessions[session.session_id] = session
                logger.info("New MCPTT session %s group=%s", session.session_id, group_uri)

            if len(session.legs) >= MAX_UE_PER_SESSION:
                logger.warning("Session %s full", session.session_id)
                self.send_simple_response(addr, 486, "Busy Here", headers)
                return

        try:
            local_rtp_p, local_rtcp_p = self.allocate_media_ports()
        except RuntimeError:
            self.send_simple_response(addr, 503, "Service Unavailable", headers)
            return

        try:
            rtp_s = bind_udp(self.rtp_bind_ip, local_rtp_p)
            rtcp_s = bind_udp(self.rtp_bind_ip, local_rtcp_p)
        except OSError as exc:
            self.release_media_ports(local_rtp_p, local_rtcp_p)
            logger.error("Media socket bind failed: %s", exc)
            self.send_simple_response(addr, 500, "Server Internal Error", headers)
            return

        local_tag = generate_tag()
        to_with_tag = add_or_replace_tag(to_hdr, local_tag)
        remote_tag = extract_from_tag(from_hdr)

        # Prefer SDP address if it looks like a UE pool IP; still learn NAT later.
        media_ip = sdp.connection_ip
        media_port = sdp.audio_port

        leg = CallLeg(
            call_id=call_id,
            from_header=from_hdr,
            to_header=to_with_tag,
            remote_sip_addr=addr,
            local_tag=local_tag,
            remote_tag=remote_tag,
            remote_media_ip=media_ip,
            remote_rtp_port=media_port,
            remote_rtcp_port=sdp.rtcp_port or (media_port + 1),
            local_rtp_port=local_rtp_p,
            local_rtcp_port=local_rtcp_p,
            rtp_socket=rtp_s,
            rtcp_socket=rtcp_s,
            sdp=sdp,
        )

        with self.lock:
            live = self.find_session_by_group(group_uri)
            if live is not None:
                session = live
            elif session.session_id not in self.sessions:
                self.sessions[session.session_id] = session
            if len(session.legs) >= MAX_UE_PER_SESSION:
                logger.warning("Session %s full at insert", session.session_id)
                try:
                    rtp_s.close()
                    rtcp_s.close()
                except OSError:
                    pass
                self.release_media_ports(local_rtp_p, local_rtcp_p)
                self.send_simple_response(addr, 486, "Busy Here", headers)
                return
            session.legs[call_id] = leg
            self.call_to_session[call_id] = session.session_id
            self.call_id_canonical[call_id] = call_id

        answer_sdp = build_sdp_answer(self.advertise_ip, local_rtp_p, local_rtcp_p, sdp.selected_codec)
        self.send_sip_response(
            addr,
            200,
            "OK",
            self.response_headers(
                headers,
                {
                    "To": to_with_tag,
                    "Contact": f"<sip:{self.advertise_ip}:{self.sip_port}>",
                    "Content-Type": "application/sdp",
                    "Allow": "INVITE, ACK, BYE, CANCEL, OPTIONS, INFO, MESSAGE",
                },
            ),
            answer_sdp,
        )
        logger.info(
            "200 OK INVITE Call-ID=%s codec=%s RTP %s:%s  offer %s:%s  sip-src %s",
            call_id,
            sdp.selected_codec.get("name"),
            self.advertise_ip,
            local_rtp_p,
            media_ip,
            media_port,
            addr,
        )

        threading.Thread(target=self.rtp_loop, args=(call_id,), name=f"RTP-{call_id[:8]}", daemon=True).start()
        threading.Thread(target=self.rtcp_loop, args=(call_id,), name=f"RTCP-{call_id[:8]}", daemon=True).start()

        # Late joiner: tell them who currently holds the floor (INVITE itself is not a floor event).
        holder_user = None
        with self.lock:
            holder_cid = session.floor_holder_call_id
            if holder_cid and holder_cid != call_id:
                holder_leg = session.legs.get(holder_cid)
                if holder_leg:
                    holder_user = extract_uri_user(holder_leg.from_header)
        if holder_user:
            self.send_floor_info_to_leg(leg, "floor-taken", holder_user)
            logger.info("Late joiner Call-ID=%s notified floor-taken by %s", call_id, holder_user)

    def touch_leg_addr(self, call_id: str, addr: Tuple[str, int]) -> None:
        leg, _ = self.get_leg_and_session(call_id)
        if leg:
            leg.remote_sip_addr = addr

    def get_leg_and_session(self, call_id: str) -> Tuple[Optional[CallLeg], Optional[MCPTTSession]]:
        if not call_id:
            return None, None
        with self.lock:
            canon = self.call_id_canonical.get(call_id, call_id)
            session_id = self.call_to_session.get(canon) or self.call_to_session.get(call_id)
            if not session_id:
                return None, None
            session = self.sessions.get(session_id)
            if not session:
                return None, None
            return session.legs.get(canon) or session.legs.get(call_id), session

    def recover_dialog(
        self, call_id: str, headers: dict, addr: Tuple[str, int]
    ) -> Tuple[Optional[CallLeg], Optional[MCPTTSession]]:
        user = extract_uri_user(get_header(headers, "From"))
        with self.lock:
            for session in self.sessions.values():
                for leg in session.legs.values():
                    if not leg.active:
                        continue
                    same_user = extract_uri_user(leg.from_header) == user
                    same_addr = leg.remote_sip_addr[0] == addr[0]
                    if same_user or (same_addr and addr[1] == leg.remote_sip_addr[1]):
                        if call_id:
                            self.call_to_session[call_id] = session.session_id
                            self.call_id_canonical[call_id] = leg.call_id
                        leg.remote_sip_addr = addr
                        logger.info(
                            "Recovered dialog user=%s INFO Call-ID=%s -> leg %s",
                            user,
                            call_id,
                            leg.call_id,
                        )
                        return leg, session
        return None, None

    def find_session_by_group(self, group_uri: str) -> Optional[MCPTTSession]:
        for session in self.sessions.values():
            if session.group_uri == group_uri and len(session.legs) < MAX_UE_PER_SESSION:
                return session
        for session in self.sessions.values():
            if session.group_uri == group_uri:
                return session
        return None

    # -- INFO / MESSAGE ----------------------------------------------------

    def handle_info(self, headers: dict, body: str, addr: Tuple[str, int]) -> None:
        call_id = get_header(headers, "Call-ID")
        action = parse_floor_action(body) or ""
        self.touch_leg_addr(call_id, addr)

        leg, session = self.get_leg_and_session(call_id)
        if (not leg or not session) and call_id:
            leg, session = self.recover_dialog(call_id, headers, addr)

        extra = {"Content-Type": "text/plain"}
        reply_body = ""

        if not leg or not session:
            logger.warning("INFO unknown Call-ID=%s action=%s from %s", call_id, action, addr)
            self.send_sip_response(addr, 200, "OK", self.response_headers(headers, extra), reply_body)
            return

        user = extract_uri_user(get_header(headers, "From") or leg.from_header)
        logger.info("Floor INFO action=%s from %s Call-ID=%s", action, user, leg.call_id)

        if action in ("floor-request", "floor-granted"):
            with self.lock:
                session.floor_holder_call_id = leg.call_id
            reply_body = f"Action=floor-granted\r\nUser={user}\r\n"
            self.send_sip_response(addr, 200, "OK", self.response_headers(headers, extra), reply_body)
            self.send_floor_info_to_leg(leg, "floor-granted", user)
            for other in self.peer_legs(session, leg.call_id):
                self.send_floor_info_to_leg(other, "floor-taken", user)
            return

        if action in ("floor-release", "floor-idle"):
            with self.lock:
                if session.floor_holder_call_id == leg.call_id:
                    session.floor_holder_call_id = None
            reply_body = f"Action=floor-idle\r\nUser={user}\r\n"
            self.send_sip_response(addr, 200, "OK", self.response_headers(headers, extra), reply_body)
            self.send_floor_info_to_leg(leg, "floor-idle", user)
            for other in self.peer_legs(session, leg.call_id):
                self.send_floor_info_to_leg(other, "floor-idle", user)
            return

        self.send_sip_response(addr, 200, "OK", self.response_headers(headers, extra), reply_body)

    def handle_message(self, headers: dict, body: str, addr: Tuple[str, int]) -> None:
        call_id = get_header(headers, "Call-ID")
        from_hdr = get_header(headers, "From")
        to_hdr = get_header(headers, "To")
        self.send_simple_response(addr, 200, "OK", headers)
        logger.info("MESSAGE from %s body=%r", extract_uri_user(from_hdr), body[:120])

        sender_user = extract_uri_user(from_hdr)
        sender_addr = addr
        targets: List[Tuple[str, Tuple[str, int]]] = []

        leg, session = self.get_leg_and_session(call_id) if call_id else (None, None)
        if session is None:
            to_uri = canonical_uri(to_hdr)
            with self.lock:
                session = self.find_session_by_group(to_uri)

        if session:
            for other_cid, other in list(session.legs.items()):
                if not other.active:
                    continue
                if extract_uri_user(other.from_header) == sender_user:
                    continue
                if other.remote_sip_addr == sender_addr:
                    continue
                targets.append((other.from_header, other.remote_sip_addr))

        with self.lock:
            for user, reg in self.registrations.items():
                if user == sender_user:
                    continue
                if any(t[1] == reg.addr for t in targets):
                    continue
                targets.append((reg.from_header, reg.addr))

        if not targets:
            logger.warning("MESSAGE not relayed (no other UE registered/in-session)")
            return

        for dest_from, dest_addr in targets:
            self.relay_message(dest_from, dest_addr, from_hdr, to_hdr, body)

    def handle_bye(self, headers: dict, addr: Tuple[str, int]) -> None:
        call_id = get_header(headers, "Call-ID")
        self.send_simple_response(addr, 200, "OK", headers)
        if call_id:
            self.remove_call_leg(call_id)

    def handle_cancel(self, headers: dict, addr: Tuple[str, int]) -> None:
        call_id = get_header(headers, "Call-ID")
        self.send_simple_response(addr, 200, "OK", headers)
        if call_id:
            self.remove_call_leg(call_id)

    def handle_options(self, headers: dict, addr: Tuple[str, int]) -> None:
        self.send_sip_response(
            addr,
            200,
            "OK",
            self.response_headers(
                headers,
                {"Allow": "INVITE, ACK, BYE, CANCEL, OPTIONS, INFO, MESSAGE, REGISTER, SUBSCRIBE"},
            ),
        )

    def peer_legs(self, session: MCPTTSession, call_id: str) -> List[CallLeg]:
        with self.lock:
            return [leg for cid, leg in session.legs.items() if cid != call_id and leg.active]

    def send_floor_info_to_leg(self, leg: CallLeg, action: str, user: str) -> None:
        body = (
            "[MCPTT_FLOOR_CONTROL]\r\n"
            f"Action={action}\r\n"
            f"User={user}\r\n"
            f"Timestamp={int(time.time() * 1000)}\r\n"
        )
        cseq = self.next_cseq()
        m = re.search(r"<([^>]+)>", leg.from_header)
        request_uri = m.group(1) if m else canonical_uri(leg.from_header)
        lines = [
            f"INFO {request_uri} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.advertise_ip}:{self.sip_port};rport;branch=z9hG4bK{generate_tag()}",
            f"From: <sip:mcptt-as@{self.advertise_ip}>;tag={leg.local_tag}",
            f"To: {leg.from_header}",
            f"Call-ID: {leg.call_id}",
            f"CSeq: {cseq} INFO",
            f"Contact: <sip:{self.advertise_ip}:{self.sip_port}>",
            "User-Agent: MCPTT-Server-Mock/1.1",
            "Content-Type: text/plain",
            f"Content-Length: {len(body.encode('utf-8'))}",
            "",
            body,
        ]
        msg = "\r\n".join(lines).encode("utf-8")
        try:
            self.sip_socket.sendto(msg, leg.remote_sip_addr)
            logger.info("Floor INFO %s -> %s Call-ID=%s", action, leg.remote_sip_addr, leg.call_id)
        except OSError as exc:
            logger.error("Failed sending floor INFO: %s", exc)

    def relay_message(
        self,
        dest_from: str,
        dest_addr: Tuple[str, int],
        from_hdr: str,
        to_hdr: str,
        body: str,
    ) -> None:
        cseq = self.next_cseq()
        m = re.search(r"<([^>]+)>", dest_from)
        request_uri = m.group(1) if m else canonical_uri(dest_from)
        body_bytes = body.encode("utf-8")
        lines = [
            f"MESSAGE {request_uri} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.advertise_ip}:{self.sip_port};rport;branch=z9hG4bK{generate_tag()}",
            f"From: {from_hdr}",
            f"To: {dest_from}",
            f"Call-ID: msg-{generate_tag()}@{self.advertise_ip}",
            f"CSeq: {cseq} MESSAGE",
            f"Contact: <sip:{self.advertise_ip}:{self.sip_port}>",
            "User-Agent: MCPTT-Server-Mock/1.1",
            "Content-Type: text/plain",
            f"Content-Length: {len(body_bytes)}",
            "",
            body,
        ]
        msg = "\r\n".join(lines).encode("utf-8")
        try:
            self.sip_socket.sendto(msg, dest_addr)
            logger.info("Relayed MESSAGE to %s", dest_addr)
        except OSError as exc:
            logger.error("Failed relaying MESSAGE: %s", exc)

    # -- RTP ---------------------------------------------------------------

    def learn_media(self, leg: CallLeg, src: Tuple[str, int], kind: str) -> None:
        if kind == "rtp":
            if not leg.media_learned or (leg.remote_media_ip, leg.remote_rtp_port) != src:
                logger.info(
                    "Symmetric RTP learned Call-ID=%s %s:%s -> %s:%s",
                    leg.call_id,
                    leg.remote_media_ip,
                    leg.remote_rtp_port,
                    src[0],
                    src[1],
                )
            leg.remote_media_ip, leg.remote_rtp_port = src
            if not leg.media_learned:
                leg.remote_rtcp_port = src[1] + 1
            leg.media_learned = True
        else:
            leg.remote_rtcp_port = src[1]
            if not leg.media_learned:
                leg.remote_media_ip = src[0]

    def rtp_loop(self, call_id: str) -> None:
        leg, session = self.get_leg_and_session(call_id)
        if not leg or not session:
            return
        sock = leg.rtp_socket
        logger.info("RTP forwarder Call-ID=%s listening %s", call_id, sock.getsockname())
        while self.running and leg.active:
            try:
                data, src = sock.recvfrom(MAX_UDP_PACKET)
            except OSError:
                break
            if not data or len(data) < 12:
                continue
            leg.rtp_rx_packets += 1
            self.learn_media(leg, src, "rtp")
            if leg.rtp_rx_packets == 1 or leg.rtp_rx_packets % 50 == 0:
                logger.info(
                    "RTP rx=%s Call-ID=%s src=%s:%s peers=%s",
                    leg.rtp_rx_packets,
                    call_id,
                    src[0],
                    src[1],
                    len(session.legs) - 1,
                )
            with self.lock:
                holder = session.floor_holder_call_id
                targets = [other for cid, other in session.legs.items() if cid != call_id and other.active]
            if holder and holder != call_id:
                continue
            for dest in targets:
                # MUST send from the peer's RTP socket (its advertised AS port).
                # sock is THIS leg's socket. Sending from it hairpins UPF SNAT
                # (both UEs often map to 172.22.0.8:40000) back to the talker.
                if not dest.media_learned or not dest.remote_media_ip:
                    continue
                try:
                    dest.rtp_socket.sendto(data, (dest.remote_media_ip, dest.remote_rtp_port))
                    dest.rtp_tx_packets += 1
                    if dest.rtp_tx_packets == 1 or dest.rtp_tx_packets % 50 == 0:
                        logger.info(
                            "RTP fwd from %s:%s -> %s:%s (peer Call-ID=%s tx=%s)",
                            dest.rtp_socket.getsockname()[0],
                            dest.local_rtp_port,
                            dest.remote_media_ip,
                            dest.remote_rtp_port,
                            dest.call_id[:8],
                            dest.rtp_tx_packets,
                        )
                except OSError as exc:
                    logger.error("RTP send %s:%s failed: %s", dest.remote_media_ip, dest.remote_rtp_port, exc)

    def rtcp_loop(self, call_id: str) -> None:
        leg, session = self.get_leg_and_session(call_id)
        if not leg or not session:
            return
        sock = leg.rtcp_socket
        while self.running and leg.active:
            try:
                data, src = sock.recvfrom(MAX_UDP_PACKET)
            except OSError:
                break
            if not data or len(data) < 4:
                continue
            leg.rtcp_rx_packets += 1
            self.learn_media(leg, src, "rtcp")
            if len(data) >= 12 and data[1] == 204:
                name = data[8:12].decode("ascii", errors="ignore")
                if name == "MCPT":
                    logger.info("[MBCP] Floor request Call-ID=%s", call_id)
                    self.send_3gpp_floor_grant(leg)
                    with self.lock:
                        session.floor_holder_call_id = call_id
                    user = extract_uri_user(leg.from_header)
                    self.send_floor_info_to_leg(leg, "floor-granted", user)
                    for other in self.peer_legs(session, call_id):
                        self.send_floor_info_to_leg(other, "floor-taken", user)
            with self.lock:
                targets = [other for cid, other in session.legs.items() if cid != call_id and other.active]
            for dest in targets:
                try:
                    dest.rtcp_socket.sendto(data, (dest.remote_media_ip, dest.remote_rtcp_port))
                    dest.rtcp_tx_packets += 1
                except OSError:
                    pass

    def send_3gpp_floor_grant(self, leg: CallLeg) -> None:
        packet = struct.pack("!BBH", 0x82, 204, 3) + struct.pack("!I", 0x12345678) + b"MCPT" + struct.pack("!I", 0)
        dest = (leg.remote_media_ip, leg.remote_rtcp_port)
        try:
            leg.rtcp_socket.sendto(packet, dest)
            logger.info("[MBCP] Floor Granted -> %s", dest)
        except OSError as exc:
            logger.error("Error sending Floor Granted: %s", exc)

    # -- tx helpers --------------------------------------------------------

    def send_sip_response(self, addr: Tuple[str, int], code: int, reason: str, headers: dict, body: str = "") -> None:
        body_bytes = body.encode("utf-8") if body else b""
        lines = [f"SIP/2.0 {code} {reason}"]
        for key, value in headers.items():
            if value is not None:
                lines.append(f"{key}: {value}")
        if not any(k.lower() == "content-length" for k in headers):
            lines.append(f"Content-Length: {len(body_bytes)}")
        msg = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8") + body_bytes
        try:
            self.sip_socket.sendto(msg, addr)
        except OSError as exc:
            logger.error("SIP TX failed to %s: %s", addr, exc)

    def send_simple_response(self, addr: Tuple[str, int], code: int, reason: str, request_headers: dict) -> None:
        self.send_sip_response(addr, code, reason, self.response_headers(request_headers))

    def remove_call_leg(self, call_id: str) -> None:
        with self.lock:
            canon = self.call_id_canonical.get(call_id, call_id)
            session_id = self.call_to_session.pop(canon, None) or self.call_to_session.pop(call_id, None)
            aliases = [k for k, v in self.call_id_canonical.items() if v == canon or k == call_id]
            for alias in aliases:
                self.call_id_canonical.pop(alias, None)
                self.call_to_session.pop(alias, None)
            if not session_id:
                return
            session = self.sessions.get(session_id)
            if not session:
                return
            leg = session.legs.pop(canon, None) or session.legs.pop(call_id, None)
            if not leg:
                return
            if session.floor_holder_call_id in (call_id, canon):
                session.floor_holder_call_id = None
            leg.active = False
            for sock in (leg.rtp_socket, leg.rtcp_socket):
                try:
                    sock.close()
                except OSError:
                    pass
            self.release_media_ports(leg.local_rtp_port, leg.local_rtcp_port)
            logger.info(
                "Removed Call-ID=%s RTP rx=%s tx=%s",
                canon,
                leg.rtp_rx_packets,
                leg.rtp_tx_packets,
            )
            if not session.legs:
                self.sessions.pop(session_id, None)
                logger.info("Session %s empty — removed", session_id)

    def shutdown(self) -> None:
        logger.info("Shutting down MCPTT Server...")
        self.running = False
        try:
            self.sip_socket.close()
        except OSError:
            pass
        with self.lock:
            calls = list(self.call_to_session.keys())
        for cid in calls:
            self.remove_call_leg(cid)
        logger.info("Server successfully shut down.")


def main() -> None:
    parser = argparse.ArgumentParser(description="MCPTT demo Application Server")
    parser.add_argument("--advertise", default=ADVERTISE_IP, help="IP UEs must reach (host/LAN IP)")
    parser.add_argument("--sip-port", type=int, default=SIP_PORT)
    parser.add_argument(
        "--sip-bind",
        default="advertise",
        help="SIP bind IP: 'advertise' (recommended), '0.0.0.0', or a concrete IP",
    )
    parser.add_argument("--rtp-bind", default="advertise", help="RTP bind IP (same meaning as --sip-bind)")
    args = parser.parse_args()

    advertise = args.advertise
    sip_bind = advertise if args.sip_bind == "advertise" else args.sip_bind
    rtp_bind = advertise if args.rtp_bind == "advertise" else args.rtp_bind

    print("=" * 65)
    print("      MCPTT DEMO APPLICATION SERVER")
    print("=" * 65)
    print(f"SIP bind          : {sip_bind}:{args.sip_port}")
    print(f"Advertise IP      : {advertise}")
    print(f"RTP bind          : {rtp_bind}  ports {RTP_PORT_START}-{RTP_PORT_END}")
    print("Codec preference  : PCMU/PCMA")
    print("Floor control     : SIP INFO (grant in 200 OK + INFO)")
    print("Direct-AS clients : UDP SIP to ADVERTISE_IP:5070")
    print("=" * 65)

    server = MCPTTServer(
        sip_bind_ip=sip_bind,
        sip_port=args.sip_port,
        advertise_ip=advertise,
        rtp_bind_ip=rtp_bind,
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Exit key pressed by user.")
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
