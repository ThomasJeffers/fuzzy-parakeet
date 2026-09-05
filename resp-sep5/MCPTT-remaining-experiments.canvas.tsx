import {
  Callout,
  Card,
  CardBody,
  CardHeader,
  Code,
  Divider,
  Grid,
  H1,
  H2,
  H3,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
  TodoListCard,
  useCanvasState,
} from "cursor/canvas";

type TabId = "now" | "commands" | "android" | "tools";

const TABS: Array<{ id: TabId; label: string }> = [
  { id: "now", label: "Do this now" },
  { id: "commands", label: "Command sheets" },
  { id: "android", label: "Waydroid vs Genymotion" },
  { id: "tools", label: "SIPp vs sipsak" },
];

export default function McpttRemainingExperiments() {
  const [tab, setTab] = useCanvasState<TabId>("tab", "now");

  return (
    <Stack gap={20} style={{ padding: 24, maxWidth: 1080 }}>
      <Stack gap={8}>
        <H1>MCPTT lab — next experiments</H1>
        <Text tone="secondary">
          Experiments 1–3 passed. Experiment 4 invoked the AS through S-CSCF but
          Kamailio timed out the INVITE. The AS copied only the last Via (UE).
          Deploy mcptt-server.py 1.2, then SIPp REGISTER+INVITE+ACK. Android waits.
        </Text>
      </Stack>

      <Row gap={16} align="end" wrap>
        <Stat value="4" label="Open: 200 OK / ACK" tone="warning" />
        <Stat value="MD5" label="IMS auth (not AKA)" tone="info" />
        <Stat value="Later" label="Android / Waydroid" />
      </Row>

      <Callout tone="warning" title="Do not rewrite the AS into twelve modules">
        The current single-file server is a valid lab AS once Via/Record-Route are
        copied. Prometheus, YAML, MBCP-complete, and iFC do not fix 408. Keep
        Direct-AS and python3 mcptt-server.py --advertise 172.30.104.240.
      </Callout>

      <Row gap={8} wrap>
        {TABS.map((item) => (
          <span key={item.id}>
            <Pill active={tab === item.id} onClick={() => setTab(item.id)}>
              {item.label}
            </Pill>
          </span>
        ))}
      </Row>

      {tab === "now" && <NowPanel />}
      {tab === "commands" && <CommandsPanel />}
      {tab === "android" && <AndroidPanel />}
      {tab === "tools" && <ToolsPanel />}

      <Text tone="tertiary" size="small">
        Full command sheets: mcptt-client/LAB-EXPERIMENTS.md. Secrets stay in
        IMS_DIGEST_SECRET, never in git.
      </Text>
    </Stack>
  );
}

function NowPanel() {
  return (
    <Stack gap={16}>
      <H2>Scoreboard</H2>
      <Table
        headers={["Exp", "Goal", "Status"]}
        columnAlign={["left", "left", "left"]}
        rowTone={[
          "success",
          "success",
          "success",
          "warning",
          "neutral",
          "neutral",
          "neutral",
        ]}
        rows={[
          ["1", "srsUE attach, APN=ims, 192.168.101.x", "PASS"],
          ["2", "OPTIONS to 172.22.0.21:5060 over GTP-U", "PASS"],
          ["3", "IMS REGISTER, MD5, 200, Service-Route", "PASS"],
          ["4", "INVITE → S-CSCF → AS :5070 → 200/ACK to UE", "AS reached; 408 open"],
          ["5", "Two legs, SIP INFO floor", "After 4C"],
          ["6", "RTP mixer PCMU", "After 5"],
          ["7–10", "MBCP, iFC, QCI 65, Android splice", "Later"],
        ]}
        striped
      />

      <H2>Root cause of the 408</H2>
      <Text>
        S-CSCF sends INVITE with three Via hops (S-CSCF, P-CSCF, UE). The old
        get_header() returned the last Via. 200 OK therefore looked like a
        response to the UE transaction, not to Kamailio tm. Timer A (0.5, 1.5,
        3.5, 7.5 s) matches the AS “retransmitted INVITE / re-sending 200”
        log. Capture of host 5070→6060 does not mean tm matched.
      </Text>

      <Grid columns={2} gap={16}>
        <Card>
          <CardHeader>Keep on ogs</CardHeader>
          <CardBody>
            <Text>
              MCPTT AS on 172.30.104.240:5070 is correct. Co-location with
              EPC/IMS is fine. Do not Dockerize the AS until 200/ACK works.
            </Text>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>Do not touch yet</CardHeader>
          <CardBody>
            <Text>
              default_ifc.xml, PCRF, P-CSCF, host port 5060, Internet APN, IMS
              AKA. The custom MCPTT_AS_CHECK hook stays until a dedicated iFC
              experiment succeeds.
            </Text>
          </CardBody>
        </Card>
      </Grid>

      <TodoListCard
        defaultExpanded
        todos={[
          {
            id: "d1",
            content: "ogs: replace mcptt-server.py with 1.2, bind 172.30.104.240:5070",
            status: "pending",
          },
          {
            id: "d2",
            content: "ogs: tcpdump on host :5070 AND inside scscf netns",
            status: "pending",
          },
          {
            id: "d3",
            content: "Demo: bearer preflight (ping 192.168.101.1 and 172.22.0.21)",
            status: "pending",
          },
          {
            id: "d4",
            content: "Demo: SIPp register-then-invite.xml — expect 200 not 408",
            status: "pending",
          },
          {
            id: "d5",
            content: "Confirm AS log via=N top=172.22.0.20, then ACK",
            status: "pending",
          },
        ]}
      />
    </Stack>
  );
}

