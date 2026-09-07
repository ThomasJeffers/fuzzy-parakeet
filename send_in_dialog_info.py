#!/usr/bin/env python3
"""Send one in-dialog SIP INFO (floor-request) to P-CSCF.

Copy To-tag / Record-Route / Call-ID from THIS UE's INVITE 200 OK.
Run inside the UE netns so the packet sources from the IMS PDN IP.
"""

from __future__ import annotations

import argparse
import socket
import uuid


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--bind", required=True, help="UE IMS IP")
    p.add_argument("--port", type=int, default=5062)
    p.add_argument("--pcscf", default="172.22.0.21")
    p.add_argument("--pcscf-port", type=int, default=5060)
    p.add_argument("--from-uri", required=True)
    p.add_argument("--from-tag", required=True)
    p.add_argument("--to-uri", required=True)
    p.add_argument("--to-tag", required=True)
    p.add_argument("--call-id", required=True)
    p.add_argument("--contact", required=True)
    p.add_argument("--as", dest="as_uri", required=True)
    p.add_argument(
        "--route",
        action="append",
        default=[],
        help="Repeat in the same order as Record-Route in the 200 OK "
        "(this script reverses them; first hop becomes P-CSCF)",
    )
    p.add_argument(
        "--no-reverse",
        action="store_true",
        help="Leave --route order unchanged (wrong for INFO; ACK-style)",
    )
    p.add_argument("--cseq", type=int, default=2)
    p.add_argument("--timeout", type=float, default=15.0)
    args = p.parse_args()

    routes = list(args.route)
    if not args.no_reverse:
        routes = list(reversed(routes))
        print("Route set (reversed, P-CSCF first):", routes)

    body = b"Action=floor-request\r\n"
    branch = "z9hG4bK-floor-" + uuid.uuid4().hex[:10]
    hdr = [
        f"INFO {args.as_uri} SIP/2.0",
    ]
    for route in routes:
        hdr.append(f"Route: <{route}>")
    hdr.extend(
        [
            f"Via: SIP/2.0/UDP {args.bind}:{args.port};branch={branch};rport",
            f"From: <{args.from_uri}>;tag={args.from_tag}",
            f"To: <{args.to_uri}>;tag={args.to_tag}",
            f"Call-ID: {args.call_id}",
            f"CSeq: {args.cseq} INFO",
            f"Contact: <{args.contact}>",
            "Max-Forwards: 70",
            "User-Agent: MCPTT-Lab-UE",
            "Content-Type: text/plain",
            f"Content-Length: {len(body)}",
            "",
        ]
    )
    msg = "\r\n".join(hdr).encode("utf-8") + body

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind, args.port))
    sock.settimeout(args.timeout)
    sock.sendto(msg, (args.pcscf, args.pcscf_port))
    print("----- TX -----")
    print(msg.decode())
    try:
        data, src = sock.recvfrom(65535)
        print(f"----- RX {src[0]}:{src[1]} -----")
        print(data.decode("utf-8", errors="replace"))
    except socket.timeout:
        print(f"No reply in {args.timeout:.0f}s")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
