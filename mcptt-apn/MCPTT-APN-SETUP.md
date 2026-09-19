# Path 2 — Dedicated `mcptt` APN setup (Open5GS + Android + app)

This is the practical way for a **normal third-party APK** to send MCPTT SIP
without the restricted **IMS** APN and without the **Internet** APN.

```text
Phone preferred data APN = mcptt (type=default)
        │  UE IP e.g. 192.168.102.x
        ▼
Open5GS UPF (DNN mcptt)
        │
        ▼
Host-published P-CSCF  172.30.104.240:5060
        │
        ▼
S-CSCF → MCPTT AS :5070
```

**Critical Android rule:** do **not** set APN type to `ims` or `mcx`.
Those are restricted networks; ordinary apps get `SecurityException`.
Use APN type **`default`** and select `mcptt` as the preferred mobile-data APN.

Full guide mirrors [docker_open5gs provisioning](https://github.com/herlesupreeth/docker_open5gs#provisioning-of-sim-information)
(internet + ims), then adds a third DNN: **`mcptt`**.

---

## Lab IP pools (recommended)

| APN / DNN | UE IPv4 pool | Who uses it | Android APN type |
|-----------|--------------|-------------|------------------|
| `internet` | `192.168.100.0/24` | browsing / general data | `default` (do **not** select for MCPTT) |
| `ims` | `192.168.101.0/24` | native VoLTE modem | `ims` (system only) |
| **`mcptt`** | **`192.168.102.0/24`** | **this APK SIP/RTP** | **`default`** ← select as preferred data |

App Settings defaults: APN name `mcptt`, IPv4 prefix `192.168.102.`

---

## 1) Open5GS — add DNN `mcptt` (WebUI + SMF/UPF)

docker_open5gs already documents **internet** and **ims**. You add **mcptt** the same way, plus a third UE subnet in SMF/UPF.

### 1A — SMF / UPF subnet (required before phones can attach to `mcptt`)

On the ogs host (`~/docker_open5gs` or your clone):

1. In `.env` (or equivalent), keep existing:

```text
UE_IPV4_INTERNET=192.168.100.0/24
UE_IPV4_IMS=192.168.101.0/24
```

2. Add a third pool (name may vary by your compose templates — the important part is SMF `session` + UPF `subnet` for `dnn: mcptt`):

```text
UE_IPV4_MCPTT=192.168.102.0/24
```

3. In SMF config (`smf.yaml` / generated from template), add a session next to internet/ims:

```yaml
smf:
  session:
    - subnet: 192.168.100.0/24
      gateway: 192.168.100.1
      dnn: internet
    - subnet: 192.168.101.0/24
      gateway: 192.168.101.1
      dnn: ims
    - subnet: 192.168.102.0/24
      gateway: 192.168.102.1
      dnn: mcptt
```

4. In UPF config, add the matching subnet / TUN (third ogstun or alias on existing TUN — follow how your tree already splits internet vs ims). Example pattern:

```yaml
upf:
  session:
    - subnet: 192.168.102.0/24
      gateway: 192.168.102.1
      dnn: mcptt
      # + dnn / interface name as in your docker_open5gs UPF template
```

5. Host routing: ensure UE packets from `192.168.102.0/24` can reach the **host-published** P-CSCF
   (`172.30.104.240:5060` in this lab), not only Docker-internal `172.22.0.21`.
   Same publication you already needed for VIA-PCSCF tests.

6. Recreate/restart **smf** and **upf** (and any compose service that regenerates their configs).

> If WebUI alone shows session `mcptt` but SMF has no `dnn: mcptt` subnet, attach fails with
> missing DNN / no IP pool. WebUI subscriber entry is **not** enough by itself.

### 1B — Open5GS WebUI subscriber (like internet + ims)

Open WebUI (typically `http://<DOCKER_HOST_IP>:9999` — use your ogs host IP).

For **each** test IMSI (e.g. `491234567890123`, `491234567890124`):

1. Open the subscriber (or create it as in the docker_open5gs README).
2. Keep existing sessions:
   - `internet` — QCI 9 default (non-GBR)
   - `ims` — QCI 5 default (signalling)
3. **Add Session** / APN:
   - **DNN / APN:** `mcptt`
   - **Type:** IPv4
   - **QoS Index (QCI):** `9` (or `8`) for the default bearer — same idea as internet  
     (Do **not** set this default to 65; dedicated bearers stay a separate PCC topic.)
   - **ARP Priority:** e.g. `8` (similar to internet) or slightly higher if you prefer
   - **Capability / Vulnerability:** Disabled / Disabled (match internet row style)
   - **AMBR:** unlimited or lab defaults
4. Save. Confirm the subscriber now lists **three** sessions: `internet`, `ims`, `mcptt`.

Reference table style (from docker_open5gs README + mcptt row):

| APN | Type | QCI | ARP | Capability | Vulnerability | Notes |
|-----|------|-----|-----|------------|---------------|-------|
| internet | IPv4 | 9 | 8 | Disabled | Disabled | general data |
| ims | IPv4 | 5 | 1 | Disabled | Disabled | VoLTE / restricted on Android |
| **mcptt** | IPv4 | **9** | **8** | Disabled | Disabled | **app SIP/RTP** |

### 1C — Optional: pyHSS APN list (if you also provision there)

If you use pyHSS swagger (`:8080/docs`) like the README:

1. **Create APN** payload:

```json
{
  "apn": "mcptt",
  "apn_ambr_dl": 0,
  "apn_ambr_ul": 0
}
```

2. Note the new `apn_id`.
3. Update **subscriber** `apn_list` to include internet + ims + mcptt IDs, e.g. `"1,2,3"`.
4. Keep `default_apn` as **internet** (or mcptt only if you want MCPTT as attach default — for phones that select APN manually, internet as default_apn is fine).

IMS subscriber / Digest IMPUs for Kamailio stay as you already have for REGISTER.

---

## 2) Android phone — create APN `mcptt`

Your friends already added **internet** and **ims**. Add a third entry.

### 2A — UI path (typical Xiaomi / stock Android)

1. Settings → **SIM & network settings** / **Mobile network** → **Access Point Names**.
2. Tap **+** / Add.
3. Fill exactly:

| Field | Value | Why |
|-------|--------|-----|
| **Name** | `MCPTT` | display only |
| **APN** | `mcptt` | **must match** Open5GS DNN string |
| **Proxy / Port / Username / Password / Server** | leave empty | |
| **MMSC / MMS proxy / MMS port** | leave empty | |
| **MCC / MNC** | your SIM (e.g. 901 / 70) | must match PLMN |
| **Authentication type** | Not set / None | unless you configured PAP/CHAP |
| **APN type** | **`default`** | **NOT `ims`, NOT `mcx`** |
| **APN protocol** | IPv4 | match Open5GS |
| **APN roaming protocol** | IPv4 | |
| **Bearer** | Unspecified | |
| **MVNO type/value** | None | unless your SIM needs it |

4. Save.
5. **Select the radio button** next to **MCPTT** so it becomes the **preferred mobile data APN**.
   - Leave **ims** present for VoLTE (modem).
   - Leave **internet** present but **not** selected while testing MCPTT SIP.
6. Toggle Airplane mode ON/OFF (or restart modem) so the UE re-establishes PDN.
7. Verify data IP is in **`192.168.102.x`**, not `.100` / `.101`:

```bash
adb shell ip addr | grep -E 'rmnet|wlan'
# or in phone: Settings → About → Status → IP address
```

Optional adb check:

```bash
adb shell dumpsys connectivity | head -n 80
adb shell ping -c 2 172.30.104.240
```

Ping must succeed **from the mcptt PDN** toward the host P-CSCF.

### 2B — What NOT to do

| Mistake | Result |
|---------|--------|
| APN type = `ims` | Restricted; app cannot bind |
| APN type = `mcx` | Restricted; `SecurityException` on NetworkRequest |
| Prefer **internet** APN while testing | App may bind `192.168.100.x`; SIP still wrong path / rejected |
| Point app at `172.22.0.21` | Docker-internal; unreachable from UE |
| Expect two simultaneous `default` PDNs without OEM help | Ordinary phones usually bring one preferred data APN |

### 2C — Simultaneous Internet + MCPTT

Ordinary Android cannot cleanly dual-homed “internet for Chrome + mcptt for app” without restricted capabilities / OEM. For lab phones dedicated to MCPTT: **select `mcptt` as preferred data**. Use Wi‑Fi for browsing if needed (or switch APN back to internet after tests).

---

## 3) App (already updated)

- Mode **MCPTT APN** (default): binds SIP/RTP via `McpttApnNetworkManager` to cellular INTERNET PDN matching prefix `192.168.102.`
- SIP destination: **P-CSCF** (`172.30.104.240:5060`), not Direct-AS `:5070`
- Direct-AS mode **removed**
- Settings fields: APN name, IPv4 prefix, P-CSCF host/port

Build/install, then:

1. Confirm phone preferred APN = `mcptt` and IP `192.168.102.x`
2. App Settings → MCPTT APN → Save
3. REGISTER → should appear in P-CSCF / S-CSCF / AS logs

If start fails with “no mcptt PDN”, the preferred APN is still internet/IMS or the Open5GS pool does not match the prefix.

---

## 4) Quick verification checklist

| Step | Pass criteria |
|------|----------------|
| SMF has `dnn: mcptt` subnet | `192.168.102.0/24` |
| WebUI subscriber has session `mcptt` | Saved on both IMSIs |
| Phone APN `mcptt` type=`default`, selected | Preferred data |
| UE IP | `192.168.102.x` |
| Ping P-CSCF host | `ping 172.30.104.240` OK |
| App Net line | `bound … (192.168.102.x) [mcptt]` |
| REGISTER | 401/200 in P-CSCF, not only AS Direct |

---

## 5) Relation to Exp9 QoS (QCI 65)

Exp9C QCI 65 was proven on the **IMS** PDN with AF-App-Id MCPTT ICSI.
Path 2 moves SIP onto **DNN mcptt**. Dedicated-bearer / Rx policy for that DNN is a
**follow-on** (PCC templates for APN `mcptt`, P-CSCF Rx still tied to where SIP lands).
Get REGISTER + call working on `mcptt` first; then extend PCC if you need QCI 65 on this APN.
