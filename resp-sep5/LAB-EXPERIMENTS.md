# MCPTT lab — remaining experiments (after Exp 1–4A)

Copy this file with `mcptt-server.py` and `sipp/` onto the lab VMs. Do not put
Ki, OP/OPc, ADM, or the IMS digest secret in git; use environment variables.

## What is already proven

| Exp | Result | Meaning |
|-----|--------|---------|
| 1 | PASS | srsUE + ZMQ + Open5GS, APN=`ims`, UE in `192.168.101.0/24` |
| 2 | PASS | SIP OPTIONS to **P-CSCF container** `172.22.0.21:5060` over GTP-U |
| 3 | PASS | IMS REGISTER, MD5 Digest, `200 OK`, P-Associated-URI, Service-Route |
| 4 | PARTIAL | S-CSCF `MCPTT_AS_CHECK` delivered INVITE to AS `:5070`; **200 OK did not complete** |

Experiment 4 failed the transaction, not the architecture. The AS copied only
the **last Via** (the UE). Kamailio `tm` matches the AS-side INVITE on the
**top Via branch** (S-CSCF). It ignored the 200 OK, retransmitted INVITE at
T1=500 ms, then sent `408 Request Timeout`.

`mcptt-server.py` 1.2 copies every Via and Record-Route. That is the next
deploy, not a rewrite.

Authentication is still **MD5 Digest**, not IMS AKA/IPsec. Leave that until
after group/RTP/QoS.

---

## Hosts (do not mix them up)

```text
Demo  172.30.104.230    srsENB, srsUE, netns ue1, SIPp
ogs   172.30.104.240    Open5GS + Kamailio IMS (docker_open5gs) + MCPTT AS
```

IMS Docker net `172.22.0.0/24`:

```text
P-CSCF  172.22.0.21:5060
I-CSCF  172.22.0.19:4060
S-CSCF  172.22.0.20:6060
PyHSS   172.22.0.18:3875
MCPTT AS (host)  172.30.104.240:5070/udp
```

P-CSCF is **not** `172.30.104.240:5060`. Do not publish host `:5060`.

---

## Should the MCPTT AS stay on the EPC/IMS VM?

**Yes.** Keep it on `ogs` at `172.30.104.240:5070`. S-CSCF already reaches that
address (`MCPTT_AS_URI`). The 408 was a Via bug, not co-location.

Do **not** move it into Docker until 200/ACK works. A later optional cleanup is
a container on `172.22.0.x` so ISC stays on the IMS bridge. That is cosmetics.

---

## Should we replace sipsak with SIPp?

**Yes for REGISTER/INVITE/ACK/BYE.** sipsak is fine for OPTIONS. It is a poor
UAC: wrong host in Via/Contact (`172.30.104.30`), changing source ports, no ACK
dialog. This lab’s P-CSCF uses `match_contact_host_port = 1`, so INVITE must
reuse the **exact** registered Contact host:port.

SIPp keeps one `-i` / `-p` for REGISTER and INVITE. Use
`sipp/register-then-invite.xml`.

```bash
# on Demo
sudo apt-get update
sudo apt-get install -y sip-tester   # Debian package name for SIPp
sipp -v
```

If the package is too old, build from https://github.com/sipp/sipp.

Keep sipsak for:

```bash
sudo ip netns exec ue1 sipsak -vvv -E udp -s sip:172.22.0.21:5060
```

---

## Waydroid vs Genymotion — when to touch Android

**Not now.** Finish Exp 4 completion → 5 (group) → 6 (RTP) first.

Neither Waydroid nor Genymotion is an LTE modem. `srsUE` remains the UE.
Android is only a SIP/RTP application source into `tun_srsue`.

| | Waydroid | Genymotion Android 10 |
|--|----------|------------------------|
| Fits this Linux lab | Yes (LXC on the RAN host or a Linux workstation) | Yes, but a separate Desktop VM |
| Matches Xiaomi Android 10 | **No** (typically 11/13) | **Yes (API 29)** |
| Root / priv-app / VpnService | Possible | Possible |
| Binder Option B | Yes in principle | Yes in principle |
| Pain | binder/wayland, images, not Android 10 | license, VirtualBox/QEMU |

Use **Genymotion Android 10** when the point is OEM-shaped Option B
(`priv-app` + later `NET_CAPABILITY_IMS` story). Use **Waydroid** when the
point is “can this APK send SIP with the IMS PDN IP into `tun_srsue` on
Linux without buying Genymotion.” Do not start either until SIPp gets 200 OK.

