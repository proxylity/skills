# Architecture Reference — Proxylity UDP Gateway

## Multi-Region Deployment

A single `Custom::ProxylityUdpGatewayListener` creates a globally anycast endpoint. Proxylity's infrastructure automatically routes each incoming UDP packet to the nearest healthy AWS region.

The `Listener` and `Destination` resources belong in the global stack. How `DestinationArn` is provided depends on when the ARNs are known:

- **ARNs known ahead of time** — include a region-keyed `DestinationArn` map directly on the `Destination` in the global template. This is useful when targeting existing resources (S3 buckets, pre-deployed queues, etc.).
- **ARNs not yet known** — omit `DestinationArn` from the global `Destination` and deploy `Custom::ProxylityUdpGatewayDestinationArn` in each regional stack. Each regional resource registers its ARN automatically when the regional stack is deployed. This is the common pattern when the global stack must be deployed first to establish shared resources (IAM roles, DynamoDB tables, etc.) that regional stacks depend on.

### Global stack — with known ARNs (deploy once, any region)

Include `DestinationArn` as a region-keyed map when the target ARNs are already known:

```json
"UdpListener": {
  "Type": "Custom::ProxylityUdpGatewayListener",
  "Properties": {
    "ServiceToken": { "Fn::FindInMap": ["ProxylityConfig", {"Ref": "AWS::Region"}, "ServiceToken"] },
    "ApiKey":       { "Fn::FindInMap": ["ProxylityConfig", "Account", "ApiKey"] },
    "Protocols": ["udp"],
    "ClientRestrictions": { "Networks": [{ "Ref": "ClientCidrToAllow" }] },
    "Destinations": [{
      "DestinationArn": {
        "us-east-1": "arn:aws:lambda:us-east-1:123456789012:function:handler",
        "us-west-2": "arn:aws:lambda:us-west-2:123456789012:function:handler",
        "eu-west-1": "arn:aws:lambda:eu-west-1:123456789012:function:handler"
      },
      "Role": { "Arn": { "Fn::GetAtt": ["DestinationRole", "Arn"] } },
      "Batching": { "Count": 1000, "TimeoutInSeconds": 1 }
    }]
  }
}
```

Use `"*"` as a fallback key for any region not explicitly listed.

### Global stack — without ARNs (deploy before regional stacks)

Omit `DestinationArn` when regional ARNs aren't yet known. Regional stacks will register their ARNs after deployment:

```json
"UdpListener": {
  "Type": "Custom::ProxylityUdpGatewayListener",
  "Properties": {
    "ServiceToken": { "Fn::FindInMap": ["ProxylityConfig", {"Ref": "AWS::Region"}, "ServiceToken"] },
    "ApiKey":       { "Fn::FindInMap": ["ProxylityConfig", "Account", "ApiKey"] },
    "Protocols": ["udp"],
    "ClientRestrictions": { "Networks": [{ "Ref": "ClientCidrToAllow" }] },
    "Destinations": [{
      "Role": { "Arn": { "Fn::GetAtt": ["DestinationRole", "Arn"] } },
      "Batching": { "Count": 1000, "TimeoutInSeconds": 1 }
    }]
  }
}
```

### Regional stack (deploy per target region)

Deploys regional resources and registers the ARN with the global listener via `DestinationIndex` (zero-based index into the `Destinations` array):

```json
"RegionalDestination": {
  "Type": "Custom::ProxylityUdpGatewayDestinationArn",
  "Properties": {
    "ServiceToken": { "Fn::FindInMap": ["ProxylityConfig", {"Ref": "AWS::Region"}, "ServiceToken"] },
    "ApiKey":       { "Fn::FindInMap": ["ProxylityConfig", "Account", "ApiKey"] },
    "ListenerId":   { "Ref": "GlobalListenerIdParameter" },
    "DestinationIndex": 0,
    "DestinationArn": { "Fn::GetAtt": ["RegionalFunction", "Arn"] },
    "Role": { "Arn": { "Fn::GetAtt": ["RegionalDestinationRole", "Arn"] } }
  }
}
```

### Mixing models (advanced)

A single listener can have destinations using both approaches — for example, one `Destination` with a `DestinationArn` targeting a pre-existing archive bucket (known ahead of time) and another `Destination` without `DestinationArn` that is populated by regional Lambda ARNs via regional stacks. Each `Custom::ProxylityUdpGatewayDestinationArn` targets the correct destination by its `DestinationIndex`.

See `coap-demo/`, `dns-filter/`, and `radius/` in the examples repository for complete global + regional stack implementations.

### DynamoDB Global Tables for shared state

