# Architecture and operations

## Transport selection

Use exactly one protocol in a listener's `Protocols` array. Deploy separate listeners for different transports.

### Plain UDP

`["udp"]` delivers the datagram payload. Add application authentication where needed; source filtering is not proof of identity. Passing a stateful encrypted protocol through plain UDP does not implement that protocol in Lambda.

### WireGuard

`["wg"]` terminates WireGuard at the gateway. Set either known `Peers` or intentionally enable `AllowUnknownPeers`. Peer fields are `PublicKey`, optional `AllowedIPs`, and optional 32-byte base64 `SharedSecret`. Open-peer mode can use `UnknownPeerPreSharedKey`; do not commit that secret.

```json
{
  "Protocols": ["wg"],
  "Peers": [{
    "PublicKey": "<client-public-key>",
    "AllowedIPs": ["10.0.0.2/32"]
  }],
  "DecapsulatedDelivery": true,
  "ClientRestrictions": { "Networks": ["203.0.113.10/32"] }
}
```

The CIDR restriction above is the client's **public outer source**, not `10.0.0.2`. `AllowedIPs` constrains tunnel source addresses. Output `WireGuardPublicKey` for the client's peer configuration.

`DecapsulatedDelivery` is a **listener property**, not a destination property. With it enabled, use application payload plus `Inner` metadata. Without application-level decapsulation, the tunnel path delivers inner IP packets: SDK `DecapsulatedHandler` parses `message.Data` as a complete IP packet. Do not feed it only UDP application bytes or return a UDP payload where a complete IP response is required. Check the actual delivery fixture against the deployed gateway; use the matching example/SDK path.

Example client settings:

```ini
[Interface]
PrivateKey = <client-private-key>
Address = 10.0.0.2/32

[Peer]
PublicKey = <listener-WireGuardPublicKey>
Endpoint = <listener-domain>:<listener-port>
AllowedIPs = 10.0.0.1/32
PersistentKeepalive = 25
```

Use only the service tunnel route needed. Do not default a client's `AllowedIPs` to `0.0.0.0/0`: that redirects all IPv4 traffic, and the listener is not automatically an Internet VPN router.

### DTLS

`["dtls"]` terminates DTLS 1.2/1.3 at the edge and delivers decrypted application data. Replies are encrypted into the client's session. This is not end-to-end encryption through Proxylity.

- `Psks`: identity-to-base64-key map for PSK clients; keep keys in protected configuration.
- `RequireCookies`: enable cookie protection for public endpoints unless client compatibility requires otherwise.
- `DtlsServerCertificate`: returned certificate; distribute/pin trust according to client requirements, not an assumed public CA chain.
- `CertRefreshToken`: change to rotate certificate material; coordinate client trust changes.
- `AllowEarlyData` / `EarlyDataWindowSeconds`: opt-in settings; early data is replay-sensitive. Keep disabled for non-idempotent operations unless replay handling is explicitly designed.

A DTLS listener alone is not a WebRTC signaling/SCTP service.

### WebRTC: verify deployment before offering it

Current control-plane source accepts `["webrtc"]`, but local code is not proof of account/region availability. Public documentation may lag. Verify service support and the signaling API before generating a deployable browser integration.

The implemented listener contract is deliberately narrow:

- Negotiated, unordered **binary data channel 0**.
- Fixed SCTP port **5000**, distinct from the allocated outer UDP listener port.
- **1024-byte unfragmented message cap**; not a general media, TURN, or arbitrary-channel endpoint.
- Mandatory cookies (`RequireCookies: false` is rejected).
- Certificate outputs: `DtlsServerCertificate`, `WebRtcFingerprint`, `WebRtcSctpPort`, `WebRtcChannelId`.
- `WebRtcSignalingMode` is `none` (default) or `public`. Public mode returns a signaling URL/token; handle the token as a bearer capability. `WebRtcSignalingRefreshToken` rotates it.
- WireGuard fields, DTLS PSK/early-data/ticket fields, and inline ICE credential fields are rejected. Transient ICE sessions are provisioned by signaling, not static template credentials.

Do not invent SDP, signaling request/response schemas, ICE lifecycle, browser fallback, or delivery guarantees from these listener attributes. Validate them against the deployed signaling implementation.

## BREX: filters and field extraction

BREX operates on packet bytes, not the JSON envelope or encoded base64 string. A destination `FilterExpression` gates delivery; its service-specific expressions belong under `Arguments`.

```json
{
  "FilterExpression": "u8[0] == 1",
  "Arguments": {
    "MessageGroupIdExpression": "[0:4]",
    "MessageGroupIdFormatter": "hex"
  }
}
```

Use this only for an SQS destination with a payload layout matching the expression.

