# Examples Reference — Proxylity UDP Gateway

All examples are in the [proxylity/examples](https://github.com/proxylity/examples) repository. Each example is a fully deployable CloudFormation or SAM template. Use the closest matching example as your starting point — copy and modify rather than building from scratch.

---

## `packet-counter/` — Simplest Lambda (Node.js)

**Use case**: Echo the count of received packets back to each sender. The hello-world of UDP Gateway.

**What it demonstrates:**
- Minimal CloudFormation template structure
- Inline Lambda function (Node.js 22.x)
- `AWS::Serverless::Function` with `InlineCode`
- Counting packets by sender IP and returning a UDP reply
- Standard outputs: `Domain`, `Port`, `Endpoint`

**Key pattern**: The Lambda receives `event.Messages[]`, aggregates by `Remote.IpAddress`, and returns `{ Replies: [...] }`.

**Variants in the repository:**
- `packet-counter/` — Node.js 22.x (simplest)
- `packet-counter-python/` — Python 3.x
- `packet-counter-go/` — Go (requires SAM CLI)
- `packet-counter-sfn/` — Step Functions Express (no Lambda, no cold start)
- `packet-counter-cpp/` — C++ (native runtime)
- `packet-counter-multi-region/` — Multi-region with global + regional stacks

**Start here when:** Building a new integration and needing the simplest possible working template.

---

## `coap-time-service/` — CoAP + Step Functions + Observe

**Use case**: CoAP/WireGuard time service that responds to GET /time requests and supports CoAP Observe subscriptions with server-push notifications.

**What it demonstrates:**
- `"Formatter": "coap"` on the destination (parses CoAP to JSON)
- `"Protocols": ["wg"]` WireGuard listener
- `AWS::Serverless::StateMachine` (Express, JSONata)
- `Custom::ProxylityUdpGatewayPacketSource` for server-initiated UDP delivery (Observe)
- DynamoDB table for subscription registry with TTL
- SNS topic as the PacketSource outbound channel
- CloudWatch logging for state machine executions

**Architecture**: CoAP requests → WireGuard listener → Step Functions Express → DynamoDB (read/write subscriptions) → SNS PacketSource (push time updates to subscribers).

**Key techniques:**
- Step Functions uses JSONata to parse the CoAP `Data` field
- `ObserveTable` stores `ClientEndpoint` + `Token` with TTL expiry
- A scheduled Lambda (`ObserveNotifier`) reads subscriptions from DynamoDB and publishes to SNS

**Start here when:** Building CoAP observe/notify patterns, IoT push services, or Step Functions-based packet processing.

---

## `coap-demo/` — Full CoAP API (Multi-Region)

**Use case**: Production-grade multi-region CoAP API supporting Block-wise transfer (large payloads), Observe, and asynchronous deferred responses.

**What it demonstrates:**
- Global stack + regional stacks pattern
- `Custom::ProxylityUdpGatewayDestinationArn` for per-region registration
- DynamoDB Global Tables for shared state across regions
- C# .NET NativeAOT Lambda (~100ms cold start)
- Block-wise transfer (RFC 7959) implementation
- EventBridge Scheduler for deferred/async responses
- AppSync Events for async browser notifications
- Lambda `AsyncResponder` for deferred reply delivery

**Architecture**: Global listener → regional Lambda handlers → DynamoDB Global Table → AppSync Events WebSocket (for browser clients).

**Start here when:** Building production multi-region CoAP services, needing .NET NativeAOT, or implementing block-wise transfer.

---

## `syslog/` — Enterprise Syslog (WireGuard + Firehose + S3 WORM)

**Use case**: Collect encrypted syslog traffic from network devices, archive to S3 with compliance-grade retention, and forward to CloudWatch Logs for alerting.

**What it demonstrates:**
- WireGuard listener with peer public key as CloudFormation parameter
- Kinesis Firehose destination (NDJSON delivery, buffered to S3)
- S3 with Object Lock (GOVERNANCE mode) for WORM archival
- KMS customer-managed key with auto-rotation
- S3 Lifecycle rules (Glacier transition after N days, expiration after M days)
- CloudWatch Logs destination (parallel delivery to live monitoring)
- CloudWatch Metric Filters for high-severity syslog alerts
- SNS alarm notifications (email subscription)
- No custom Lambda code — pure CloudFormation configuration

**Key parameter**: `PeerPublicKey` — generate with `wg genkey | tee site.key | wg pubkey > site.pub` and provide the contents of `site.pub`.

**Start here when:** Migrating existing syslog infrastructure to serverless, building compliance-grade log archival, or implementing WireGuard-encrypted UDP ingestion without custom code.

---

## `event-bridge/` — EventBridge Fan-out

**Use case**: Route UDP packets to EventBridge default event bus for downstream processing by any number of EventBridge targets.

**What it demonstrates:**
- EventBridge destination with region-keyed `DestinationArn`
- `Custom::ProxylityUdpGatewayDestinationArn` for cross-region routing
- EventBridge Rule with Proxylity source/detail-type filter
- CloudWatch Logs as EventBridge target (for live inspection)
- CloudWatch Logs resource policy for EventBridge access
- `AWS::LanguageExtensions` transform for `Fn::ToJsonString`

**Start here when:** Building event-driven architectures, fan-out to multiple downstream services, or bridging UDP to any EventBridge-compatible integration.

---

## `kinesis-streams/` — Real-Time Streaming Analytics

**Use case**: Write UDP packets to Amazon Kinesis Data Streams for real-time analytics, downstream Lambda consumers, or Kinesis Data Analytics.

**What it demonstrates:**
- Kinesis Data Stream destination
- `PartitionKeyExpression` (BREX) for shard routing
- `PartitionKeyFormatter: hex`
- `ShardCount` as a CloudFormation parameter
- Separate CloudWatch Log Group for destination errors

**Start here when:** Building real-time analytics pipelines, ingesting high-volume telemetry, or integrating with existing Kinesis consumers.

---

## `mavlink-fifo/` — Ordered Per-Device Queue (MAVLink)

**Use case**: Receive MAVLink drone telemetry and deliver to SQS FIFO queue with per-drone message ordering (using the MAVLink system ID as the partition key).

**What it demonstrates:**
- SQS FIFO queue destination
- BREX `MessageGroupIdExpression` (under `Arguments`) extracting bytes from the packet payload
- Multiple destinations on a single listener (standard queue + FIFO queue)
- No custom Lambda code — pure routing configuration
- MAVLink v1/v2 protocol detection via payload byte offsets

**Key insight**: BREX extracts the MAVLink system ID from the packet payload bytes. All messages from the same drone (same system ID) land in the same SQS message group, preserving ordering.

**Start here when:** Building per-device ordered delivery, multi-protocol routing, or any pattern requiring FIFO guarantees without custom code.

---

## `dns-filter/` — DNS Filtering with Anomaly Detection (Multi-Region)

**Use case**: Serverless DNS filter that blocks malicious domains, redirects by ASN, and uses Amazon Bedrock for anomaly detection.

**What it demonstrates:**
- Full multi-region global + regional stack deployment
- C# .NET Lambda for DNS packet parsing and response generation
- EventBridge for anomaly event publishing
- Amazon Bedrock (Claude) integration for ML-based anomaly detection
- DynamoDB for blocklist and ASN redirect rules
- High-performance binary protocol handling with .NET

**Start here when:** Building custom DNS services, serverless security filtering, or multi-region high-performance binary protocol processing.

---

## `radius/` — RADIUS Authentication (Multi-Region)

**Use case**: Enterprise RADIUS authentication/accounting service with DynamoDB user store and Bedrock anomaly detection.

**What it demonstrates:**
- RADIUS protocol (port 1812/1813) over WireGuard
- Full multi-region global + regional stack
- .NET NativeAOT Lambda with RADIUS packet parsing (RFC 2865)
- Step Functions for complex authentication state machine
- DynamoDB for user credentials and session state
- Amazon Bedrock for authentication anomaly detection
- Complete auth + accounting workflow

**Start here when:** Modernizing legacy RADIUS infrastructure, building enterprise authentication services, or needing a reference for complex multi-step stateful UDP protocols.

---

## `packet-capture/` — Live Browser Packet View (AppSync WebSocket)

**Use case**: Capture UDP packets and stream them in real-time to a browser via AppSync Events (WebSocket), with SQS as an observable buffer.

**What it demonstrates:**
- .NET Lambda with `PacketDotNet` for packet parsing
- SQS standard queue as observable buffer
- AWS AppSync Events API for WebSocket push to browsers
- Real-time packet capture without persistent storage
- Browser-facing serverless UDP introspection tool

**Start here when:** Building live monitoring dashboards, real-time packet inspection tools, or WebSocket-based UDP data feeds.

---

## `supabase-udp/` — HTTP REST API Bridge with JWT Rotation

**Use case**: Bridge UDP packets to Supabase (PostgreSQL) via their REST API, with automatic JWT credential rotation.

**What it demonstrates:**
- API Gateway destination with VTL mapping templates
- Bearer token injection via `Authorization` header in VTL
- Step Functions for periodic JWT rotation
- Deno/TypeScript Supabase Edge Functions for packet storage
- `package.json`-based Node.js Lambda for JWT management

**Key technique**: The VTL mapping template injects the current JWT from Parameter Store into the `Authorization` header on every HTTP request to the API Gateway endpoint.

**Start here when:** Bridging UDP to HTTP REST APIs, integrating with third-party services requiring authentication, or building rotating-credential patterns.

---

## `momento-udp/` — Third-Party Cache over UDP

**Use case**: UDP client SDK alternative to gRPC/HTTP for Momento Cache, using .NET NativeAOT Lambda.

**What it demonstrates:**
- .NET 10 NativeAOT Lambda with Momento SDK
- UDP-to-cache proxy pattern
- Custom binary UDP protocol design
- SAM CLI build for NativeAOT compilation

**Start here when:** Building UDP SDKs or proxies for third-party services with gRPC/HTTP APIs.

---

## `wireguard-echo/` — WireGuard Echo + NTP

**Use case**: Single Lambda that handles ICMP ping, UDP echo (port 7), and NTP (port 123) responses inside a WireGuard tunnel.

**What it demonstrates:**
- WireGuard with `DecapsulatedDelivery: true`
- `Inner` metadata field (decapsulated IP headers)
- Multi-protocol routing in a single Lambda based on `Inner.DestinationPort`
- NTP response construction (binary, time-sensitive)
- C# NativeAOT for protocol-level UDP handling

**Start here when:** Implementing multi-protocol UDP services in a single Lambda, using `DecapsulatedDelivery`, or building WireGuard-tunneled service emulation.

---

## `packet-counter-multi-region/` — Multi-Region Counter

**Use case**: The packet-counter example extended to multi-region with global + regional stacks and DynamoDB Global Tables.

**What it demonstrates:**
- Minimal multi-region pattern: global stack + per-region stacks
- DynamoDB Global Table for cross-region aggregate counts
- `Custom::ProxylityUdpGatewayDestinationArn` in regional stacks
- `packet_counter_test.py` — Python test script for load testing

**Start here when:** Learning the multi-region pattern for the first time before tackling `coap-demo/` or `radius/`.

---

## Choosing Between Lambda and Step Functions

| Criteria | Use Lambda | Use Step Functions Express |
|---|---|---|
| Cold start tolerance | Yes (1–3s ok) | No (need < 100ms) |
| Logic complexity | Simple to moderate | Complex branching, retries |
| State machine visual | Not needed | Beneficial |
| Protocol | Any | CoAP, RADIUS, complex stateful |
| Cost at high volume | Cheaper per invocation | Slightly higher base cost |
| .NET NativeAOT needed? | Yes → ~100ms cold start | No cold start at all |

---

## Choosing Between CloudFormation CLI and SAM CLI

| Criteria | AWS CLI (`cloudformation deploy`) | SAM CLI (`sam build && sam deploy`) |
|---|---|---|
| Lambda code | Inline (ZipFile/InlineCode) | Compiled or packaged |
| Runtimes | Node.js, Python (inline) | Any (.NET, Go, Java, Rust) |
| SAM transforms | Optional | Required for compiled Lambdas |
| Template macros | Supported | Same + additional SAM macros |
| Local testing | Not built-in | `sam local invoke` |