When regional functions need shared state, use DynamoDB Global Tables. Deploy the table in the global stack with `BillingMode: PAY_PER_REQUEST` and `StreamSpecification` enabled. Add replicas in the regional stacks. Each region reads/writes its local replica; DynamoDB replicates asynchronously.

---

## BREX — Binary Range Expressions

BREX (Binary Range Expressions) extracts values from raw packet bytes without custom Lambda code. Used for `Arguments.MessageGroupIdExpression` on SQS FIFO destinations and `Arguments.PartitionKeyExpression` on Kinesis destinations.

### Syntax

```
[start:end]
```

Selects bytes from index `start` (inclusive) to `end` (exclusive), zero-indexed.

Examples:
- `[0:4]` — first 4 bytes
- `[4:8]` — bytes 4–7
- `[2:6]` — bytes 2–5

### Key Formatters

Applied after extraction to convert bytes to a string. Set via `Arguments.MessageGroupIdFormatter` (SQS FIFO) or `Arguments.PartitionKeyExpressionFormatter` (Kinesis):

| Value | Description |
|---|---|
| `hex` | Convert bytes to lowercase hex string |
| `base64` | Convert bytes to base64 string |
| `utf8` | Interpret bytes as UTF-8 text |

### Example — Per-device ordering on SQS FIFO

Extract the first 4 bytes of each packet as the device ID, convert to hex, use as the FIFO message group ID:

```json
"Destinations": [{
  "DestinationArn": { "Fn::GetAtt": ["DeviceQueue", "Arn"] },
  "Role": { "Arn": { "Fn::GetAtt": ["DestinationRole", "Arn"] } },
  "Arguments": {
    "MessageGroupIdExpression": "[0:4]",
    "MessageGroupIdFormatter": "hex"
  }
}]
```

Messages from the same device (same first 4 bytes) land in the same SQS FIFO message group, ensuring ordered delivery. See `mavlink-fifo/` for a complete example.

---

## Composite Destinations (Multiple Destinations per Listener)

A single listener can route to multiple destinations simultaneously. Each destination in the list receives every packet independently.

```json
"Destinations": [
  {
    "Description": "Real-time processing",
    "DestinationArn": { "Fn::GetAtt": ["ProcessingLambda", "Arn"] },
    "Role": { "Arn": { "Fn::GetAtt": ["LambdaRole", "Arn"] } },
    "Batching": { "Count": 10, "TimeoutInSeconds": 0.1 }
  },
  {
    "Description": "Archive to Firehose",
    "DestinationArn": { "Fn::GetAtt": ["ArchiveFirehose", "Arn"] },
    "Role": { "Arn": { "Fn::GetAtt": ["FirehoseRole", "Arn"] } },
    "Batching": { "Count": 1000, "TimeoutInSeconds": 60 }
  }
]
```

Each destination has its own independent batching settings and formatter. Use this for fan-out, audit logging, or parallel processing pipelines.

---

## WireGuard Configuration

WireGuard provides encrypted UDP tunneling. The listener terminates the WireGuard tunnel and delivers the inner payload to destinations.

### Listener with known peers

```json
"UdpListener": {
  "Type": "Custom::ProxylityUdpGatewayListener",
  "Properties": {
    "ServiceToken": "...",
    "ApiKey": "...",
    "Protocols": ["wg"],
    "Peers": [
      { "PublicKey": "<base64-encoded client public key>", "Description": "Site 1" },
      { "PublicKey": "<base64-encoded client public key>", "Description": "Site 2" }
    ],
    "DecapsulatedDelivery": true,
    "ClientRestrictions": { "Networks": ["10.0.0.0/8"] },
    "Destinations": [...]
  }
}
```

- `WireGuardPublicKey` return value: the server's public key to configure in the client's WireGuard config.
- `DecapsulatedDelivery: true`: strips WireGuard headers; Lambda receives the inner UDP payload identically to a plain UDP listener. The `Inner` field in the packet JSON provides the inner IP/port metadata.
- Without `DecapsulatedDelivery`, Lambda receives the outer WireGuard UDP packet.

### Open WireGuard (public endpoint)

```json
"AllowUnknownPeers": true,
"UnknownPeerPreSharedKey": "<base64-encoded 32-byte PSK>"
```

Any client with a WireGuard keypair can connect. Optionally add a pre-shared key as a second authentication layer.

### Generate client keypair

```bash
wg genkey | tee private.key | wg pubkey > public.key
```

Provide `public.key` content as the `PublicKey` in the `Peers` list or as a CloudFormation parameter.

### Client wg configuration