---

## Every session: LTE user-plane preflight (Demo)

The bearer dies after srsUE restart while `tun_srsue` still shows an address.

```bash
# Demo
UE_IP=$(sudo ip netns exec ue1 ip -4 -o addr show tun_srsue | awk '{print $4}' | cut -d/ -f1)
echo "UE_IP=$UE_IP"   # must be 192.168.101.x, not 192.168.100.x

sudo ip netns exec ue1 ip route replace 172.22.0.0/24 via 192.168.101.1 dev tun_srsue
sudo ip netns exec ue1 ping -c 3 192.168.101.1
sudo ip netns exec ue1 ping -c 3 172.22.0.21
```

If pings fail: restart srsENB then srsUE, then re-run the route. Do not send SIP
until both pings work.

---

## Experiment 4 completion — 200 OK + ACK through S-CSCF

### 4C1 — Deploy the Via-fixed AS (ogs)

```bash
# ogs
cd ~/mcptt-server
# replace mcptt-server.py with the 1.2 file from this repo
python3 mcptt-server.py --advertise 172.30.104.240
```

```bash
ss -lunp | grep 5070
# UNCONN ... 172.30.104.240:5070 ... python3
```

### 4C2 — Captures (ogs) before the INVITE

```bash
# host view of AS
sudo tcpdump -ni any udp port 5070 -w /tmp/as-5070.pcap

# inside S-CSCF netns — this is the proof that tm saw the 200
docker inspect scscf --format '{{.State.Pid}}'
sudo nsenter -t "$(docker inspect scscf --format '{{.State.Pid}}')" -n \
  tcpdump -ni any udp port 5070 or udp port 6060 -w /tmp/scscf-mcptt.pcap
```

Also:

```bash
docker logs -f scscf
# expect: S-CSCF [MCPTT]: Intercepted MCPTT INVITE
# expect: S-CSCF [MCPTT]: Received Reply 200 from MCPTT Mock AS
```

AS log must show **`via=3 top=...172.22.0.20:6060`** (or 2 hops), **not**
`via=1 top=192.168.101.x`.

### 4C3 — SIPp (Demo)

```bash
# Demo — never echo the secret into the shell history if you can avoid it
export IMS_DIGEST_SECRET='...'   # IMS Digest, not Ki
chmod +x sipp/run-exp4-complete.sh
sudo -E ./sipp/run-exp4-complete.sh
```

Manual equivalent:

```bash
UE_IP=$(sudo ip netns exec ue1 ip -4 -o addr show tun_srsue | awk '{print $4}' | cut -d/ -f1)
sudo ip netns exec ue1 ip route replace 172.22.0.0/24 via 192.168.101.1 dev tun_srsue

sudo ip netns exec ue1 sipp 172.22.0.21:5060 \
  -sf sipp/register-then-invite.xml \
  -i "$UE_IP" -p 5062 \
  -s 491234567890123 \
  -au 491234567890123@ims.mnc070.mcc901.3gppnetwork.org \
  -ap "$IMS_DIGEST_SECRET" \
  -m 1 -t u1 -trace_msg -timeout 30 -timeout_error
```

### 4C4 — Pass criteria

```text
SIPp exits 0
REGISTER 401 then 200
INVITE → 100 (optional) → 200  (NOT 408)
ACK reaches AS (log: ACK Call-ID=...)
BYE → 200
scscf pcap: 200 OK with top Via = S-CSCF, then ACK toward :5070
UE / SIPp receives 200 OK (not generated locally as timeout)
```

Do **not** change `default_ifc.xml`, PCRF, P-CSCF, or Open5GS for this step.
Keep `MCPTT_AS_CHECK`. iFC is a later experiment.

If 408 persists: open `/tmp/scscf-mcptt.pcap`. If 200 never appears in the
**container** netns, it is Docker path filter. If 200 is there but top Via is
still the UE, the old AS is still running.

---

## Experiment 5 — group + floor (SIP INFO)

Still no Android. Still no iFC.

1. Repeat 4C with SIPp UE-1 (keep the dialog up: comment out BYE in the XML or
   increase the pause).
2. Join a second participant **Direct-AS** to `172.30.104.240:5070` (the
   already-working Android/Direct path, or a second SIPp aimed at `:5070`
   with `INVITE sip:group1@...` and User-Agent MCPTT).
