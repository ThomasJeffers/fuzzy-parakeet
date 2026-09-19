# Android MCPTT path forward (after Exp1–9C)

**Status:** Core/IMS/QoS proven with srsUE. Stock phones remain blocked for IMS APN.  
**Audience:** project lead / engineering  
**Related:** `WHY-SRSUE-NOT-ANDROID.md`, attached MCOP analysis, Phase 1B connectivity plugin

---

## Short answers

| Question | Answer |
|----------|--------|
| Can we put our third-party MCPTT APK into OEM-privileged **without rooting** the retail phones we already have? | **Not by ourselves.** That requires the **OEM (or a custom system image)** to preinstall the app under `/system/priv-app` (or product/priv-app) **and** whitelist `CONNECTIVITY_USE_RESTRICTED_NETWORKS` in `privapp-permissions-*.xml`. Root is only a DIY way to fake that on a device you control. |
| Does “give the app its own SIP stack” unlock the IMS APN? | **No.** Own SIP (MCOP Model A) only means the app can use **whatever non-restricted network Android gives it**. It does not grant `NET_CAPABILITY_IMS`. |
| Are we correct that Internet APN is wrong for MCPTT SIP-1 toward this lab / operator IMS P-CSCF? | **Yes for this architecture.** SIP-1 is supposed to ride the **MCPTT service APN** (often the well-known **IMS** APN). Internet APN → wrong PDN/IP → P-CSCF never sees a valid IMS UE. |
| Are we helpless without root? | **No.** There are real product/lab paths that do **not** require rooting your Xiaomis. They require choosing the right **architecture** and the right **partner/device**. |

---

## What the other AI got right (and one refinement)

Their MCOP analysis is correct:

- MCOP = **independent SIP stack** over ordinary IP (default/active network), **not** Android Single Registration / IMS PDN binding.
- Google’s IMS Single Registration / restricted IMS network needs `CONNECTIVITY_USE_RESTRICTED_NETWORKS` (`signature\|privileged`) or an OEM allowlist — **carrier privileges alone are not enough** (your experiment already proved that).

**Refinement for TS 23.179:** The standard does **not** say “must use Internet APN” or “must use IMS APN only.” It says the UE shall use an **MCPTT service APN** for SIP-1, which:

- **may** be the well-known **IMS** APN (if PLMN + MCPTT provider agree on QoS), or  
- **may** be a **different** dedicated APN, or  
- may share another APN with compatible QoS.

So:

- Using **Internet/default** for SIP-1 is **not** what 23.179 intends when the SIP core is operator IMS.  
- Using a **dedicated MCPTT/MCX APN** (not the restricted `ims` type) is standards-aligned **and** often easier on Android than hijacking VoLTE’s IMS PDN.  
- Using **IMS** is allowed by the NOTE in 5.2.9.1, but on Android that hits the **restricted network** wall for ordinary apps.

---

## Why carrier privilege failed (do not retry that hope)

```text
Carrier privilege (UICC cert)  ≠  OEM / priv-app privilege
        │                                    │
        ▼                                    ▼
  carrier config, some                  CONNECTIVITY_USE_RESTRICTED_NETWORKS
  telephony APIs                        NET_CAPABILITY_IMS / SipTransport
        │                                    │
        ✗ still blocked for IMS PDN          ✓ can bind to IMS (if OEM ships it)
```

Your Phase 1B plugin (`connectivity-service` + `privapp-permissions-mcptt-connectivity.xml`) is the **correct** design for Model B — but it only works after the APK is **system-preinstalled and allowlisted**, not after sideload + carrier cert.

---

## Paths that do **not** require rooting your current phones

Ranked for this project:

### Path 1 — Lab continuity (fastest): Android app → VpnService / TUN → srsUE IMS IP

