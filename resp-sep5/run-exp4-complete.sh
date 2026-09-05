#!/usr/bin/env bash
# Run on RAN VM (Demo / 172.30.104.230) inside a shell that can sudo.
# Completes Experiment 4: REGISTER + INVITE + ACK + BYE through P-CSCF.
#
#   export IMS_DIGEST_SECRET='...'   # PyHSS/IMS digest, not Ki. Do not commit.
#   sudo -E ./sipp/run-exp4-complete.sh
set -euo pipefail

PCSCF="${PCSCF:-172.22.0.21}"
IMPU_USER="${IMPU_USER:-491234567890123}"
LOCAL_PORT="${LOCAL_PORT:-5062}"
NS="${NS:-ue1}"
DEV="${DEV:-tun_srsue}"
GW="${GW:-192.168.101.1}"
IMS_NET="${IMS_NET:-172.22.0.0/24}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCENARIO="${SCENARIO:-$SCRIPT_DIR/register-then-invite.xml}"

if [[ -z "${IMS_DIGEST_SECRET:-}" ]]; then
  echo "Set IMS_DIGEST_SECRET to the IMS Digest password (not Ki/OPc)." >&2
  exit 1
fi

if ! command -v sipp >/dev/null 2>&1; then
  echo "Install SIPp first: sudo apt install sip-tester   # or build https://github.com/sipp/sipp" >&2
  exit 1
fi

UE_IP="$(ip netns exec "$NS" ip -4 -o addr show "$DEV" | awk '{print $4}' | cut -d/ -f1)"
if [[ -z "$UE_IP" || "$UE_IP" != 192.168.101.* ]]; then
  echo "tun_srsue is not on the IMS pool (got '${UE_IP:-empty}'). Restart srsUE first." >&2
  exit 1
fi

ip netns exec "$NS" ip route replace "$IMS_NET" via "$GW" dev "$DEV"

echo "UE_IP=$UE_IP  P-CSCF=$PCSCF  local SIP port=$LOCAL_PORT"
echo "ping IMS gw..."
ip netns exec "$NS" ping -c 2 -W 2 "$GW"
echo "ping P-CSCF..."
ip netns exec "$NS" ping -c 2 -W 2 "$PCSCF"

exec ip netns exec "$NS" sipp "${PCSCF}:5060" \
  -sf "$SCENARIO" \
  -i "$UE_IP" \
  -p "$LOCAL_PORT" \
  -s "$IMPU_USER" \
  -au "${IMPU_USER}@ims.mnc070.mcc901.3gppnetwork.org" \
  -ap "$IMS_DIGEST_SECRET" \
  -m 1 \
  -t u1 \
  -trace_msg \
  -trace_err \
  -timeout 30 \
  -timeout_error