```ini
[Interface]
PrivateKey = <client private key>
Address = 10.0.0.2/32

[Peer]
PublicKey = <server WireGuard public key from UdpListener.WireGuardPublicKey>
Endpoint = ingress-1.proxylity.com:<port>
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```

---

## Batching Configuration

Batching controls how Proxylity groups packets before invoking your destination.

| Property | Description | Default |
|---|---|---|
| `Count` | Maximum packets per invocation | 1 |
| `TimeoutInSeconds` | Maximum wait time before flush | 1 |

A batch is dispatched when either limit is reached, whichever comes first.

**Tuning guidance:**

| Pattern | Count | TimeoutInSeconds | Rationale |
|---|---|---|---|
| Low-latency (CoAP, RADIUS, echo) | 1–10 | 0.05–0.5 | Minimize round-trip |
| Standard IoT / telemetry | 100–1000 | 0.5–1 | Balance cost and latency |
| High-volume archival (syslog, logs) | 1000 | 5–60 | Maximize efficiency |
| SQS FIFO | 10 | 0.5 | Ordered delivery per group |
| Kinesis | 500 | 1 | Match shard throughput |

Reduce Lambda costs by increasing `Count` — fewer invocations = fewer charges. Reduce latency by decreasing both values.

---

## PacketSource — Server-Initiated Delivery

`Custom::ProxylityUdpGatewayPacketSource` lets your application push UDP packets to connected clients without waiting for an inbound request. Used for CoAP Observe notifications, server-push gaming updates, and any publish/subscribe pattern.

A PacketSource is a **regional resource** — deploy one per AWS region where you need egress capability. The SNS topic must be in the same region as the PacketSource stack. Packets egress through that region's Proxylity infrastructure, directed by the `EgressRegion` SNS message attribute on each publish.

```json
"PacketSource": {
  "Type": "Custom::ProxylityUdpGatewayPacketSource",
  "Properties": {
    "ServiceToken": { "Fn::FindInMap": ["ProxylityConfig", {"Ref": "AWS::Region"}, "ServiceToken"] },
    "ApiKey":       { "Fn::FindInMap": ["ProxylityConfig", "Account", "ApiKey"] },
    "ListenerName": { "Ref": "UdpListener" },
    "SnsTopicSource": {
      "TopicArn": { "Ref": "OutboundTopic" },
      "Role":     { "Fn::GetAtt": ["PacketSourceRole", "Arn"] }
    }
  }
}
```

`SnsTopicSource.Role` is an IAM role that Proxylity assumes to subscribe its delivery queues to the topic. Its policy must grant `sns:Subscribe`, `sns:Unsubscribe`, and `sns:ListSubscriptionsByTopic` on the topic resource. Use `DependsOn` on the PacketSource resource to ensure the policy is attached before CloudFormation attempts to create it.

### SNS message format

Publish a JSON object with a `Messages` array to the SNS topic. Each entry is one UDP packet:

```json
{
  "Messages": [{
    "Remote": { "Address": "1.2.3.4", "Port": 5678 },
    "Data": "<base64-encoded payload>"
  }]
}
```

### EgressRegion — required message attribute

Every SNS publish **must** include an `EgressRegion` message attribute. Proxylity subscribes one delivery queue per supported region, each filtered on this attribute. A publish without a matching `EgressRegion` attribute is silently discarded — no packet is delivered.

```python
sns.publish(
    TopicArn="...",
    MessageAttributes={
        "EgressRegion": {"DataType": "String", "StringValue": "us-east-1"}
    },
    Message=json.dumps({"Messages": [...]})
)
```

For replies to inbound packets, set `EgressRegion` to the `IngressRegion` field from the original packet JSON envelope — this ensures the reply exits from the same region the client's traffic entered, which is required for WireGuard session compatibility.

For proactive pushes not triggered by an inbound packet, choose the region nearest to the target clients.

### WireGuard listeners

For WireGuard listeners, also set `Remote.PeerKey` to the peer's base64-encoded WireGuard public key. For listeners with `DecapsulatedDelivery: true`, include an `Inner` block with inner IP/port addressing.

See `coap-time-service/` and `coap-demo/` in the examples repository for complete observe + notify implementations.

---

## Destination Error Logging

Add a `LogGroupArn` to a destination to capture delivery errors separately from application logs:

```json
"Destinations": [{
  "DestinationArn": "...",
  "Role": { "Arn": "..." },
  "LogGroupName": { "Ref": "DestinationErrorLogs" },
  "MetricsEnabled": true
}]
```

The destination role must grant `logs:CreateLogStream` and `logs:PutLogEvents` on the log group. This is strongly recommended for production deployments to distinguish Proxylity delivery failures from Lambda execution errors.
