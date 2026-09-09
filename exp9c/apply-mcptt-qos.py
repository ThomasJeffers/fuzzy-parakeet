#!/usr/bin/env python3
"""Apply MCPTT AF-Application-Identifier QoS patches (idempotent).

Run on ogs against the real source trees:

  python3 apply-mcptt-qos.py \\
    --open5gs ~/docker_open5gs/base/open5gs \\
    --kamailio ~/docker_open5gs/ims_base/kamailio

Does NOT rebuild Docker images. Does NOT git checkout/reset.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MARKER = "MCPTT_AF_APP_ID_QOS"


def backup(path: Path) -> None:
    bak = path.with_suffix(path.suffix + ".pre-mcptt-af")
    if not bak.exists():
        bak.write_bytes(path.read_bytes())
        print(f"  backup {bak}")


def ensure_qos65(types_h: Path) -> None:
    text = types_h.read_text()
    if "OGS_QOS_INDEX_65" in text:
        print(f"  OK {types_h}: OGS_QOS_INDEX_65 present")
        return
    # Insert after OGS_QOS_INDEX_5 if present, else after INDEX_1
    for anchor in (
        "#define OGS_QOS_INDEX_5   5",
        "#define OGS_QOS_INDEX_5  5",
        "#define OGS_QOS_INDEX_5 5",
        "#define OGS_QOS_INDEX_1   1",
    ):
        if anchor in text:
            backup(types_h)
            text = text.replace(
                anchor,
                anchor + "\n#define OGS_QOS_INDEX_65  65",
                1,
            )
            types_h.write_text(text)
            print(f"  + {types_h}: OGS_QOS_INDEX_65")
            return
    raise SystemExit(f"Cannot find insertion point in {types_h}")


def patch_message_h(path: Path) -> None:
    text = path.read_text()
    if "OGS_DIAM_RX_AVP_CODE_AF_APPLICATION_IDENTIFIER" in text:
        print(f"  OK {path}: AF-App-Id AVP code")
        return
    backup(path)
    # Tolerate Open5GS column-aligned spacing, e.g.
    #   #define OGS_DIAM_RX_AVP_CODE_SPECIFIC_ACTION                (513)
    m = re.search(
        r"^#define\s+OGS_DIAM_RX_AVP_CODE_SPECIFIC_ACTION\s+\(513\)\s*$",
        text,
        re.M,
    )
    if not m:
        raise SystemExit(f"missing SPECIFIC_ACTION define in {path}")
    insert = (
        m.group(0)
        + "\n#define OGS_DIAM_RX_AVP_CODE_AF_APPLICATION_IDENTIFIER (504)"
    )
    text = text[: m.start()] + insert + text[m.end() :]
    # Remove proprietary Media-Type MCPTT 7 if present
    text = re.sub(
        r"\n#define\s+OGS_DIAM_RX_MEDIA_TYPE_MCPTT\s+7\n?",
        "\n",
        text,
    )
    path.write_text(text)
    print(f"  + {path}: AF-App-Id AVP code; stripped MCPTT Media-Type 7 if any")


def _ims_data_struct_span(text: str):
    """Return (start, end, body) of typedef struct ogs_ims_data_s ... } ogs_ims_data_t;"""
    m = re.search(
        r"typedef\s+struct\s+ogs_ims_data_s\s*\{",
        text,
    )
    if not m:
        return None
    # Brace-match from the opening '{' so nested msisdn struct is handled.
    i = m.end() - 1  # points at '{'
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                end_m = re.match(r"\s*ogs_ims_data_t\s*;", text[j + 1 :])
                if not end_m:
                    return None
                end = j + 1 + end_m.end()
                return m.start(), end, text[m.start() : end]
    return None


def repair_duplicate_af_app_id(path: Path) -> None:
    """Keep exactly one af_application_identifier in ogs_ims_data_s."""
    text = path.read_text()
    span = _ims_data_struct_span(text)
    if not span:
        raise SystemExit(f"Cannot find ogs_ims_data_s in {path}")
    start, end, body = span
    field_re = re.compile(r"^[ \t]*char\s*\*\s*af_application_identifier\s*;[ \t]*\n?", re.M)
    n = len(field_re.findall(body))
    if n <= 1:
        print(f"  OK {path}: {n} af_application_identifier field(s)")
        return
    backup(path)
    new_body = field_re.sub("", body)
    new_body = re.sub(
        r"\n[ \t]*/\*[^*]*AF-Application-Identifier[^*]*\*+/[ \t]*",
        "",
        new_body,
    )
    new_body = re.sub(r"\n{3,}", "\n\n", new_body)
    m = re.search(r"int\s+num_of_media_component\s*;", new_body)
    if not m:
        raise SystemExit(f"num_of_media_component missing in {path}")
    field_block = (
        "\n\n    /* TS 29.214 AF-Application-Identifier (AVP 504); owned string */\n"
        "    char *af_application_identifier;\n"
    )
    new_body = new_body[: m.end()] + field_block + new_body[m.end() :]
    path.write_text(text[:start] + new_body + text[end:])
    print(f"  repaired {path}: kept one af_application_identifier")


def patch_ims_data_struct(path: Path) -> None:
    text = path.read_text()
    span = _ims_data_struct_span(text)
    if not span:
        raise SystemExit(f"Cannot find ogs_ims_data_s in {path}")
    start, end, body = span
    field_re = re.compile(r"char\s*\*\s*af_application_identifier\s*;")
    n = len(field_re.findall(body))
    if n > 1:
        repair_duplicate_af_app_id(path)
        return
    if n == 1:
        print(f"  OK {path}: af_application_identifier field")
        return
    backup(path)
    m = re.search(r"int\s+num_of_media_component\s*;", body)
    if not m:
        raise SystemExit(f"Cannot find num_of_media_component in {path}")
    insert = (
        "\n\n    /* TS 29.214 AF-Application-Identifier (AVP 504); owned string */\n"
        "    char *af_application_identifier;\n"
    )
    new_body = body[: m.end()] + insert + body[m.end() :]
    path.write_text(text[:start] + new_body + text[end:])
    print(f"  + {path}: af_application_identifier on ogs_ims_data_t")


def patch_ims_data_free(path: Path) -> None:
    text = path.read_text()
    n = text.count("ims_data->af_application_identifier")
    if n >= 2:
        # already has free block (typically 3 refs: if / free / NULL)
        print(f"  OK {path}: free af_application_identifier")
        return
    backup(path)
    m = re.search(
        r"void\s+ogs_ims_data_free\s*\(\s*ogs_ims_data_t\s*\*\s*ims_data\s*\)\s*\{"
        r"\s*int\s+i\s*,\s*j\s*,\s*k\s*;\s*"
        r"ogs_assert\s*\(\s*ims_data\s*\)\s*;",
        text,
        re.S,
    )
    if not m:
        raise SystemExit(f"Cannot find ogs_ims_data_free prologue in {path}")
    add = (
        m.group(0)
        + "\n\n    if (ims_data->af_application_identifier) {\n"
        + "        ogs_free(ims_data->af_application_identifier);\n"
        + "        ims_data->af_application_identifier = NULL;\n"
        + "    }"
    )
    path.write_text(text[: m.start()] + add + text[m.end() :])
    print(f"  + {path}: free af_application_identifier")


RX_PARSE_SNIPPET = r'''
            case OGS_DIAM_RX_AVP_CODE_AF_APPLICATION_IDENTIFIER:
                /* TS 29.214 §5.3.5 — standalone case; do NOT place inside the
                 * Origin-Realm…Specific-Action fall-through ignore list. */
                if (rx_message.ims_data.af_application_identifier) {
                    ogs_free(rx_message.ims_data.af_application_identifier);
                    rx_message.ims_data.af_application_identifier = NULL;
                }
                if (!hdr->avp_value || !hdr->avp_value->os.data ||
                        !hdr->avp_value->os.len) {
                    ogs_warn("AF-Application-Identifier missing/empty");
                    break;
                }
                rx_message.ims_data.af_application_identifier = ogs_strndup(
                        (char *)hdr->avp_value->os.data,
                        hdr->avp_value->os.len);
                if (!rx_message.ims_data.af_application_identifier) {
                    ogs_error("Failed to duplicate AF-Application-Identifier");
                    error_occurred = 1;
                    goto out;
                }
                ogs_info("Rx AF-Application-Identifier: %s",
                        rx_message.ims_data.af_application_identifier);
                break;
'''


def patch_rx_path(path: Path) -> None:
    text = path.read_text()
    if "OGS_DIAM_RX_AVP_CODE_AF_APPLICATION_IDENTIFIER" in text:
        # Detect the fall-through bug: AF-App-Id case glued to Framed-IPv6 /
        # Origin-Realm group (realms/hosts logged as AF-App-Id).
        if re.search(
            r"case\s+OGS_DIAM_AVP_CODE_FRAME_IPV6_PREFIX\s*:\s*"
            r"case\s+OGS_DIAM_RX_AVP_CODE_AF_APPLICATION_IDENTIFIER\s*:",
            text,
            re.S,
        ) or re.search(
            r"case\s+AC_AUTH_APPLICATION_ID\s*:\s*"
            r"(?:case[^\n]+:\s*)*"
            r"case\s+OGS_DIAM_RX_AVP_CODE_AF_APPLICATION_IDENTIFIER\s*:",
            text,
            re.S,
        ):
            raise SystemExit(
                f"{path}: AF-App-Id case is inside an ignore fall-through group "
                "(realms/hosts overwrite AF-App-Id). Restore pcrf-rx-path.c from "
                "git/backup, copy updated apply-mcptt-qos.py, re-apply, rebuild."
            )
        print(f"  OK {path}: parses AF-App-Id")
        return
    backup(path)
    # MUST be a standalone case BEFORE the Origin-Realm…Specific-Action
    # fall-through ignore list — never insert in the middle of that list.
    m = re.search(
        r"case\s+AC_ORIGIN_REALM\s*:\s*"
        r"case\s+AC_DESTINATION_REALM\s*:",
        text,
        re.S,
    )
    if not m:
        raise SystemExit(
            f"Cannot find AC_ORIGIN_REALM ignore group start in {path}"
        )
    text = (
        text[: m.start()]
        + RX_PARSE_SNIPPET.rstrip()
        + "\n"
        + m.group(0)
        + text[m.end() :]
    )
    path.write_text(text)
    print(f"  + {path}: parse AF-Application-Identifier (standalone case)")


GX_HELPER = r'''
/* ''' + MARKER + r''' */
static int pcrf_af_application_is_mcptt(const char *af_id)
{
    if (!af_id || !af_id[0])
        return 0;
    /* ICSI from TS 24.379 / TS 24.229 */
    if (strstr(af_id, "3gpp-service.ims.icsi.mcptt"))
        return 1;
    /* Feature-tag forms sometimes copied into AF-App-Id */
    if (strstr(af_id, "+g.3gpp.mcptt"))
        return 1;
    if (!strcasecmp(af_id, "MCPTT"))
        return 1;
    return 0;
}
'''

AUDIO_CASE_BODY = """
            case OGS_DIAM_RX_MEDIA_TYPE_AUDIO:
                /*
                 * Media-Type remains AUDIO for MCPTT RTP.
                 * TS 29.214 §5.3.5: use AF-Application-Identifier with
                 * Media-Type to differentiate application QoS.
                 * MCPTT → QCI 65 PCC; ordinary IMS audio → QCI 1.
                 */
                if (pcrf_af_application_is_mcptt(
                        rx_message->ims_data.af_application_identifier)) {
                    qos_index = OGS_QOS_INDEX_65;
                } else {
                    qos_index = OGS_QOS_INDEX_1;
                }
                ogs_info("Rx media policy: media_type=AUDIO af_app_id=%s "
                        "selected_qos_index=%d",
                        rx_message->ims_data.af_application_identifier
                            ? rx_message->ims_data.af_application_identifier
                            : "(none)",
                        qos_index);
                break;
