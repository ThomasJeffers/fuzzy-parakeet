#!/usr/bin/env python3
"""Experiment 5 UAC: Digest REGISTER + INVITE + ACK + optional floor INFO.

One UDP socket, bound to the UE IMS IP:5062, for the whole sequence.

Do not use sipsak for INVITE/INFO. sipsak REGISTER/INVITE send from an
ephemeral port (your traces: rport=45865 / 37822) while Contact says :5062.
ACK still works (INVITE transaction). INFO is a new in-dialog request:
P-CSCF loose_route() needs the 200 OK Record-Route *reversed* (P-CSCF first)
and the same source port as REGISTER. Wrong Route + wrong port = silent drop.

Copy to Demo, then (after both UEs have IMS IPs and can ping 172.22.0.21):

  # Terminal A — UE2 registers, joins group1, holds the socket
  sudo ip netns exec ue2 python3 exp5_uac.py \\
    --bind "$UE2_IP" --imsi 491234567890124 --password "$K2" --role join

  # Wait until it prints holding dialog, then Terminal B — UE1 floor
  sudo ip netns exec ue1 python3 exp5_uac.py \\
    --bind "$UE1_IP" --imsi 491234567890123 --password "$K" --role floor
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import socket
import struct
import time
import uuid


PCSCF = ("172.22.0.21", 5060)
REALM = "ims.mnc070.mcc901.3gppnetwork.org"
GROUP = f"sip:group1@{REALM}"
REG_URI = f"sip:{REALM}"
AS_FALLBACK = "sip:172.30.104.240:5070;transport=udp"
ORIG_ROUTE = f"sip:orig@scscf.{REALM}:6060;lr"


def md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def hdr_values(msg: str, name: str) -> list[str]:
    key = name.lower() + ":"
    out: list[str] = []
    for line in msg.replace("\r\n", "\n").split("\n"):
        if line.lower().startswith(key):
            out.append(line.split(":", 1)[1].strip())
    return out


def hdr(msg: str, name: str) -> str:
    vals = hdr_values(msg, name)
    return vals[0] if vals else ""


def strip_angles(value: str) -> str:
    value = value.strip()
    if value.startswith("<") and ">" in value:
        return value[1 : value.index(">")]
    return value.split(";", 1)[0].strip()


def status_code(msg: str) -> int:
    m = re.match(r"SIP/2.0\s+(\d+)", msg)
    return int(m.group(1)) if m else 0


def to_tag(msg: str) -> str:
    m = re.search(r"[;\s]tag=([^;>\s]+)", hdr(msg, "To"), re.I)
    return m.group(1) if m else ""


def contact_uri(msg: str) -> str:
    raw = hdr(msg, "Contact")
    return strip_angles(raw) if raw else AS_FALLBACK


def record_routes(msg: str) -> list[str]:
    return [strip_angles(v) for v in hdr_values(msg, "Record-Route")]


def uac_route_set(rr: list[str]) -> list[str]:
    return list(reversed(rr))


def sdp_c_and_m(msg: str) -> tuple[str, int, int]:
    """c=/m= from the 200 OK the UE actually received (after any proxy rewrite)."""
    parts = msg.replace("\r\n", "\n").split("\n\n", 1)
    body = parts[1] if len(parts) > 1 else msg
    ip = ""
    port = 0
    rtcp = 0
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("c=IN IP4 "):
            ip = line.split()[2]
        elif line.startswith("m=audio "):
            try:
                port = int(line.split()[1])
            except ValueError:
                port = 0
        elif line.startswith("a=rtcp:"):
            try:
                rtcp = int(line.split(":", 1)[1].split()[0])
            except ValueError:
                rtcp = 0
    return ip, port, rtcp or (port + 1 if port else 0)


def send_pcmu(bind_ip: str, local_port: int, dest_ip: str, dest_port: int, seconds: float) -> int:
    """20 ms PCMU/8000 silence. AS only needs packets, not audible audio."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((bind_ip, local_port))
    ssrc = uuid.uuid4().int & 0xFFFFFFFF
    seq = 0
    ts = 0
    payload = b"\xff" * 160
    print(f"RTP PCMU {bind_ip}:{local_port} -> {dest_ip}:{dest_port} for {seconds:.0f}s")
    end = time.time() + seconds
    while time.time() < end:
        pkt = struct.pack("!BBHII", 0x80, 0, seq & 0xFFFF, ts & 0xFFFFFFFF, ssrc) + payload
        sock.sendto(pkt, (dest_ip, dest_port))
        seq += 1
        ts = (ts + 160) & 0xFFFFFFFF
        time.sleep(0.02)
    sock.close()
    print(f"RTP sent {seq} packets")
    return seq


