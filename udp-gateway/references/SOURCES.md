# Sources and verification

Reviewed against local source on **2026-10-14**. These are source snapshots, not a claim that every feature is deployed or every referenced package has been published.

| Source | Checked revision | Evidence |
|---|---|---|
| [Control plane](https://github.com/proxylity/proxylity-control) | `2855898` | `ListenerRequestValidator`, `DestinationArnRequestValidator`, listener outputs, PacketSource subscription filters |
| [Documentation source](https://github.com/proxylity/proxylity-frontend) | `31faaa1` | Destination/formatter contracts, metrics, DTLS, PacketSource |
| [.NET Lambda SDK](https://github.com/proxylity/lambda-sdk-net) | `077aa7e` | SDK 2.x reply methods, byte decoding, serializer, batch processing, raw-IP dispatch |
| [.NET templates](https://github.com/proxylity/templates-net) | `0b5ea7c` | Template names, .NET 10, SDK 2.0.0 references, AOT bootstrap |
| [Examples](https://github.com/proxylity/examples) | `4004309` | Existing directory names, CoAP JSON replies, application/tunnel patterns |
| [BREX library](https://github.com/proxylity/brex-lib-net) | `78de87e` | Slice semantics, typed reads, comparison/filter expressions |

## Authoritative surfaces to check

- Control plane: `src/listener-resource-lambda/helpers/Listeners/ListenerRequestValidator.cs`, `ListenerHelperExtensions.cs`, `ListenerCreateHelper.cs`.
- Regional registration: `helpers/DestinationArns/DestinationArnRequestValidator.cs`.
- PacketSource: `helpers/PacketSources/PacketSourceRequestValidator.cs` and `SubscriptionHelper.cs`.
- SDK: `src/lambda-sdk/UdpGatewayMessage.cs`, `UdpGatewayReply.cs`, `UdpGatewayBatchProcessor.cs`, `UdpGatewayLambdaJsonSerializer.cs`, `DecapsulatedHandler.cs`.
- Templates: selected `content/*/Function.cs`, `Program.cs`, project file, and deployment template.
- BREX: `docs/BinaryRangeExpression.g4` plus parser/evaluator tests.

When working in a multi-repository checkout, use those sibling sources if available. Otherwise consult the public docs and selected repositories/package contents; do not assume the user has this checkout or access to implementation repositories.

Useful public documentation:

- [Listener properties](https://proxylity.com/docs/cloudformation/listener.html)
- [Destination properties and formatter behavior](https://proxylity.com/docs/cloudformation/destination.html)
- [Regional ARN registration](https://proxylity.com/docs/cloudformation/destination-arn.html)
- [Lambda modes](https://proxylity.com/docs/destinations/lambda.html)
- [Packet formats](https://proxylity.com/docs/destinations/json-packet-format.html)
- [BREX syntax](https://proxylity.com/docs/destinations/brex-syntax.html)
- [PacketSource](https://proxylity.com/docs/listeners/packet-sources.html)
- [DTLS](https://proxylity.com/docs/listeners/dtls.html)
- [Metrics](https://proxylity.com/docs/metrics.html)

## Known discrepancies: do not copy blindly

| Older guidance | Correct approach for the checked implementation |
|---|---|
| Multiple entries in `Protocols` | Exactly one of `udp`, `wg`, `dtls`, `webrtc` |
| Regional registration by listener ID/destination index | `Destination`, `IngressRegionKey`, `Arn` |
| `Role.RoleArn` | `Role.Arn` for listener/destination; PacketSource topic `Role` is a plain ARN |
| Replies always base64 | Encode with the destination formatter; CoAP uses stringified JSON |
| CoAP `"Type": "Confirmable"` and text option values | Numeric type, CoAP code string, numeric option number/base64 option value |
| SDK `ProxylityLambdaRequest` / `ResponsePacket` | Actual `UdpGateway*` types and SDK 2.x `Reply` / `NoReply` methods |
| Default AWS serializer for SDK models | `UdpGatewayLambdaJsonSerializer`, including AOT bootstrap |
| `DecapsulatedHandler` consumes bare application bytes | It consumes complete IP packet bytes; application decapsulation uses another path |
| PacketSource required per egress region | Topic is stack-regional; one registration subscribes per-region delivery queues |
| Location `TimestampTimeUnit` | Validator accepts `TimeUnit`; confirm adapter/deployment before using custom timestamps |
| SQS FIFO implicit default group | Current validator requires explicit group-expression configuration |
| `listener-schema.json` is complete/current | It contains stale fields/types and is not the custom-resource runtime validator |

If source and docs disagree, identify the discrepancy, prefer the active validator for accepted property names, and verify behavior with the actual deployed service. Do not convert a local implementation detail or inferred stream/session behavior into an availability guarantee.
