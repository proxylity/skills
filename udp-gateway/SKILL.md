---
name: udp-gateway
description: Build serverless UDP services with Proxylity UDP Gateway on AWS. Use when creating CloudFormation or SAM templates, Lambda or Step Functions handlers, or integrations for UDP-based protocols — including plain UDP, WireGuard, CoAP, syslog, RADIUS, DNS, MAVLink, IoT sensor data, or online gaming backends. Covers all supported destinations (Lambda, Step Functions, EventBridge, SQS, Kinesis, DynamoDB, S3, Firehose, CloudWatch Logs, API Gateway), WireGuard encryption, batching, multi-region deployment, and the UDP packet request/response format.
license: MIT
compatibility: Requires an AWS account subscribed to Proxylity UDP Gateway on AWS Marketplace. AWS CLI required for deployment; SAM CLI required for compiled Lambda runtimes (.NET, Go, Java).
metadata:
  author: proxylity
  version: "1.0"
---

# UDP Gateway Skill

[Proxylity UDP Gateway](https://proxylity.com) is a managed network ingress service that routes UDP packets directly to AWS resources — Lambda, Step Functions, EventBridge, SQS, Kinesis, DynamoDB, S3, Firehose, CloudWatch Logs, API Gateway, and more — without servers, load balancers, or autoscaling groups.

This skill guides you to **design**, **implement**, **deploy**, and **troubleshoot** UDP Gateway solutions with Infrastructure as Code. The [proxylity/examples](https://github.com/proxylity/examples) repository is the canonical source of working templates and handlers; use it as the ground truth for patterns.

## Prerequisites

1. **AWS Marketplace subscription** to [UDP Gateway](https://aws.amazon.com/marketplace/pp/prodview-cpvl5wgt2yo2e) for the target AWS account.
2. **AWS CLI** configured with account credentials.
3. **SAM CLI** — required only for compiled Lambda runtimes (.NET NativeAOT, Go, Java, Rust).

---

## Step 1 — Gather requirements

Identify these before generating any code:

| Requirement | Options / Notes |
|---|---|
| **Protocol** | Plain UDP · WireGuard (encrypted) · CoAP · syslog · DNS · RADIUS · MAVLink · custom binary |
| **Destination** | Lambda · Step Functions · EventBridge · SQS (standard or FIFO) · Kinesis · DynamoDB · S3 · Firehose · CloudWatch Logs · API Gateway |
| **Response required?** | Yes → Lambda/SFn return `Replies`; server-push → SNS PacketSource. No → fire-and-forget. |
| **Latency** | < 100ms cold start → .NET NativeAOT Lambda or Step Functions Express |
| **Client IP restrictions** | Specific CIDR(s) for production; `0.0.0.0/0` for dev only |
| **Single or multi-region?** | Multi-region requires global + regional stack split |
| **WireGuard?** | Requires client public key(s) or `AllowUnknownPeers: true` |
| **Formatter** | `base64` (default binary) · `utf8` · `ascii` · `hex` · `coap` (parses CoAP to JSON) |

---

## Step 2 — Choose a base pattern

| Scenario | Base example in repository |
|---|---|
| Simplest Lambda — count, echo, or process packets | `packet-counter/` (Node.js, Python, or Go variants) |
| CoAP GET/POST with server responses | `coap-time-service/` |
| CoAP observe, block transfer, async replies, multi-region | `coap-demo/` |
| IoT sensor data to DynamoDB | `coap-demo/` or `momento-udp/` |
| Event-driven fan-out to AWS services | `event-bridge/` |
| Real-time streaming analytics | `kinesis-streams/` |
| Enterprise syslog — WireGuard + Firehose + S3 WORM | `syslog/` |
| DNS filtering with anomaly detection | `dns-filter/` |
| RADIUS authentication and accounting | `radius/` |
| Live browser packet view via WebSocket | `packet-capture/` |
| Per-device ordered queue (MAVLink, telemetry) | `mavlink-fifo/` |
| Bridge UDP to HTTP REST API | `supabase-udp/` |
| Step Functions orchestration + complex state | `coap-time-service/` or `radius/` |

See [references/EXAMPLES.md](references/EXAMPLES.md) for detailed descriptions of each example including key techniques and runtime choices.

---

## Step 3 — Build the CloudFormation template

Every template requires these three building blocks.

### 3a. ProxylityConfig Mapping (always required)

```json
"Mappings": {
  "ProxylityConfig": {
    "Fn::Transform": {
      "Name": "AWS::Include",
      "Parameters": {
        "Location": { "Fn::Sub": "s3://proxylity-config-${AWS::Region}/${AWS::AccountId}/customer-config.json" }
      }
    }
  }
}
```

This `AWS::Include` fetches the customer's `ServiceToken`, `ServiceRole`, and `ApiKey` from Proxylity's per-account S3 config bucket at deploy time. **Never hardcode these values.**

### 3b. DestinationRole — IAM role Proxylity assumes to deliver packets

```json
"DestinationRole": {
  "Type": "AWS::IAM::Role",
  "Properties": {
    "AssumeRolePolicyDocument": {
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": { "AWS": { "Fn::FindInMap": ["ProxylityConfig", {"Ref": "AWS::Region"}, "ServiceRole"] } },
        "Action": "sts:AssumeRole"
      }]
    },
    "Policies": [{ "PolicyName": "Allow", "PolicyDocument": { "Version": "2012-10-17", "Statement": [{ ... }] } }]
  }
}
```

The trust principal is always `ProxylityConfig[Region].ServiceRole` from the mapping. See [references/DESTINATIONS.md](references/DESTINATIONS.md) for the exact `Action` and `Resource` for every destination type.

### 3c. UdpListener resource

```json
"UdpListener": {
  "Type": "Custom::ProxylityUdpGatewayListener",
  "Properties": {
    "ServiceToken": { "Fn::FindInMap": ["ProxylityConfig", {"Ref": "AWS::Region"}, "ServiceToken"] },
    "ApiKey":       { "Fn::FindInMap": ["ProxylityConfig", "Account", "ApiKey"] },
    "Protocols": ["udp"],
    "ClientRestrictions": { "Networks": [{ "Ref": "ClientCidrToAllow" }] },
    "Destinations": [{
      "DestinationArn": { "Fn::GetAtt": ["MyFunction", "Arn"] },
      "Role": { "Arn": { "Fn::GetAtt": ["DestinationRole", "Arn"] } },
      "Batching": { "Count": 1000, "TimeoutInSeconds": 1 },
      "MetricsEnabled": true
    }]
  }
}
```

- Use `"Protocols": ["wg"]` for WireGuard-only, `["udp", "wg"]` for both.
- For WireGuard, add `"Peers": [{"PublicKey": "..."}]` and optionally `"DecapsulatedDelivery": true` (strips the WireGuard envelope before delivery).
- Multiple destinations are supported in the `Destinations` list.

### 3d. Standard outputs

```json
"Outputs": {
  "Endpoint": { "Value": { "Fn::Sub": "${UdpListener.Domain}.proxylity.com:${UdpListener.Port}" } },
  "Domain":   { "Value": { "Fn::Sub": "${UdpListener.Domain}.proxylity.com" } },
  "Port":     { "Value": { "Fn::GetAtt": ["UdpListener", "Port"] } }
}
```

For WireGuard listeners, also output `"Fn::GetAtt": ["UdpListener", "WireGuardPublicKey"]`.

A minimal working template is in [assets/starter.template.json](assets/starter.template.json).

---

## Step 4 — Write the packet handler

**Lambda and Step Functions Express** receive a batch envelope:

```json
{
  "Messages": [
    {
      "Tag": "abc123",
      "Remote": { "IpAddress": "1.2.3.4", "Port": 5678 },
      "Local":  { "Domain": "ingress-1", "Port": 15678 },
      "Data": "<payload — base64 by default, decoded string for utf8/ascii>",
      "ReceivedAt": "2024-01-01T00:00:00.000Z"
    }
  ]
}
```

**Return format** — return responses or an empty array:

```json
{ "Replies": [{ "Tag": "abc123", "Data": "<base64-encoded response payload>" }] }
```

Return `{ "Replies": [] }` or `{}` when no response is needed.

**Formatter values** (set per-destination, not per-listener):
- `base64` (default) — `Data` is a base64 string of raw bytes
- `utf8` / `ascii` — `Data` is a decoded text string
- `hex` — `Data` is a hex string
- `coap` — `Data` is a stringified JSON object with parsed CoAP fields

**Other destination formats** (SQS, EventBridge, DynamoDB, S3, Firehose) differ — load [references/PACKET-FORMAT.md](references/PACKET-FORMAT.md) for the full breakdown.

---

## Step 5 — Deploy

**Plain CloudFormation** (inline Lambda, no compiled code):

```bash
aws cloudformation deploy \
  --template-file service.template.json \
  --stack-name my-udp-service \
  --capabilities CAPABILITY_IAM \
  --region us-east-1
```

**SAM CLI** (compiled Lambda — .NET NativeAOT, Go, Java):

```bash
sam build
sam deploy --guided
```

**Retrieve the endpoint** after deploy:

```bash
aws cloudformation describe-stacks \
  --stack-name my-udp-service \
  --query 'Stacks[0].Outputs' \
  --region us-east-1
```

---

## Step 6 — Test

```bash
# Linux / macOS
echo "hello" | nc -u ingress-1.proxylity.com 15678

# PowerShell (Windows)
$c = New-Object System.Net.Sockets.UdpClient
$c.Connect("ingress-1.proxylity.com", 15678)
$b = [Text.Encoding]::ASCII.GetBytes("hello")
$c.Send($b, $b.Length) | Out-Null
$c.Close()
```

Replace the domain and port with the values from the `Endpoint` stack output. Check CloudWatch Logs for your Lambda function to verify receipt.

---

## Constraints — always enforce

1. **`ClientRestrictions` must always be present** on every listener. Omitting it silently blocks **all** traffic. Use `"Networks": ["0.0.0.0/0"]` for open-access dev only.
2. **Never hardcode `ServiceToken`, `ServiceRole`, or `ApiKey`.** Always use `Fn::FindInMap` against the `ProxylityConfig` mapping.
3. **`DestinationRole` must trust Proxylity's `ServiceRole`** (from the mapping), not a hardcoded ARN.
4. **`CAPABILITY_IAM`** is always required for CloudFormation deployment — every template creates IAM roles.
5. **Step Functions: both EXPRESS and STANDARD are supported.** Set `"Type": "EXPRESS"` for request/response (replies supported); `"Type": "STANDARD"` for async workflows (no replies). The destination role must include `states:DescribeStateMachine` — Proxylity uses it to auto-detect the state machine type.
6. **EventBridge `DestinationArn`** may be a plain ARN string (`"arn:aws:events:us-east-1:..."`) or a region-keyed JSON object (`{ "*": "arn:..." }` or `{ "us-east-1": "arn:..." }`). Use a region-keyed map when the listener serves multiple regions.
7. **WireGuard listeners** need either a `Peers` list with at least one public key, or `"AllowUnknownPeers": true`.
8. **IAM least-privilege** — each `DestinationRole` grants only the action(s) needed for that specific destination (e.g., `lambda:InvokeFunction`, `kinesis:PutRecords`).

---

## Gotchas

- **Listener receives no traffic**: `ClientRestrictions` is missing or the client IP is outside the allowed CIDR. Check this first, always.
- **ProxylityConfig include fails at deploy time**: The account must be subscribed on AWS Marketplace *and* the region must be supported. The S3 bucket `proxylity-config-{region}` must be accessible.
- **Lambda cold start timeouts**: Use Step Functions Express (zero cold start) for latency-sensitive protocols (CoAP, RADIUS). Use .NET NativeAOT for ~100ms Lambda cold starts.
- **High latency despite low batch timeout**: Lambda minimum invocation overhead is ~1ms per invocation after warm-up; Step Functions Express adds ~50ms overhead per execution.
- **No reply back to client**: Lambda/SFn must explicitly return `{ "Replies": [...] }`. For server-initiated messages (CoAP Observe, push), use an `SNS PacketSource` — see [references/ARCHITECTURE.md](references/ARCHITECTURE.md).
- **PacketSource `EgressRegion` is required**: Every SNS publish must include an `EgressRegion` message attribute (not in the body — as an SNS message attribute). Messages without it match no subscription filter and are silently discarded. For replies, use the `IngressRegion` from the original inbound packet JSON. PacketSource is a regional resource — deploy one per egress region.
- **FIFO queue ordering**: Requires `Arguments.MessageGroupIdExpression` (BREX syntax) to extract the message group ID from packet bytes (e.g., device ID from the first N bytes). See [references/ARCHITECTURE.md](references/ARCHITECTURE.md).
- **Formatter is per-destination**: The same listener can route to one destination with `"Formatter": "coap"` and another with `"Formatter": "base64"`.
- **Multi-region gotcha**: A single `Custom::ProxylityUdpGatewayListener` is globally anycast. Adding regional processing requires `Custom::ProxylityUdpGatewayDestinationArn` resources deployed per region. See [references/ARCHITECTURE.md](references/ARCHITECTURE.md).
- **SAM Transform required** (`"Transform": "AWS::Serverless-2016-10-31"`) for `AWS::Serverless::Function`, `AWS::Serverless::StateMachine`, `Fn::ForEach`, and other SAM macros.
- **Stack deletion removes the listener**: Deleting the CloudFormation stack calls the Proxylity custom resource handler, which deregisters the listener and releases the port assignment.

---

## Reference files

Load these on demand — only when the task requires the detail they contain:

| File | Load when… |
|---|---|
| [references/ARCHITECTURE.md](references/ARCHITECTURE.md) | Multi-region stacks, BREX partition keys, composite destinations, WireGuard peers, PacketSource, batching tuning |
| [references/PACKET-FORMAT.md](references/PACKET-FORMAT.md) | Full request/response JSON schemas, per-service format differences (SQS, EventBridge, DynamoDB, S3, Firehose) |
| [references/DESTINATIONS.md](references/DESTINATIONS.md) | IAM policy statements, DestinationArn syntax, and configuration options per destination type |
| [references/EXAMPLES.md](references/EXAMPLES.md) | Detailed walkthrough of every example in the repository — use cases, runtime choices, key techniques |
| [assets/starter.template.json](assets/starter.template.json) | Minimal working CloudFormation template — use as a starting point, not as-is |