"""

AUDIO_CASE_RE = re.compile(
    r"case\s+OGS_DIAM_RX_MEDIA_TYPE_AUDIO\s*:\s*"
    r"qos_index\s*=\s*(?:OGS_QOS_INDEX_1|OGS_QOS_INDEX_65|65)\s*;\s*"
    r"break\s*;",
    re.S,
)


def patch_gx_path(path: Path) -> None:
    text = path.read_text()
    if MARKER in text and "pcrf_af_application_is_mcptt" in text:
        if "selected_qos_index" in text:
            print(f"  OK {path}: MCPTT AF-App-Id policy present")
            return
    backup(path)
    if MARKER not in text:
        m = re.search(r"\nint pcrf_gx_send_rar\s*\(", text)
        if not m:
            raise SystemExit(f"Cannot find pcrf_gx_send_rar in {path}")
        text = text[: m.start()] + "\n" + GX_HELPER + text[m.start() :]

    if not AUDIO_CASE_RE.search(text):
        raise SystemExit(
            f"Cannot match AUDIO qos_index case in {path}; "
            "edit manually using MCPTT-QOS-DESIGN.md"
        )
    text = AUDIO_CASE_RE.sub(AUDIO_CASE_BODY.strip() + "\n", text, count=1)

    text = re.sub(
        r"\s*case\s+OGS_DIAM_RX_MEDIA_TYPE_MCPTT\s*:\s*"
        r"qos_index\s*=\s*(?:OGS_QOS_INDEX_65|65)\s*;\s*break\s*;",
        "",
        text,
    )
    path.write_text(text)
    print(f"  + {path}: AUDIO+MCPTT→65 / AUDIO→1 policy")


KAMAILIO_HELPER = r'''
/* ''' + MARKER + r'''
 * Detect MCPTT from SIP ICSI / feature tags (TS 24.379).
 * Media stays m=audio → Media-Type AUDIO; service identity goes in
 * AF-Application-Identifier (TS 29.214 §5.3.5).
 */
static str MCPTT_Serv_AVP_val = {
        "urn:urn-7:3gpp-service.ims.icsi.mcptt", 35};

static int rx_buf_contains(
        const char *hay, int hlen, const char *needle, int nlen)
{
        int i;

        if(!hay || !needle || nlen <= 0 || hlen < nlen)
                return 0;
        for(i = 0; i <= hlen - nlen; i++) {
                if(memcmp(hay + i, needle, nlen) == 0)
                        return 1;
        }
        return 0;
}

static int rx_sip_indicates_mcptt(struct sip_msg *msg)
{
        const char *body;
        int hdr_len;
        int i;

        if(!msg || !msg->buf || msg->len < 8)
                return 0;

        body = NULL;
        for(i = 0; i + 3 < msg->len; i++) {
                if(msg->buf[i] == '\r' && msg->buf[i + 1] == '\n'
                                && msg->buf[i + 2] == '\r'
                                && msg->buf[i + 3] == '\n') {
                        body = msg->buf + i;
                        break;
                }
        }
        hdr_len = body ? (int)(body - msg->buf) : msg->len;
        if(hdr_len <= 0)
                return 0;

        if(rx_buf_contains(msg->buf, hdr_len, "icsi.mcptt", 10))
                return 1;
        if(rx_buf_contains(msg->buf, hdr_len, "+g.3gpp.mcptt", 13))
                return 1;
        return 0;
}

static str rx_select_af_application_id_from_dialog(
        struct sip_msg *req, struct sip_msg *res)
{
        if(rx_sip_indicates_mcptt(req) || rx_sip_indicates_mcptt(res)) {
                LM_INFO("Rx AF-Application-Identifier=MCPTT ICSI "
                                "(SIP MCPTT feature/ICSI detected)\n");
                return MCPTT_Serv_AVP_val;
        }
        LM_INFO("Rx AF-Application-Identifier=IMS Services "
                        "(no MCPTT SIP ICSI/feature tag on INVITE/200)\n");
        return IMS_Serv_AVP_val;
}
'''


def patch_kamailio_rx_aar(path: Path) -> None:
    text = path.read_text()
    changed = False

    if MARKER not in text:
        backup(path)
        anchor = 'str IMS_Serv_AVP_val = {"IMS Services", 12};'
        if anchor not in text:
            raise SystemExit(f"Cannot find IMS_Serv_AVP_val in {path}")
        text = text.replace(anchor, anchor + "\n" + KAMAILIO_HELPER, 1)
        changed = True
    elif "rx_select_af_application_id_from_dialog" not in text:
        # Older helper (req-only) — replace whole marked helper with dialog version
        backup(path)
        m = re.search(
            r"/\* " + re.escape(MARKER) + r".*?"
            r"static str rx_select_af_application_id\s*\([^)]*\)\s*\{.*?\n\}\n",
            text,
            re.S,
        )
        if m:
            text = text[: m.start()] + KAMAILIO_HELPER + text[m.end() :]
            changed = True
        else:
            # Append dialog selector after old req-only selector
            old = (
                "static str rx_select_af_application_id(struct sip_msg *req)\n"
                "{\n"
                "        if(req && rx_sip_indicates_mcptt(req)) {\n"
                "                LM_INFO(\"Rx AF-Application-Identifier=MCPTT ICSI \"\n"
                "                                \"(SIP MCPTT feature/ICSI detected)\\n\");\n"
                "                return MCPTT_Serv_AVP_val;\n"
                "        }\n"
                "        return IMS_Serv_AVP_val;\n"
                "}\n"
            )
            add = (
                "\nstatic str rx_select_af_application_id_from_dialog(\n"
                "        struct sip_msg *req, struct sip_msg *res)\n"
                "{\n"
                "        if(rx_sip_indicates_mcptt(req) || rx_sip_indicates_mcptt(res)) {\n"
                "                LM_INFO(\"Rx AF-Application-Identifier=MCPTT ICSI \"\n"
                "                                \"(SIP MCPTT feature/ICSI detected)\\n\");\n"
                "                return MCPTT_Serv_AVP_val;\n"
                "        }\n"
                "        LM_INFO(\"Rx AF-Application-Identifier=IMS Services \"\n"
                "                        \"(no MCPTT SIP ICSI/feature tag on INVITE/200)\\n\");\n"
                "        return IMS_Serv_AVP_val;\n"
                "}\n"
            )
            if old not in text:
                raise SystemExit(
                    f"{path}: MCPTT marker present but helpers unexpected; "
                    "inspect rx_aar.c manually"
                )
            text = text.replace(old, old + add, 1)
            changed = True

    idx = text.find("int rx_send_aar(struct sip_msg *req,")
    if idx < 0:
        raise SystemExit(f"Cannot find rx_send_aar in {path}")
    idx2 = text.find("int rx_send_aar_register(", idx + 1)
    if idx2 < 0:
        idx2 = len(text)
    chunk = text[idx:idx2]

    wired = "rx_select_af_application_id_from_dialog(req, res)" in chunk
    if not wired:
        if not changed:
            backup(path)
        # Replace any stock or req-only assignment
        chunk2, n = re.subn(
            r"af_id\s*=\s*(?:IMS_Serv_AVP_val|rx_select_af_application_id\s*\(\s*req\s*\))\s*;",
            "af_id = rx_select_af_application_id_from_dialog(req, res);",
            chunk,
            count=1,
        )
        if n != 1:
            raise SystemExit(
                "Cannot wire af_id in rx_send_aar. On ogs run:\n"
                "  grep -n 'af_id' "
                "~/docker_open5gs/ims_base/kamailio/src/modules/ims_qos/rx_aar.c"
            )
        text = text[:idx] + chunk2 + text[idx2:]
        changed = True

    if changed:
        path.write_text(text)
        print(f"  + {path}: MCPTT AF-App-Id wired in rx_send_aar")
    else:
        print(f"  OK {path}: MCPTT AF-App-Id selection wired in rx_send_aar")


def patch_kamailio_rx_avp(path: Path) -> None:
    """Revert proprietary mcptt media-type branch if present."""
    if not path.exists():
        print(f"  skip missing {path}")
        return
    text = path.read_text()
    if "AVP_IMS_Media_Type_Mcptt" not in text and 'strncmp(media_description->s, "mcptt"' not in text:
        print(f"  OK {path}: no proprietary mcptt Media-Type")
        return
    backup(path)
    text = re.sub(
        r'\s*\} else if\(strncmp\(media_description->s, "mcptt", 5\) == 0\) \{\s*'
        r"type = AVP_IMS_Media_Type_Mcptt;\s*",
        "\n",
        text,
    )
    text = re.sub(
        r"\s*#define\s+AVP_IMS_Media_Type_Mcptt\s+\d+\s*",
        "\n",
        text,
    )
    path.write_text(text)
    print(f"  + {path}: removed proprietary m=mcptt Media-Type mapping")


def find_ims_data_header(open5gs: Path) -> Path:
    candidates = list(open5gs.glob("**/ogs-proto.h")) + list(
        open5gs.glob("**/ogs-proto-message.h")
    )
    for c in candidates:
        if "ogs_ims_data_s" in c.read_text(errors="ignore"):
            return c
    # also search broadly
    for c in open5gs.glob("lib/**/*.h"):
        try:
            t = c.read_text(errors="ignore")
        except OSError:
            continue
        if "typedef struct ogs_ims_data_s" in t:
            return c
    raise SystemExit("Cannot locate ogs_ims_data_s header under Open5GS tree")


def find_ims_data_c(open5gs: Path) -> Path:
    for name in ("ogs-proto-message.c", "ogs-tlv-message.c", "message.c"):
        hits = list(open5gs.glob(f"**/{name}"))
        for h in hits:
            if "ogs_ims_data_free" in h.read_text(errors="ignore"):
                return h
    for c in open5gs.glob("lib/**/*.c"):
        try:
            if "ogs_ims_data_free" in c.read_text(errors="ignore"):
                return c
        except OSError:
            continue
    raise SystemExit("Cannot locate ogs_ims_data_free")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--open5gs", type=Path, required=True)
    ap.add_argument("--kamailio", type=Path, required=True)
    args = ap.parse_args()

    o5 = args.open5gs.resolve()
    ka = args.kamailio.resolve()
    if not o5.is_dir() or not ka.is_dir():
        print("open5gs/kamailio paths must be directories", file=sys.stderr)
        return 1

    print("=== Open5GS ===")
    types = o5 / "lib/proto/types.h"
    if not types.exists():
        # alternate layouts
        hits = list(o5.glob("**/types.h"))
        types = next((h for h in hits if "QOS_INDEX_1" in h.read_text(errors="ignore")), None)
        if not types:
            raise SystemExit("types.h with OGS_QOS_INDEX not found")
    ensure_qos65(types)

    msg_h = o5 / "lib/diameter/rx/message.h"
    if not msg_h.exists():
        raise SystemExit(f"missing {msg_h}")
    patch_message_h(msg_h)

    ims_h = find_ims_data_header(o5)
    patch_ims_data_struct(ims_h)
    ims_c = find_ims_data_c(o5)
    patch_ims_data_free(ims_c)

    rx = o5 / "src/pcrf/pcrf-rx-path.c"
    gx = o5 / "src/pcrf/pcrf-gx-path.c"
    patch_rx_path(rx)
    patch_gx_path(gx)

    print("=== Kamailio ===")
    rx_aar = ka / "src/modules/ims_qos/rx_aar.c"
    rx_avp = ka / "src/modules/ims_qos/rx_avp.c"
    if not rx_aar.exists():
        raise SystemExit(f"missing {rx_aar}")
    patch_kamailio_rx_aar(rx_aar)
    patch_kamailio_rx_avp(rx_avp)

    print("\nDone. Next: rebuild open5gs base image + pcscf (offline), recreate pcrf+pcscf.")
    print("See ims/MCPTT-QOS-DESIGN.md for verification.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
