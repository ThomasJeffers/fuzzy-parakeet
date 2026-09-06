#!/usr/bin/env python3
"""ZMQ I/Q broker: one srsENB <-> two srsUE (srsRAN 4G).

srsRAN ZMQ is point-to-point (TX=REP bind, RX=REQ connect). You cannot put a
second UE on the same port pair, and extra tx_port1 on the eNB is MIMO, not a
second UE. This process copies downlink to both UEs and adds their uplinks.

Ports (must match enb.conf / ue-ims.conf / ue2-ims.conf):

              TX (REP bind)         RX (REQ connect)
  eNB         tcp://*:2000          tcp://localhost:2001
  UE1         tcp://*:2101          tcp://localhost:2100
  UE2         tcp://*:2201          tcp://localhost:2200

Install:  sudo apt-get install -y gnuradio
Run last: python3 zmq_two_ue_broker.py --srate 23.04e6

Start order: Open5GS -> srsENB -> srsUE1 -> srsUE2 -> this broker.
Restart this broker whenever you restart eNB/UEs.
"""

from __future__ import annotations

import argparse
import sys


def build_flowgraph(samp_rate: float, timeout_ms: int):
    try:
        from gnuradio import blocks, gr, zeromq
    except ImportError:
        print(
            "GNU Radio Python bindings not found.\n"
            "On Ubuntu: sudo apt-get install -y gnuradio\n"
            "Then: python3 zmq_two_ue_broker.py --srate 23.04e6",
            file=sys.stderr,
        )
        sys.exit(1)

    class TwoUeBroker(gr.top_block):
        def __init__(self):
            gr.top_block.__init__(self, "srsRAN 2-UE ZMQ broker")
            item = gr.sizeof_gr_complex

            # Pull TX from each radio (they bind REP).
            self.enb_dl = zeromq.req_source(
                item, 1, "tcp://127.0.0.1:2000", timeout_ms, False, -1
            )
            self.ue1_ul = zeromq.req_source(
                item, 1, "tcp://127.0.0.1:2101", timeout_ms, False, -1
            )
            self.ue2_ul = zeromq.req_source(
                item, 1, "tcp://127.0.0.1:2201", timeout_ms, False, -1
            )

            # Serve RX of each radio (they connect REQ).
            self.ue1_dl = zeromq.rep_sink(
                item, 1, "tcp://127.0.0.1:2100", timeout_ms, False, -1
            )
            self.ue2_dl = zeromq.rep_sink(
                item, 1, "tcp://127.0.0.1:2200", timeout_ms, False, -1
            )
            self.enb_ul = zeromq.rep_sink(
                item, 1, "tcp://127.0.0.1:2001", timeout_ms, False, -1
            )

            try:
                self.ul_add = blocks.add_cc()
            except AttributeError:
                self.ul_add = blocks.add_vcc(1)

            # Keep GR from spinning a core; 1.0 = realtime vs srsRAN base_srate.
            self.throttle = blocks.throttle(item, samp_rate, True)

            # DL: one eNB TX -> both UEs
            self.connect((self.enb_dl, 0), (self.ue1_dl, 0))
            self.connect((self.enb_dl, 0), (self.ue2_dl, 0))

            # UL: UE1 + UE2 -> eNB RX
            self.connect((self.ue1_ul, 0), (self.ul_add, 0))
            self.connect((self.ue2_ul, 0), (self.ul_add, 1))
            self.connect((self.ul_add, 0), (self.throttle, 0))
            self.connect((self.throttle, 0), (self.enb_ul, 0))

    return TwoUeBroker()


def main() -> None:
    parser = argparse.ArgumentParser(description="srsRAN 4G two-UE ZMQ I/Q broker")
    parser.add_argument(
        "--srate",
        type=float,
        default=23.04e6,
        help="Must equal base_srate in enb.conf and both UE confs (Hz)",
    )
    parser.add_argument("--timeout-ms", type=int, default=100)
    args = parser.parse_args()

    print("Two-UE ZMQ broker")
    print("  DL  eNB:2000  ->  UE1:2100 and UE2:2200")
    print("  UL  UE1:2101 + UE2:2201  ->  eNB:2001")
    print(f"  samp_rate={args.srate:.0f}  (must match base_srate)")
    print("Both srsUE processes must already be running.")
    tb = build_flowgraph(args.srate, args.timeout_ms)
    tb.start()
    print("Running. Ctrl-C to stop. Restart after every eNB/UE restart.")
    try:
        tb.wait()
    except KeyboardInterrupt:
        pass
    tb.stop()
    tb.wait()


if __name__ == "__main__":
    main()
