---
name: udp-gateway
description: "Design, implement, deploy, test, and troubleshoot Proxylity UDP Gateway services on AWS. Use for UDP, WireGuard, DTLS, CoAP, binary protocols, CloudFormation/SAM listeners, Lambda handlers and SDK templates, Step Functions, PacketSource server push, BREX filtering/routing, batching, multi-region destinations, IoT Core, Location trackers, and CloudWatch observability. Also covers Lambda async invocation, response streaming, tenant isolation, and availability checks for WebRTC data channels."
license: MIT
compatibility: "Requires a Proxylity-enabled AWS account and AWS credentials for deployment. AWS CLI deploys packaged CloudFormation/SAM templates; SAM CLI is optional build/deploy tooling. Compiled handlers require their language toolchain; NativeAOT requires a compatible Linux build environment."
metadata:
  author: proxylity
  version: "2.0"
---

# Proxylity UDP Gateway

Build event-driven datagram services without operating UDP listener servers. This skill covers infrastructure, packet processing, replies, and operational validation.

## Start here: establish the contract

1. Inspect the user's existing template, handler, target runtime, package versions, and deployment region before generating replacements.
2. Use the [source and verification notes](./references/SOURCES.md) when checking capabilities. Prefer current implementation validators and SDK types for exact names; documentation and examples can lag. Do not treat example claims, local source, or an old schema as proof that a feature is deployed in the user's account.
3. Load only the references needed for the task:

| Reference | Load for |
|---|---|
| [Handlers](./references/HANDLERS.md) | Node.js, Python, Go, .NET SDK 2.x, NativeAOT, streaming, Step Functions |
| [Packet format](./references/PACKET-FORMAT.md) | Formatter-aware request/reply encoding, CoAP, tunnel metadata, destination envelopes |
| [Destinations](./references/DESTINATIONS.md) | Resource ARNs, least-privilege IAM, service-specific `Arguments` |
| [Architecture](./references/ARCHITECTURE.md) | WireGuard/DTLS/WebRTC, BREX filters, batching, regional registration, PacketSource, metrics |
| [Examples](./references/EXAMPLES.md) | Selecting and adapting an existing solution |
| [Starter template](./assets/starter.template.json) | Complete, single-region, base64 UDP echo with bounded log retention |

## 1. Gather requirements

Clarify missing decisions that affect the architecture:

| Decision | What to establish |
|---|---|
| Transport | Exactly one of `udp`, `wg`, `dtls`, or availability-verified `webrtc` per listener |
| Protocol | Binary layout, byte order, maximum datagram size, version, authentication, retries, duplicate handling |
| Response | Synchronous replies, streaming replies during execution, delayed/server-initiated push, or no reply |
| Destination | Lambda, Step Functions, API Gateway, SNS, SQS, Kinesis, Firehose, DynamoDB, S3, Logs, IoT Data, Location tracker |
| Performance | Measured latency budget, expected packet/byte rate, burst rate, and acceptable loss |
| Access | Actual public source CIDRs, peer keys or PSKs, and whether a public endpoint is intentional |
| Regions | Single compute region or regional processing, shared-state consistency, egress/session affinity |
| Data handling | Formatter, payload sensitivity, log retention, encryption, and cost budget |

UDP does not guarantee delivery, order, uniqueness, or peer identity. Downstream FIFO queues cannot restore packets lost or reordered before enqueueing. Use protocol sequence IDs, idempotency, bounded retries, and acknowledgments where required. Do not use an IP address, BREX-extracted device ID, or Lambda tenant ID as authentication.

Existing UDP protocols are a good fit; protocols such as QUIC, RTP, or DTLS passed through plain UDP still need their own session state and protocol implementation. CoAP formatting does not implement application Observe state, retransmission policy, or block-wise transfers for you. Browsers cannot use arbitrary UDP sockets; use HTTP/WebSocket or a verified WebRTC integration, not raw UDP.

## 2. Choose a processing model

