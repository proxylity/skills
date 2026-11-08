# Selecting an example

Use [proxylity/examples](https://github.com/proxylity/examples) as implementation patterns, not an unconditional production-readiness or latest-version guarantee. Read each selected example's README, template, actual handler, and dependency manifest together.

## Pattern index

Paths are relative to that repository. Verify the selected revision before copying.

| Directory | Useful starting point | Check before adopting |
|---|---|---|
| `packet-counter` | Minimal inline Node Lambda and correlated replies | Counts are per batch, not durable totals; aggregation by IP can merge clients behind NAT |
| `packet-counter-python` | Python variant | Runtime support and formatter |
| `packet-counter-go` | Compiled Go handler | Linux architecture, bootstrap packaging/build metadata |
| `packet-counter-cpp` | Native C++ handler | Toolchain and Lambda runtime packaging |
| `lambda-microvm` | Lambda MicroVM image destination: SAM `AWS::Serverless::MicrovmImage`, Node.js HTTP app on port 8080, `/ready` and `/run` hooks, per-tenant MicroVMs | MicroVM availability in the region, destination role grants, first packets dropped while the MicroVM starts, idle suspend/resume latency |
| `packet-counter-sfn` | Express processing without Lambda | ASL/JSONata validity and empty/single/multi-item output shape |
| `packet-counter-multi-region` | Global/regional split | Destination names/registration properties and state ownership |
| `coap-time-service` | CoAP formatting, Express workflow, Observe, PacketSource | Numeric CoAP types, current object-valued `Data` contract, subscription expiry, ingress-region persistence |
| `coap-demo` | More extensive CoAP, block-wise/Observe/deferred response patterns | Application state/retry semantics; not automatic gateway block-wise support |
| `wireguard-echo` | Raw inner-IP ICMP/UDP service implementation | `DecapsulatedHandler`, complete IP replies/checksums, old SDK package pins |
| `wireguard-iot-device` | WireGuard-connected device/application integration | Client firmware, keys, outer CIDR vs inner address |
| `webrtc` | WebRTC data-channel binary echo | Deployed availability, exact signaling contract, channel/size restrictions |
| `event-bridge` | Event bus routing and downstream fan-out | Event source/detail-type, resource policies, transforms |
| `sqs` | Queue integration | Envelope mode, FIFO/fair grouping, deduplication, redrive |
| `kinesis-streams` | Stream ingestion and partition extraction | `PartitionKeyExpressionFormatter`, skew, record quotas |
| `location-service` | Direct binary telemetry to Location trackers | Signed coordinate units, explicit scaling, `TimeUnit` validator discrepancy |
| `mavlink` | Binary telemetry filtering and BREX routing | MAVLink version/offsets and truncated-packet fixtures |
| `syslog` | Encrypted logging, Firehose/S3, Logs | Choose `syslog` for parsed JSON fields or `utf8` for text; handle `parse_ok: false`, retention/Object Lock, privacy, KMS/IAM, size limits |
| `dns-filter` | DNS parsing and multi-region application logic | DNS semantics, timeouts, state consistency, dependencies |
| `radius` | RADIUS application/tunnel patterns | Authentication, secrets, protocol integrity, old SDK package pins |
| `packet-capture` | Live packet display with browser-facing components | Redact payloads, restrict capture access, explicitly disable after debugging |
| `udp-to-http` / `supabase-udp` | API Gateway/HTTP integration | POST endpoint, REST VTL vs HTTP API support, tag-preserving response mappings, secret rotation |
| `momento-udp` | UDP proxy to a cache SDK | Single-datagram sizing, dependency/runtime versions, credentials |
| `iperf2` | Throughput-oriented protocol workload | Application-specific streaming, load authorization, measurements rather than assumed throughput |
| `multi-modal` / `blink` | Additional application/device patterns | Read actual transport and infrastructure; do not infer capabilities from names |

There is no `mavlink-fifo` directory in the checked revision: use `mavlink` and `sqs`. A `dtls` directory is not required to use DTLS; some examples expose transport parameters. Do not fabricate filenames or assume each example implements every transport.

Older CoAP examples may stringify `Data` or describe content decoding under `coap`. Adapt them to the [current packet contract](./PACKET-FORMAT.md): protocol-aware `Data` is an object; `coap` keeps base64 payloads, and `coap+` decodes recognized Content-Formats. For CDK apps, use the [published constructs](./CDK.md) rather than manually translating every sample custom resource.

For new CoAP applications, begin with the [CoAP design guide](./COAP.md) and its bounded, read-only `coap+` example. Extend to Observe/deferred/block-transfer patterns only after designing their state, authentication, and failure handling.

## Current .NET scaffolding

Prefer [Proxylity.Templates](https://github.com/proxylity/templates-net) for new SDK handlers:

| Template short name | Handler model |
|---|---|
| `proxylity-udp` | Synchronous UDP |
| `proxylity-udp-aot` | Synchronous UDP, NativeAOT |
| `proxylity-udp-async` | Async per-message UDP |
| `proxylity-udp-async-aot` | Async per-message UDP, NativeAOT |
| `proxylity-wg-async` | Raw inner-IP tunnel protocol dispatch |
| `proxylity-wg-async-aot` | Same with NativeAOT bootstrap |

The checked template source targets .NET 10 / SDK 2.0.0. Verify published template/package versions before installation. SDK 1.x examples can use incompatible handler return types; adapt to `UdpGatewayReply` and `Reply` / `NoReply` rather than mixing APIs.

## Adaptation checklist

1. State the transport, formatter, event envelope, and response mode.
2. Resolve exact API/property/type names from current implementation and installed packages.
3. Replace permissive access, sample secrets, globally conflicting names, stale runtime/package versions, and unnecessary wildcard IAM.
4. Match function architecture and build output; use the project's existing packaging mechanism. SAM is optional tooling, not a compiled-language requirement.
5. Test real protocol fixtures, empty/multi-message batches, malformed/truncated input, response encoding, and failure paths.
6. Validate infrastructure and ASL before deployment; record account/region-specific limitations.
7. Measure actual latency/throughput/cost. No example establishes a universal NativeAOT cold-start time, Express execution overhead, or production SLA.