Common forms include byte slices, typed little-/big-endian reads, dynamic offsets, conditionals, arithmetic, bitwise operations, null/error fallback, pipes, and searches. Consult the [BREX syntax reference](https://proxylity.com/docs/destinations/brex-syntax.html) and installed library grammar rather than assuming another expression language's syntax.

- `[0:4]`: bytes at offsets 0 through 3; `[4:8]`: offsets 4 through 7.
- `u8[0]`: unsigned first byte.
- `i32le[4:8]`: signed 32-bit little-endian field.
- `[:]`: whole payload.

Argument formatters are `ascii`, `utf8`, `hex`, and `base64`; **not `coap`, `coap+`, or `syslog`**. Names vary: SQS `MessageGroupIdFormatter`, Lambda `TenantIdFormatter`, IoT `TopicSuffixFormatter`, Kinesis **`PartitionKeyExpressionFormatter`**.

For WireGuard, confirm which inner bytes the selected decapsulation path supplies before choosing offsets. Test short/truncated packets, unsupported versions, invalid offsets, signed values, byte order, and all conditional branches. The control plane checks many property types but does not fully validate BREX syntax; successful stack creation is not proof that expressions work.

Filters provide selective fan-out, not application authentication. With `MetricsEnabled`, rejected traffic contributes to `FilteredPackets`/`FilteredBytes`. Do not assert billing behavior without current pricing terms.

## Batching and payload budgets

Set limits explicitly; do not rely on undocumented defaults:

| Property | Meaning |
|---|---|
| `Count` | Maximum packet count per batch |
| `TimeoutInSeconds` | Maximum batching wait, not a fixed end-to-end latency floor |
| `SizeInMB` | Advisory encoded-payload size threshold; at least one packet can be included |

Count/size triggers can flush before timeout. Start with `Count: 1, TimeoutInSeconds: 0.05` for latency tests; increase count/wait for throughput after measuring. A count of 1000 does not yield a 1000-fold saving at low traffic.

Budget for envelope metadata and base64 expansion (~4/3), not only UDP payload bytes. Respect the target's actual limits (including smaller async Lambda and Step Functions input budgets) and per-record as well as per-request quotas. `SizeInMB` does not make an oversized individual packet valid.

Gateway batching is not identical to downstream API batching: SQS/SNS batch calls, Kinesis records, and Firehose NDJSON records have different count/byte constraints. Verify the current adapter and AWS quotas before selecting production thresholds.

Keep datagrams within a measured path-MTU budget, including tunnel overhead. Do not promise automatic fragmentation/reassembly. CoAP block-wise transfers are application protocol behavior, not arbitrary large UDP datagrams.

## Multi-region registration

A listener is a global ingress resource. Regional compute requires explicit routing configuration; do not create a second global listener merely to add another compute region.

Known ARNs can be declared as a `DestinationArn` map:

```json
{
  "DestinationArn": {
    "us-east-1": "arn:aws:lambda:us-east-1:123456789012:function:handler",
    "us-west-2": "arn:aws:lambda:us-west-2:123456789012:function:handler",
    "*": "arn:aws:lambda:us-east-1:123456789012:function:handler"
  }
}
```

All entries must use the same AWS service. For explicit region keys, match the ARN region to the key; `*` provides a fallback. Choose a fallback consistent with latency/data-residency requirements.

When ARNs are unknown until regional deployment, omit the inline ARN and register later:

```json
{
  "RegionalDestination": {
    "Type": "Custom::ProxylityUdpGatewayDestinationArn",
    "Properties": {
      "ServiceToken": { "Fn::FindInMap": ["ProxylityConfig", { "Ref": "AWS::Region" }, "ServiceToken"] },
      "ApiKey": { "Fn::FindInMap": ["ProxylityConfig", "Account", "ApiKey"] },
      "Destination": { "Ref": "GlobalDestinationName" },
      "IngressRegionKey": { "Ref": "AWS::Region" },
      "Arn": { "Fn::GetAtt": ["RegionalFunction", "Arn"] }
    }
  }
}
```

The actual registration properties are **`Destination`, `IngressRegionKey`, `Arn`**. Do not generate `ListenerId`, `DestinationIndex`, `DestinationArn`, or `Role` on this resource. Obtain the global destination's name from an explicit globally unique name or the listener's `DestinationNames` attribute (select the desired entry).

Deploy global resources/roles before regional registrations; avoid duplicate region registrations. The destination role must authorize the actual regional ARNs. Registration does not create a new IAM role or health-check a function's business logic. Test region failure scenarios; do not promise automatic recovery from application errors.

For shared state, declare DynamoDB Global Table replicas in the owning table's infrastructure workflow. Do not have independent regional stacks compete to own replicas of the same table. Account for replication latency, conflicts, TTL delay, and local reads; reject expired subscription records even before TTL cleanup.

## PacketSource: delayed replies and server push

An SNS-backed PacketSource binds an outbound topic to a listener:

```json
{
  "Type": "Custom::ProxylityUdpGatewayPacketSource",
  "Properties": {
    "ServiceToken": { "Fn::FindInMap": ["ProxylityConfig", { "Ref": "AWS::Region" }, "ServiceToken"] },
    "ApiKey": { "Fn::FindInMap": ["ProxylityConfig", "Account", "ApiKey"] },
    "ListenerName": { "Ref": "UdpListener" },
    "SnsTopicSource": {
      "TopicArn": { "Ref": "OutboundTopic" },
      "Role": { "Fn::GetAtt": ["PacketSourceRole", "Arn"] }
    }
  }
}
```

The topic must be in the **stack's region**. `SnsTopicSource.Role` is a plain role ARN, not `{Arn:...}`; it trusts Proxylity and grants `sns:Subscribe`, `sns:Unsubscribe`, `sns:ListSubscriptionsByTopic`. Publishers separately need `sns:Publish`. Add policy dependencies if needed.

A registration subscribes Proxylity's per-region delivery queues to the topic. You do **not** need a separate PacketSource for every egress region; deploy additional topics/registrations only when regional publishers or other requirements warrant them.

```python
sns.publish(
    TopicArn=topic_arn,
    MessageAttributes={
        "EgressRegion": {"DataType": "String", "StringValue": ingress_region}
    },
    Message=json.dumps({"Messages": [{
        "Remote": {"Address": remote_ip, "Port": remote_port},
        "Formatter": "base64",
        "Data": base64.b64encode(payload).decode("ascii")
    }]})
)
```

`Remote.Address` differs from inbound `Remote.IpAddress`. Missing/nonmatching `EgressRegion` attributes match no queue subscription. Preserve the inbound `IngressRegion` routing context for session-bound replies; do not silently substitute the Lambda region if that field is absent. Confirm its location in the actual event and persist it with subscription state.

WireGuard additionally requires `Remote.PeerKey` and an established session. In decapsulated application-payload mode, provide `Inner` with outbound source/destination addresses/ports. NAT/firewall bindings expire; PacketSource cannot make an unreachable client reachable or establish a peer session on its own.

SNS redrive is a **subscription** policy, not a topic-level DLQ setting. PacketSource subscriptions are service-created; do not promise a generic topic DLQ protects this path. Monitor publishing failures and verify supported subscription redrive configuration before relying on it.

## Observability

- Listener `MetricsEnabled` / `LogGroupName` require a listener `Role.Arn`; it need not have destination delivery permissions.
- Destination switches and role are separate. Neither switch enables the other scope.
- Metrics namespace is exactly **`Proxylity/UDP Gateway`**; each metric has one dimension, `Listener`, `Destination`, or `PacketSource`, using the actual resource name or source identifier, not an ARN or logical ID. PacketSource publishes only `EgressPackets` and `EgressBytes` with dimension `PacketSource=<source_id>`, using the bound listener's `MetricsEnabled` setting and observability role. No separate source role or setting is needed; no ingress, filtered, or error metrics are published for sources. Separate `PSRC` usage records remain available.
- Listener ingress counts all application and protocol datagrams admitted by the firewall while the listener is not suspended, before protocol processing. Firewall-denied and suspended-listener datagrams count only as listener filtered traffic. Invalid transport packets admitted on an active listener remain ingress. Destination BREX rejection does not undo listener ingress.
- Listener egress counts every successfully sent datagram, including application replies, PacketSource deliveries, handshakes, keepalives, WebRTC DATA/control bundles, and retransmissions. Dropped or failed sends do not count. A successful send does not prove client receipt.
- Listener byte counts exclude Proxy Protocol and outer IP/UDP headers but include transport encryption and encapsulation overhead. Destination ingress/filtering currently use the original incoming UDP payload length, while destination/source egress uses application bytes before transport encoding. WebRTC destination/source egress counts once per application reply after an application-bearing datagram is sent, not once per control datagram or retransmission.
- Packet units are `max(1, ceil(recorded byte length / 1024))`: 0, 1024, and 1025 bytes count as 1, 1, and 2 units. A 1024-byte application reply encoded as a 1056-byte datagram is one destination/source egress unit but two listener egress units. Destination ingress means queued, not confirmed AWS delivery; destination `EgressPackets` measures replies, not requests delivered to AWS.
- Listener and destination/source counters overlap, and fan-out records ingress separately at each destination. Never sum scopes as unique traffic or infer delivery-success rates from their ratios. For one listener/period, accounted inbound bytes are `IngressBytes + FilteredBytes`; firewall/suspension rejection fraction is `FilteredBytes / (IngressBytes + FilteredBytes)` for a nonzero denominator. Packet-based fractions are size-weighted, not raw datagram fractions. Consult the [metric definitions](https://proxylity.com/docs/metrics.html) before calculating rates or costs.
- Listener and PacketSource metrics appear in the processing gateway region; destination metrics use the resolved destination ARN region (or gateway region for regionless ARNs). Inspect all relevant regions.
- Delivery-error logs need a pre-created group and stream-write permissions; metric publishing needs `cloudwatch:PutMetricData` with namespace restriction. Logging and metrics are independent.
- Alarm on errors/throttles and application failures, set log retention, and gate sensitive raw packet capture. Size Lambda concurrency against peak traffic; a low cap can itself cause packet loss.