- **No custom processing:** use a direct destination and BREX extraction/filtering where supported.
- **Request/response:** synchronous Lambda, Step Functions **Express**, or an API Gateway POST endpoint returning `Replies`.
- **Incremental replies:** Lambda `Arguments.UseResponseStreaming: true`, with a streaming-capable handler and the correct JSON stream contract.
- **Background work:** Lambda `Arguments.UseAsyncInvoke: true` or Step Functions **Standard**. Return values do not send replies; use PacketSource for later delivery.
- **Server push:** SNS-backed PacketSource with explicit remote addressing, formatter, and an `EgressRegion` message attribute.
- **Encrypted native clients:** choose WireGuard for IP tunneling or DTLS for clients that speak DTLS. Neither is universally faster or a substitute for the other's protocol.

Streaming and async Lambda invocation are mutually exclusive. Tenant isolation is a separate Lambda feature and requires a tenant-enabled function plus a valid static or BREX-derived tenant identifier.

Prefer existing patterns from the [examples index](./references/EXAMPLES.md), but verify their package versions, IAM policies, and protocol assumptions before copying.

## 3. Build infrastructure

Start from the bundled [starter](./assets/starter.template.json) for base64 UDP echo. Require the user to supply their client CIDR; there is deliberately no public-access default.

### Customer configuration

Include the account-specific configuration at deployment time:

```json
{
  "Mappings": {
    "ProxylityConfig": {
      "Fn::Transform": {
        "Name": "AWS::Include",
        "Parameters": {
          "Location": {
            "Fn::Sub": "s3://proxylity-config-${AWS::Region}/${AWS::AccountId}/customer-config.json"
          }
        }
      }
    }
  }
}
```

Use `Fn::FindInMap` to resolve:

- `["ProxylityConfig", {"Ref": "AWS::Region"}, "ServiceToken"]`
- `["ProxylityConfig", {"Ref": "AWS::Region"}, "ServiceRole"]`
- `["ProxylityConfig", "Account", "ApiKey"]`

Never copy customer credentials or private keys into generated source, logs, or outputs. The destination role trusts the configured Proxylity `ServiceRole`, not `lambda.amazonaws.com`; the Lambda execution role is separate.

### Listener and destination invariants

- `Type: Custom::ProxylityUdpGatewayListener` with `ServiceToken`, `ApiKey`, and **one** protocol in `Protocols`. Do not generate `["udp", "wg"]`.
- Set `ClientRestrictions.Networks` to an array of allowed **outer client** CIDRs. Missing restrictions allow no traffic. A WireGuard inner address is not the client's public source address.
- Each destination uses `Role: { "Arn": ... }`; do not use `RoleArn`.
- Put service-specific settings under destination `Arguments`, not at destination top level.
- Set the destination `Formatter` explicitly. Raw/binary processing should start with `base64`.
- Resolve exact destination delivery actions and ARN scopes from the [destination reference](./references/DESTINATIONS.md).
- Enable delivery error logs with a pre-created log group and stream-write permissions. Configure retention and avoid logging sensitive payloads.
- Use `MetricsEnabled` deliberately: custom metric charges apply and the corresponding role needs `cloudwatch:PutMetricData`.
- Add IAM policy dependencies where permissions are attached using separate resources. Do not let a listener become active before its destination is usable.
- `AWS::Serverless::*` resources require `AWS::Serverless-2016-10-31`; `Fn::ForEach` and `Fn::ToJsonString` require **`AWS::LanguageExtensions`**, not the SAM transform alone.

Outputs normally use `${UdpListener.Domain}.proxylity.com` and `${UdpListener.Port}`. Add `WireGuardPublicKey` or `DtlsServerCertificate` only for the matching transport. Avoid exposing PSKs or WebRTC signaling bearer tokens in broadly visible outputs.

## 4. Implement and validate the packet contract

Synchronous destinations receive a batch:

```json
{
  "Messages": [{
    "Tag": "opaque-correlation-tag",
    "Remote": { "IpAddress": "203.0.113.10", "Port": 45678 },
    "Local": { "Domain": "ingress-1", "Port": 15678 },
    "Formatter": "base64",
    "Data": "aGVsbG8="
  }]
}
```

For a **base64** destination, an echo reply is:

```json
{
  "Replies": [{
    "Tag": "opaque-correlation-tag",
    "Data": "aGVsbG8="
  }]
}
```

Preserve each request's opaque `Tag`. Return `{"Replies":[]}` for no reply, including empty batches. **Reply `Data` follows the destination formatter; it is not always base64.** CoAP replies are stringified CoAP JSON, not base64 JSON. See the [packet contract](./references/PACKET-FORMAT.md) before generating code.

