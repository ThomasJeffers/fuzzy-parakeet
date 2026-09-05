#!/usr/bin/env python3
"""Experiment 4 regression: 200 OK must copy the full Via stack.

Kamailio S-CSCF matches the AS-side INVITE transaction on the *top* Via
branch. The old parser stored duplicate headers as a list and get_header()
returned the last value (the UE Via). The 200 OK then had only the UE Via,
tm never matched, INVITEs retransmitted (T1=500ms), and S-CSCF emitted 408.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SERVER_PATH = Path(__file__).resolve().parents[1] / "mcptt-server.py"


def load_server():
    spec = importlib.util.spec_from_file_location("mcptt_server", SERVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    import sys

    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


INVITE = (
    "INVITE sip:group1@ims.mnc070.mcc901.3gppnetwork.org SIP/2.0\r\n"
    "Via: SIP/2.0/UDP 172.22.0.20:6060;branch=z9hG4bK-scscf-aaa;rport\r\n"
    "Via: SIP/2.0/UDP 172.22.0.21:5060;branch=z9hG4bK-pcscf-bbb\r\n"
    "Via: SIP/2.0/UDP 192.168.101.4:42805;branch=z9hG4bK-ue-ccc;rport\r\n"
    "Record-Route: <sip:orig@scscf.ims.mnc070.mcc901.3gppnetwork.org:6060;lr>\r\n"
    "Record-Route: <sip:term@pcscf.ims.mnc070.mcc901.3gppnetwork.org;lr>\r\n"
    "From: <sip:491234567890123@ims.mnc070.mcc901.3gppnetwork.org>;tag=ue1\r\n"
    "To: <sip:group1@ims.mnc070.mcc901.3gppnetwork.org>\r\n"
    "Call-ID: mcptt-invite-exp4@192.168.101.4\r\n"
    "CSeq: 1 INVITE\r\n"
    "Contact: <sip:491234567890123@192.168.101.4:42805>\r\n"
    "Content-Type: application/sdp\r\n"
    "Content-Length: 0\r\n"
    "\r\n"
)


class ViaCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_server()

    def test_parse_keeps_via_order_top_first(self):
        msg = self.mod.parse_sip_message(INVITE.encode())
        vias = self.mod.get_headers(msg["headers"], "Via")
        self.assertEqual(len(vias), 3)
        self.assertIn("172.22.0.20:6060", vias[0])
        self.assertIn("z9hG4bK-scscf-aaa", vias[0])
        self.assertIn("192.168.101.4:42805", vias[2])
        self.assertEqual(self.mod.get_header(msg["headers"], "Via"), vias[0])

    def test_200_ok_copies_all_vias_and_record_routes(self):
        msg = self.mod.parse_sip_message(INVITE.encode())
        headers = self.mod.copy_request_headers_for_response(
            msg["headers"],
            {
                "To": msg["headers"]["To"][0] + ";tag=as-tag",
                "Contact": "<sip:172.30.104.240:5070;transport=udp>",
            },
        )
        raw = self.mod.render_sip_response(200, "OK", headers).decode()
        via_lines = [ln for ln in raw.split("\r\n") if ln.lower().startswith("via:")]
        rr_lines = [ln for ln in raw.split("\r\n") if ln.lower().startswith("record-route:")]
        self.assertEqual(len(via_lines), 3, raw)
        self.assertIn("z9hG4bK-scscf-aaa", via_lines[0])
        self.assertIn("z9hG4bK-pcscf-bbb", via_lines[1])
        self.assertIn("z9hG4bK-ue-ccc", via_lines[2])
        self.assertEqual(len(rr_lines), 2, raw)
        self.assertTrue(raw.startswith("SIP/2.0 200 OK"))
        # The bug: a 200 whose first/only Via is the UE cannot match tm.
        self.assertNotIn(via_lines[0].lower(), ["via: sip/2.0/udp 192.168.101.4:42805"])
        self.assertIn("172.22.0.20:6060", via_lines[0])

    def test_old_last_via_behavior_would_fail_kamailio(self):
        msg = self.mod.parse_sip_message(INVITE.encode())
        vias = self.mod.get_headers(msg["headers"], "Via")
        last_only = vias[-1]
        self.assertIn("192.168.101.4:42805", last_only)
        self.assertNotEqual(self.mod.get_header(msg["headers"], "Via"), last_only)


if __name__ == "__main__":
    unittest.main()