def mbcp_pack_request(ssrc: int, user_id: str) -> bytes:
    """TS 24.380 Floor Request (subtype 0, name MCPT). Compact UAC copy of AS encoder."""
    uid = user_id.encode("utf-8")
    field = bytes([6, len(uid)]) + uid
    field += b"\x00" * ((4 - (len(field) % 4)) % 4)
    prio = bytes([0, 2, 0, 0])
    ind = bytes([13, 2]) + struct.pack("!H", 0x8000)
    payload = prio + field + ind
    payload += b"\x00" * ((4 - (len(payload) % 4)) % 4)
    body = struct.pack("!I", ssrc & 0xFFFFFFFF) + b"MCPT" + payload
    total = 4 + len(body)
    header = struct.pack("!BBH", 0x80, 204, total // 4 - 1)
    return header + body


def mbcp_recv_name(packet: bytes) -> str:
    if len(packet) < 12 or packet[1] != 204 or packet[8:12] != b"MCPT":
        return ""
    names = {0: "Floor Request", 1: "Floor Granted", 2: "Floor Taken", 3: "Floor Deny",
             4: "Floor Release", 5: "Floor Idle"}
    return names.get(packet[0] & 0x1F, f"subtype-{packet[0] & 0x1F}")


def send_mbcp_floor_request(
    bind_ip: str,
    local_rtcp: int,
    dest_ip: str,
    dest_rtcp: int,
    user_id: str,
    wait: float = 4.0,
) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((bind_ip, local_rtcp))
    ssrc = uuid.uuid4().int & 0xFFFFFFFF
    pkt = mbcp_pack_request(ssrc, user_id)
    print(f"MBCP Floor Request {bind_ip}:{local_rtcp} -> {dest_ip}:{dest_rtcp}")
    sock.sendto(pkt, (dest_ip, dest_rtcp))
    sock.settimeout(wait)
    seen = ""
    try:
        data, src = sock.recvfrom(65535)
        seen = mbcp_recv_name(data)
        print(f"MBCP RX {seen or 'non-MCPT'} from {src[0]}:{src[1]}")
    except socket.timeout:
        print("MBCP no reply (AS may still log RX if RTCP dest was rewritten)")
    finally:
        sock.close()
    return seen


def auth_param(www: str, name: str) -> str:
    m = re.search(rf'{name}=(?:"([^"]+)"|([^,\s]+))', www, re.I)
    if not m:
        return ""
    return m.group(1) or m.group(2) or ""


def digest_authorization(www: str, username: str, password: str, method: str, uri: str) -> str:
    realm = auth_param(www, "realm") or REALM
    nonce = auth_param(www, "nonce")
    qop = auth_param(www, "qop") or "auth"
    if "," in qop:
        qop = qop.split(",", 1)[0].strip().strip('"')
    cnonce = uuid.uuid4().hex[:8]
    nc = "00000001"
    ha1 = md5_hex(f"{username}:{realm}:{password}")
    ha2 = md5_hex(f"{method}:{uri}")
    if qop:
        resp = md5_hex(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
        qop_part = f', qop={qop}, nc={nc}, cnonce="{cnonce}"'
    else:
        resp = md5_hex(f"{ha1}:{nonce}:{ha2}")
        qop_part = ""
    return (
        f'Digest username="{username}", uri="{uri}", algorithm=MD5, '
        f'realm="{realm}", nonce="{nonce}"{qop_part}, response="{resp}"'
    )


def sip_request(
    method: str,
    ruri: str,
    *,
    bind_ip: str,
    port: int,
    from_uri: str,
    from_tag: str,
    to_uri: str,
    to_tag: str,
    call_id: str,
    cseq: int,
    contact: str,
    routes: list[str],
    body: bytes = b"",
    extra: list[str] | None = None,
    content_type: str | None = None,
) -> bytes:
    branch = "z9hG4bK-" + uuid.uuid4().hex[:12]
    to = f"<{to_uri}>"
    if to_tag:
        to += f";tag={to_tag}"
    lines = [f"{method} {ruri} SIP/2.0"]
    for route in routes:
        uri = route if route.startswith("sip:") else strip_angles(route)
        lines.append(f"Route: <{uri}>")
    lines.extend(
        [
            f"Via: SIP/2.0/UDP {bind_ip}:{port};branch={branch};rport",
            f"From: <{from_uri}>;tag={from_tag}",
            f"To: {to}",
            f"Call-ID: {call_id}",
            f"CSeq: {cseq} {method}",
            f"Contact: <{contact}>",
            "Max-Forwards: 70",
            "User-Agent: MCPTT-Exp5-UAC",
        ]
    )
    if extra:
        lines.extend(extra)
    if body:
        lines.append(f"Content-Type: {content_type or 'application/sdp'}")
    lines.append(f"Content-Length: {len(body)}")
    lines.append("")
    return ("\r\n".join(lines) + "\r\n").encode("utf-8") + body


def recv_matching(sock: socket.socket, call_id: str, timeout: float) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        sock.settimeout(max(0.2, deadline - time.time()))
        try:
            data, src = sock.recvfrom(65535)
        except socket.timeout:
            continue
        msg = data.decode("utf-8", errors="replace")
        if call_id not in msg:
            first = msg.split("\n", 1)[0].strip()
            print(f"ignoring from {src}: {first}")
            continue
        code = status_code(msg)
        print(f"----- RX {src[0]}:{src[1]} {code} -----")
        print(msg)
        if code >= 200:
            return msg
    raise TimeoutError(f"no final response for {call_id} in {timeout}s")


def send(sock: socket.socket, raw: bytes) -> None:
    print("----- TX -----")
    print(raw.decode("utf-8", errors="replace"))
    sock.sendto(raw, PCSCF)


def do_register(
    sock: socket.socket,
    *,
    bind_ip: str,
    port: int,
    imsi: str,
    password: str,
    timeout: float,
) -> None:
    from_uri = f"sip:{imsi}@{REALM}"
    contact = f"sip:{imsi}@{bind_ip}:{port}"
    username = f"{imsi}@{REALM}"
    from_tag = "reg-" + uuid.uuid4().hex[:8]
    call_id = f"reg-{uuid.uuid4().hex[:10]}@{bind_ip}"

    first = sip_request(
        "REGISTER",
        REG_URI,
        bind_ip=bind_ip,
        port=port,
        from_uri=from_uri,
        from_tag=from_tag,
        to_uri=from_uri,
        to_tag="",
        call_id=call_id,
        cseq=1,
        contact=contact,
        routes=[],
        extra=["Expires: 6000"],
    )
    send(sock, first)
    challenge = recv_matching(sock, call_id, timeout)
    if status_code(challenge) != 401:
        raise RuntimeError(f"REGISTER expected 401, got {status_code(challenge)}")

    www = hdr(challenge, "WWW-Authenticate")
    auth = digest_authorization(www, username, password, "REGISTER", REG_URI)
    second = sip_request(
        "REGISTER",
        REG_URI,
        bind_ip=bind_ip,
        port=port,
        from_uri=from_uri,
        from_tag=from_tag,
        to_uri=from_uri,
        to_tag="",
        call_id=call_id,
        cseq=2,
        contact=contact,
        routes=[],
        extra=["Expires: 6000", f"Authorization: {auth}"],
    )
    send(sock, second)
    ok = recv_matching(sock, call_id, timeout)
    if status_code(ok) != 200:
        raise RuntimeError(f"REGISTER failed: {status_code(ok)}")
    print("REGISTER 200 OK")


def run(args: argparse.Namespace) -> int:
    imsi = args.imsi
    bind_ip = args.bind
    port = args.port
    password = args.password or os.environ.get("IMS_DIGEST_SECRET") or ""
    if not password:
        print("pass --password or IMS_DIGEST_SECRET (IMS Digest, not Ki)")
        return 1

    from_uri = f"sip:{imsi}@{REALM}"
    contact = f"sip:{imsi}@{bind_ip}:{port}"
    from_tag = f"exp5-{imsi[-4:]}-{uuid.uuid4().hex[:6]}"
    call_id = f"mcptt-exp5-{imsi[-4:]}-{uuid.uuid4().hex[:8]}@{bind_ip}"
    sdp = (
        f"v=0\r\n"
        f"o=- 5 5 IN IP4 {bind_ip}\r\n"
        f"s=MCPTT\r\n"
        f"c=IN IP4 {bind_ip}\r\n"
        f"t=0 0\r\n"
        f"m=audio 6000 RTP/AVP 0\r\n"
        f"a=rtpmap:0 PCMU/8000\r\n"
        f"a=sendrecv\r\n"
    ).encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((bind_ip, port))
    print(f"bound {bind_ip}:{port}")

    try:
        do_register(
            sock,
            bind_ip=bind_ip,
            port=port,
            imsi=imsi,
            password=password,
            timeout=args.timeout,
        )

        invite = sip_request(
            "INVITE",
            GROUP,
            bind_ip=bind_ip,
            port=port,
            from_uri=from_uri,
            from_tag=from_tag,
            to_uri=GROUP,
            to_tag="",
            call_id=call_id,
            cseq=1,
            contact=contact,
            routes=[ORIG_ROUTE],
            body=sdp,
            extra=[
                # TS 24.379 client originating MCPTT identity (keep m=audio).
                "P-Preferred-Service: urn:urn-7:3gpp-service.ims.icsi.mcptt",
                "Accept-Contact: *;+g.3gpp.mcptt;require;explicit",
                'Accept-Contact: *;+g.3gpp.icsi-ref="urn%3Aurn-7%3A3gpp-service.ims.icsi.mcptt";require;explicit',
            ],
        )
        send(sock, invite)
        ok = recv_matching(sock, call_id, args.timeout)
        code = status_code(ok)
        if code != 200:
            print(f"INVITE failed: {code}")
            return 1

        tag = to_tag(ok)
        as_uri = contact_uri(ok)
        routes = uac_route_set(record_routes(ok))
        print("dialog To-tag=", tag)
        print("dialog R-URI=", as_uri)
        print("dialog Route (P-CSCF first)=", routes)
        rtp_ip, rtp_port, rtcp_port = sdp_c_and_m(ok)
        print(f"answer SDP media {rtp_ip}:{rtp_port} rtcp {rtcp_port}")
        if not tag or not routes:
            print("200 OK missing To-tag or Record-Route")
            return 1
        if args.rtp and (not rtp_ip or not rtp_port):
            print("200 OK missing SDP c=/m= — cannot send RTP")
            return 1

        ack = sip_request(
            "ACK",
            as_uri,
            bind_ip=bind_ip,
            port=port,
            from_uri=from_uri,
            from_tag=from_tag,
            to_uri=GROUP,
            to_tag=tag,
            call_id=call_id,
            cseq=1,
            contact=contact,
            routes=routes,
        )
        send(sock, ack)

        if args.role == "join":
            print(f"holding dialog {args.hold:.0f}s — start UE1 --role floor NOW")
            if args.rtp:
                send_pcmu(bind_ip, args.rtp_local_port, rtp_ip, rtp_port, args.hold)
            else:
                time.sleep(args.hold)
            return 0

        time.sleep(0.5)
        info = sip_request(
            "INFO",
            as_uri,
            bind_ip=bind_ip,
            port=port,
            from_uri=from_uri,
            from_tag=from_tag,
            to_uri=GROUP,
            to_tag=tag,
            call_id=call_id,
            cseq=2,
            contact=contact,
            routes=routes,
            body=b"Action=floor-request\r\n",
            content_type="text/plain",
        )
        send(sock, info)
        info_ok = recv_matching(sock, call_id, args.timeout)
        if status_code(info_ok) != 200:
            print("INFO failed")
            return 1
        print("EXP5 PASS: floor INFO 200 OK")
        if args.mbcp:
            time.sleep(0.4)
            seen = send_mbcp_floor_request(
                bind_ip,
                args.rtp_local_port + 1,
                rtp_ip,
                rtcp_port,
                from_uri,
            )
            if seen == "Floor Granted":
                print("EXP7 PASS: MBCP Floor Granted")
            else:
                print(f"EXP7 MBCP reply={seen or 'none'} — check AS [MBCP] logs")
        if args.rtp:
            time.sleep(1.0)
            n = send_pcmu(bind_ip, args.rtp_local_port, rtp_ip, rtp_port, args.rtp_seconds)
            print(f"EXP6 RTP TX done ({n} packets) — check AS for RTP rx= / RTP fwd")
        else:
            time.sleep(3)
        return 0
    finally:
        sock.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--bind", required=True, help="this UE IMS IP (192.168.101.x)")
    p.add_argument("--imsi", required=True)
    p.add_argument("--password", default="", help="IMS Digest secret (not Ki). Or IMS_DIGEST_SECRET")
    p.add_argument("--port", type=int, default=5062)
    p.add_argument("--role", choices=("join", "floor"), default="floor")
    p.add_argument("--hold", type=float, default=180.0)
    p.add_argument("--timeout", type=float, default=15.0)
    p.add_argument("--rtp", dest="rtp", action="store_true", default=True)
    p.add_argument("--no-rtp", dest="rtp", action="store_false")
    p.add_argument("--rtp-seconds", type=float, default=12.0)
    p.add_argument("--rtp-local-port", type=int, default=6000)
    p.add_argument("--mbcp", dest="mbcp", action="store_true", default=True)
    p.add_argument("--no-mbcp", dest="mbcp", action="store_false")
    raise SystemExit(run(p.parse_args()))


if __name__ == "__main__":
    main()