- App stays a normal APK (own SIP stack).
- LTE/IMS PDN stays on **srsUE** (already proven).
- Phone/emulator only generates SIP/RTP; packets enter `tun_srsue`.
- **Does not** solve “APK on commercial modem uses real IMS APN.”
- **Does** let you demo the MCPTT client UI against the real EPC/IMS/QCI-65 lab.

### Path 2 — Product architecture A: own SIP + **dedicated MCPTT APN** (not `type=ims`)

**Status: implemented in this tree** — see [`MCPTT-APN-SETUP.md`](MCPTT-APN-SETUP.md) and app mode `VIA_MCPTT_APN`.

- Own SIP/REGISTER (already in app).
- Open5GS DNN `mcptt` + phone APN `mcptt` with type **`default`** (not `ims`/`mcx`).
- App binds via `McpttApnNetworkManager` to UE pool `192.168.102.x` → host P-CSCF.

### Path 3 — Product architecture B: OEM-preinstalled privileged plugin (no root for end users)

- You **cannot** do this on retail Xiaomis by yourself.
- You **can** do it with:
  - OEM partnership (app in system image + privapp allowlist), or  
  - Engineering / AOSP / custom ROM builds you control, or  
  - Devices sold as “MCPTT handsets” with your APK already privileged.
- End users never root; the **manufacturer** baked privilege in at flash time.
- Use your existing `McpttConnectivityService` + `privapp-permissions-mcptt-connectivity.xml` on that image.

### Path 4 — Dual registration over a **publicly reachable** SIP edge (different product)

- App uses Internet/Wi‑Fi to an SBC / P-CSCF that is on the public or enterprise path.
- Not the same as “use phone’s VoLTE IMS APN.”
- Valid for some MCPTT deployments; **not** a drop-in for this lab’s `172.22.0.21` on IMS Docker.

### Path 5 — Android Single Registration / SipDelegate

- Needs privileged + IMS framework integration (OEM/vendor ImsService).
- Heavier than Path 2/3 for an MCPTT lab client; usually OEM roadmap.

---

## Direct reply to: “upgrade APK to own SIP so it uses IMS APN?”

```text
Own SIP stack          →  YES, upgrade (needed for Model A / MCOP-like client)
Own registration       →  YES
Own sockets            →  YES
Automatically use IMS  →  NO on stock Android
```

Owning the SIP stack only removes dependency on Android’s VoLTE SIP. It does **not** move those sockets onto the restricted IMS interface.

To use **IMS** specifically you still need Path 3 (or root/custom image).  
To stay standards-aligned for SIP-1 **without** fighting VoLTE’s IMS PDN, prefer Path 2 (**MCPTT/MCX APN** + reachable SIP core) or Path 1 for lab demos.

---

## “Can’t use Internet APN for MCPTT/SIP?” — precise wording for the boss

1. **This Open5GS lab:** Correct — Internet APN SIP never reaches the IMS P-CSCF path; wrong PDN.  
2. **TS 23.179:** Correct that SIP-1 should use the **MCPTT service APN**, which is often IMS, **not** the generic Internet APN.  
3. **Commercial product:** Internet APN *can* carry SIP only if you deliberately design a **non-IMS dual-registration** edge (Path 4). That is a different architecture from “MCPTT over operator IMS PDN / QCI 65 as in our lab.”

---

## Recommended next move (practical)

1. **Do not** keep trying carrier privilege or sideload for IMS on stock phones — dead end.  
2. **Do** evolve the Android client toward **own SIP stack** (Model A), matching what MCOP actually does.  
3. **Lab demo now:** Path 1 (VpnService → srsUE) so the APK talks to the proven EPC.  
4. **Phone + real modem later:** either  
   - Path 2: dedicated `mcptt`/`MCX` APN on Open5GS + route to SIP core, or  
   - Path 3: one OEM/engineering build with priv-app connectivity plugin for true IMS PDN.

You are not blocked on the **network** work (that is done). You are at a **handset privilege / APN product decision**, not a missing SIP feature in the APK.