For .NET, prefer current `Proxylity.Templates` async templates and the SDK's `UdpGatewayMessage`, `UdpGatewayReply`, `UdpGatewayBatchRequest`, and `UdpGatewayBatchProcessor`. SDK 2.x uses `message.Reply(bytes)` / `message.NoReply()`; do not invent `ProxylityLambdaRequest`, `ResponsePacket`, or a `HandleBatchAsync` API. SDK `message.Data` is already decoded bytes; it is not a base64 string. Its byte decoder does not support the `coap` formatter; use the raw JSON contract for that case.

## 5. Build and deploy

Use the project's existing build/package workflow. SAM CLI is convenient, **not mandatory for compiled languages**; AWS CLI or CI can deploy artifacts built by language-specific tooling. Inline Node.js/Python can be deployed without a build.

For the starter, after template validation:

```bash
aws cloudformation deploy \
  --template-file udp-gateway/assets/starter.template.json \
  --stack-name my-udp-service \
  --parameter-overrides ClientCidrToAllow=203.0.113.10/32 \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
  --region us-east-1
```

Replace the example CIDR with the client's real public address. `CAPABILITY_AUTO_EXPAND` acknowledges macros/transforms for direct stack deployment; `CAPABILITY_NAMED_IAM` replaces `CAPABILITY_IAM` when explicitly naming IAM resources.

For a packaged SAM application:

```bash
sam validate --lint --template-file template.yaml
sam build --template-file template.yaml
sam deploy --guided
```

NativeAOT must target the Lambda Linux architecture and use the template's source-generated serializer/bootstrap. A serializer assembly attribute alone does not make a function NativeAOT-compatible.

Do not deploy, publish test traffic, or rotate/delete production resources without the user's authorization. Inspect change sets and regional registrations first. Stack deletion releases listener resources and can change endpoint allocations on recreation.

## 6. Test the actual outcome

Before deployment, check:

- Empty and multi-message batches; distinct `Tag` values; binary/non-ASCII payloads; malformed inputs; formatter-specific replies.
- Valid ASL expressions and output shape; a passing JSON parser is not ASL validation.
- IAM trust plus delivery, logging, metrics, and KMS permissions where applicable.
- Real protocol messages, not just an arbitrary text datagram; test tunnel addressing and session affinity separately.

For a deployed base64 echo, use the returned domain/port and keep the same socket open to receive:

```powershell
$client = [System.Net.Sockets.UdpClient]::new()
try {
    $client.Client.ReceiveTimeout = 5000
    $client.Connect("REPLACE-WITH-STACK-DOMAIN", 15678)
    $payload = [Text.Encoding]::UTF8.GetBytes("hello")
    [void]$client.Send($payload, $payload.Length)
    $remote = [System.Net.IPEndPoint]::new([System.Net.IPAddress]::Any, 0)
    $reply = $client.Receive([ref]$remote)
    if ([Convert]::ToBase64String($reply) -ne [Convert]::ToBase64String($payload)) {
        throw "Echo payload mismatch"
    }
} finally {
    $client.Dispose()
}
```

A successful send alone proves neither delivery nor a working reply. Report what was actually validated and what still requires a subscribed AWS account/live client.

## 7. Operate and troubleshoot

1. **No ingress:** check account/region availability, endpoint, outer source CIDR, transport handshake, certificate/peer configuration, and `FilterExpression`.
2. **Ingress but no delivery:** check ARN mapping/registration, role trust, action/resource/KMS permissions, throttling, destination error logs, and service payload quotas.
3. **Delivery but no reply:** check sync vs async mode, exact `Tag`, formatter, valid response framing, tunnel addressing, NAT state, and client receive timeout.
4. **PacketSource no delivery:** check `Remote.Address` (not inbound `IpAddress`), `EgressRegion` as an SNS attribute, active tunnel/session, and required `PeerKey`/`Inner`.
5. **Latency/cost:** measure batching delay, cold/warm runtime behavior, backend execution, cross-region routing, and packet sizes. Do not promise fixed cold-start times, latency floors, automatic application-health failover, or a fixed cost-reduction multiplier.

Listener and destination metrics are independent, not roll-ups. Inspect the proper scope and region, application errors, and delivery logs together. Synchronous Lambda errors, async retries, and downstream queue redrive have different semantics; configure and test each applicable failure path.