3. Send SIP INFO `action=floor-request` from UE-1; AS should INFO
   `floor-granted` / `floor-taken` to peers.

```bash
# second UAC straight at the AS (ogs or any host that can reach 172.30.104.240)
sipp 172.30.104.240:5070 -sn uac -s group1 -m 1 -d 8000
```

Better: a small INFO scenario after INVITE/ACK. Pass when **two** legs exist
in AS logs (`New MCPTT session` then a second INVITE on the same group) and
floor INFO is seen on both.

Two full IMS UEs (two srsUE, two IMSIs) is the correct group test. Do that
when one-UE + Direct-AS mixer works. Second srsUE needs its own ZMQ ports,
netns, IMSI in Open5GS, and PyHSS identity.

---

## Experiment 6 — RTP through the mixer

After two legs are ESTABLISHED:

```bash
# ogs
sudo tcpdump -ni any udp portrange 10000-20000 -w /tmp/mcptt-rtp.pcap
```

From Demo, send PCMU toward the AS RTP port printed in the 200 OK SDP
(`m=audio 1000x`). `sox`/`ffmpeg` or SIPp RTP (`-mp`) works.

Pass: AS logs `RTP rx=` and `RTP fwd` to the peer; peer pcap shows PCMU.

Floor: RTP from a non-holder may be dropped (current mixer policy). That is
expected until you hold the floor.

---

## Experiment 7 — MBCP (TS 24.380)

Do **not** start this until 4C + 5 + 6 pass. Keep SIP INFO as the lab floor
transport. MBCP is RTCP APP `MCPT` (the server already has a stub
`send_3gpp_floor_grant`). Treat a real 24.380 state machine as a separate
change, not mixed with the Via fix.

---

## Experiment 8 — iFC instead of `MCPTT_AS_CHECK`

Only after 4C is green. Clone `default_ifc.xml` to a **new** file (do not
uncomment the stock `applicationserver...` hostname). Point
`<ServerName>` at:

```text
sip:172.30.104.240:5070;transport=udp
```

Method `INVITE`, and/or ICSI `urn:urn-7:3gpp-service.ims.icsi.mcptt`.
Re-REGISTER so S-CSCF downloads the new profile. Then **disable**
`MCPTT_AS_CHECK` on a copy of the cfg and prove iFC still routes. Do not
remove the hook until that proof exists.

---

## Experiment 9 — Rx / Gx / QCI 65

Preserve Open5GS PCRF. The AS (or a tiny AF) sends Diameter Rx AAR with the
UE IMS IP `192.168.101.x` and media flows. Watch:

```bash
docker logs -f pcrf
docker logs -f smf   # or pgw-c depending on this compose
```

srsENB `drb.conf` must list QCI 65. Proof is **Create Bearer + new GTP-U TEID**,
not a speed test over ZMQ. Radio GBR over ZMQ is functional only.

P-CSCF already has `WITH_RX` / `ims_qos`. REGISTER AAR for signalling is
separate from QCI 65 for media. Do not confuse the earlier
`403 Can't register to QoS for signalling` (wrong Via host `172.30.104.30`)
with missing QCI 65.

---

## Experiment 10 — Android (Waydroid or Genymotion)

Only after SIPp 200/ACK.

1. Rooted Android 10 Genymotion **or** Waydroid.
2. Keep Option B: GUI APK → Binder → `McpttConnectivityService`.
3. Lab backend: VpnService TUN addressed with the **current** IMS PDN IP,
   L3 splice into `ue1`/`tun_srsue`.
4. Pass: Kamailio sees REGISTER/INVITE from `192.168.101.x`, not from the
   emulator’s VirtualBox/Waydroid address.

`requestNetwork(NET_CAPABILITY_IMS)` will still fail on emulators (no modem).
That is expected.

---

## What not to change yet

- Open5GS EPC, PCRF, P-CSCF, I-CSCF
- `default_ifc.xml` (until Exp 8)
- Publishing host `:5060`
- Switching the project to the Internet APN
- A 12-module “production” AS rewrite
- IMS AKA/IPsec (after media/QoS)

---

## Commands to leave running during 4C

**ogs terminal A** — AS  
**ogs terminal B** — `docker logs -f scscf`  
**ogs terminal C** — `tcpdump` on 5070  
**ogs terminal D** — `nsenter` tcpdump in scscf  
**Demo** — preflight + SIPp