function CommandsPanel() {
  return (
    <Stack gap={16}>
      <H2>Every session — Demo user plane</H2>
      <Code>
        {`UE_IP=$(sudo ip netns exec ue1 ip -4 -o addr show tun_srsue | awk '{print $4}' | cut -d/ -f1)
echo "$UE_IP"   # 192.168.101.x only
sudo ip netns exec ue1 ip route replace 172.22.0.0/24 via 192.168.101.1 dev tun_srsue
sudo ip netns exec ue1 ping -c 3 192.168.101.1
sudo ip netns exec ue1 ping -c 3 172.22.0.21`}
      </Code>

      <H2>ogs — AS and proof captures</H2>
      <Code>
        {`python3 mcptt-server.py --advertise 172.30.104.240
ss -lunp | grep 5070
sudo tcpdump -ni any udp port 5070 -w /tmp/as-5070.pcap
sudo nsenter -t "$(docker inspect scscf --format '{{.State.Pid}}')" -n \\
  tcpdump -ni any udp port 5070 or udp port 6060 -w /tmp/scscf-mcptt.pcap
docker logs -f scscf`}
      </Code>

      <H2>Demo — Experiment 4C (SIPp)</H2>
      <Code>
        {`export IMS_DIGEST_SECRET='...'   # digest, not Ki
sudo apt-get install -y sip-tester
sudo -E ./sipp/run-exp4-complete.sh`}
      </Code>
      <Text tone="secondary">
        Pass: SIPp exit 0, INVITE 200 (not 408), ACK on AS, BYE 200. AS log
        via count greater than 1 with top hop S-CSCF.
      </Text>

      <Divider />
      <H3>After 4C</H3>
      <Table
        headers={["Exp", "First command / check"]}
        rows={[
          [
            "5 Group + INFO",
            "Second INVITE to same group1 (Direct-AS :5070 or second SIPp). Floor INFO action=floor-request.",
          ],
          [
            "6 RTP",
            "tcpdump udp portrange 10000-20000; send PCMU to SDP m=audio port.",
          ],
          [
            "7 MBCP",
            "Do not start. Keep SIP INFO until 4–6 are green.",
          ],
          [
            "8 iFC",
            "New ifc file ServerName sip:172.30.104.240:5070;transport=udp. Re-REGISTER. Then drop MCPTT_AS_CHECK on a copy.",
          ],
          [
            "9 QCI 65",
            "Rx AAR with UE IMS IP. Proof = Create Bearer + new TEID, not ZMQ speed.",
          ],
          [
            "10 Android",
            "VpnService splice of IMS IP into tun_srsue. No requestNetwork(IMS) on emulator.",
          ],
        ]}
        striped
      />
    </Stack>
  );
}

function AndroidPanel() {
  return (
    <Stack gap={16}>
      <Callout tone="info" title="Android is not the next lab step">
        Genymotion and Waydroid both skip the modem. srsUE stays the LTE UE.
        Start an Android runtime only after SIPp receives INVITE 200 and ACK
        reaches the AS.
      </Callout>
      <Table
        headers={["", "Waydroid", "Genymotion Android 10"]}
        rows={[
          ["Role", "Linux LXC Android app host", "Android 10 API 29 VM"],
          ["LTE modem", "No", "No"],
          ["Match Xiaomi Android 10", "No (usually 11/13)", "Yes"],
          ["Option B priv-app", "Possible", "Possible"],
          ["When to use", "Cheap Linux splice test", "OEM-shaped Option B"],
        ]}
        striped
      />
      <Text>
        Waydroid is acceptable later for “APK packets into tun_srsue.” It is a
        weak stand-in for the Xiaomi IMS Network problem. Prefer Genymotion 10
        when presenting Option B to an Android team.
      </Text>
    </Stack>
  );
}

function ToolsPanel() {
  return (
    <Stack gap={16}>
      <H2>sipsak vs SIPp</H2>
      <Table
        headers={["Job", "Tool"]}
        rows={[
          ["OPTIONS reachability to 172.22.0.21:5060", "sipsak is enough"],
          ["Digest REGISTER + INVITE + ACK + BYE", "SIPp (required)"],
          ["Same Contact host:port as REGISTER", "SIPp -i/-p for the whole scenario"],
          ["Via/Contact accidentally 172.30.104.30", "sipsak default; caused PCRF 403"],
        ]}
        striped
      />
      <Text>
        This P-CSCF sets match_contact_host_port=1. An INVITE from a new
        ephemeral port after REGISTER will look unregistered even when IMS
        registration succeeded. SIPp avoids that by binding one port.
      </Text>
    </Stack>
  );
}
