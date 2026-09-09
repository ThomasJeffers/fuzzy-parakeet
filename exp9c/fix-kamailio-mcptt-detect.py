#!/usr/bin/env python3
"""Force-refresh MCPTT AF-App-Id detection in Kamailio ims_qos/rx_aar.c.

Your grep already showed rx_send_aar WAS calling the selector. The failure was
detection returning false (or the running pcscf image not built from this tree).

This script replaces the MCPTT helper with a stronger detector that also
matches lab markers: sip:group1@, MCPTT-Exp5-UAC, ICSI, +g.3gpp.mcptt.

  python3 fix-kamailio-mcptt-detect.py \\
    ~/docker_open5gs/ims_base/kamailio/src/modules/ims_qos/rx_aar.c

Then rebuild/recreate ONLY pcscf and confirm the binary contains the marker:
  docker exec pcscf grep -n 'sip:group1@' /usr/local/src/kamailio/src/modules/ims_qos/rx_aar.c
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MARKER = "MCPTT_AF_APP_ID_QOS"

HELPER = r'''
/* ''' + MARKER + r'''
 * Detect MCPTT from SIP ICSI / feature tags (TS 24.379) + lab markers.
 * Media stays m=audio → Media-Type AUDIO; service identity goes in
 * AF-Application-Identifier (TS 29.214 §5.3.5).
 */
static str MCPTT_Serv_AVP_val = {
        "urn:urn-7:3gpp-service.ims.icsi.mcptt", 35};

static int rx_buf_contains_ci(
        const char *hay, int hlen, const char *needle, int nlen)
{
        int i, j;

        if(!hay || !needle || nlen <= 0 || hlen < nlen)
                return 0;
        for(i = 0; i <= hlen - nlen; i++) {
                for(j = 0; j < nlen; j++) {
                        char a = hay[i + j];
                        char b = needle[j];
                        if(a >= 'A' && a <= 'Z')
                                a = (char)(a - 'A' + 'a');
                        if(b >= 'A' && b <= 'Z')
                                b = (char)(b - 'A' + 'a');
                        if(a != b)
                                break;
                }
                if(j == nlen)
                        return 1;
        }
        return 0;
}

static int rx_sip_indicates_mcptt(struct sip_msg *msg)
{
        int len;

        if(!msg || !msg->buf || msg->len < 8)
                return 0;

        len = msg->len;

        if(rx_buf_contains_ci(msg->buf, len, "icsi.mcptt", 10))
                return 1;
        if(rx_buf_contains_ci(msg->buf, len, "+g.3gpp.mcptt", 13))
                return 1;
        if(rx_buf_contains_ci(msg->buf, len, "3gpp-service.ims.icsi.mcptt", 26))
                return 1;
        /* Lab UAC */
        if(rx_buf_contains_ci(msg->buf, len, "mcptt-exp5-uac", 14))
                return 1;
        /* Lab group INVITE R-URI / To */
        if(rx_buf_contains_ci(msg->buf, len, "sip:group1@", 11))
                return 1;

        return 0;
}

static str rx_select_af_application_id_from_dialog(
        struct sip_msg *req, struct sip_msg *res)
{
        if(rx_sip_indicates_mcptt(req) || rx_sip_indicates_mcptt(res)) {
                LM_INFO("Rx AF-Application-Identifier=MCPTT ICSI "
                                "(SIP MCPTT marker detected)\n");
                return MCPTT_Serv_AVP_val;
        }
        LM_WARN("Rx AF-Application-Identifier=IMS Services "
                        "(no MCPTT marker; req_len=%d res_len=%d)\n",
                        req ? req->len : -1, res ? res->len : -1);
        return IMS_Serv_AVP_val;
}
'''


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    text = path.read_text()
    bak = path.with_suffix(path.suffix + ".pre-detect-fix")
    if not bak.exists():
        bak.write_text(text)
        print(f"backup {bak}")

    # Remove any prior MCPTT helper block(s)
    text2 = re.sub(
        r"/\* " + re.escape(MARKER) + r".*?return IMS_Serv_AVP_val;\n\}\n",
        "",
        text,
        count=1,
        flags=re.S,
    )
    if text2 == text and MARKER in text:
        # try broader removal
        text2 = re.sub(
            r"/\* " + re.escape(MARKER) + r".*?\nstatic str rx_select_af_application_id[^\n]*\n\{.*?\n\}\n",
            "",
            text,
            count=1,
            flags=re.S,
        )

    anchor = 'str IMS_Serv_AVP_val = {"IMS Services", 12};'
    if anchor not in text2:
        print("IMS_Serv_AVP_val not found", file=sys.stderr)
        return 1
    # Insert helper once after IMS_Serv_AVP_val
    if MARKER not in text2:
        text2 = text2.replace(anchor, anchor + "\n" + HELPER, 1)
    else:
        # marker still there — replace from marker to end of from_dialog fn
        text2 = re.sub(
            r"/\* " + re.escape(MARKER) + r".*?return IMS_Serv_AVP_val;\n\}\n",
            HELPER,
            text2,
            count=1,
            flags=re.S,
        )
        if MARKER not in text2:
            text2 = text2.replace(anchor, anchor + "\n" + HELPER, 1)

    # Wire rx_send_aar(req,res) af_id
    def wire_send_aar(s: str) -> str:
        idx = s.find("int rx_send_aar(struct sip_msg *req,")
        if idx < 0:
            raise SystemExit("rx_send_aar not found")
        idx2 = s.find("int rx_send_aar_register(", idx + 1)
        if idx2 < 0:
            idx2 = len(s)
        chunk = s[idx:idx2]
        chunk2, n = re.subn(
            r"af_id\s*=\s*[^;]+;",
            "af_id = rx_select_af_application_id_from_dialog(req, res);",
            chunk,
            count=1,
        )
        if n != 1:
            raise SystemExit("could not wire af_id in rx_send_aar")
        return s[:idx] + chunk2 + s[idx2:]

    text2 = wire_send_aar(text2)
    path.write_text(text2)
    print(f"updated {path}")
    print("Next:")
    print("  1) Rebuild pcscf image FROM this ims_base/kamailio tree (not a fresh git clone)")
    print("  2) docker compose ... up -d --force-recreate --no-deps pcscf")
    print("  3) docker exec pcscf grep -n 'sip:group1@' /usr/local/src/kamailio/src/modules/ims_qos/rx_aar.c")
    print("  4) Retest; docker logs pcscf 2>&1 | grep -E 'MCPTT ICSI|no MCPTT marker'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
