# Destinations and IAM

All examples below are destination fragments, not complete templates. Each destination needs a Proxylity-assumable role with `Role.Arn`. Use the customer mapping's `ServiceRole` as trust principal. Resource ARNs below use the commercial AWS partition; use the actual supported partition/region when adapting.

## Delivery permissions and payloads

| Destination | ARN resource form | Delivery IAM actions | Delivered content |
|---|---|---|---|
| Lambda | `arn:aws:lambda:REGION:ACCOUNT:function:NAME[:QUALIFIER]` | `lambda:InvokeFunction` | `{"Messages":[...]}` |
| Step Functions Express | `arn:aws:states:REGION:ACCOUNT:stateMachine:NAME` | `states:DescribeStateMachine`, `states:StartSyncExecution` | Batch envelope; synchronous `Replies` output |
| Step Functions Standard | Same | `states:DescribeStateMachine`, `states:StartExecution` | Batch envelope; no synchronous replies |
| API Gateway | `arn:aws:execute-api:REGION:ACCOUNT:API/STAGE/POST/PATH` | `execute-api:Invoke` | Batch envelope; map HTTP response to `Replies` |
| EventBridge | `arn:aws:events:REGION:ACCOUNT:event-bus/NAME` | `events:PutEvents` | One packet per event `detail` |
| SQS | `arn:aws:sqs:REGION:ACCOUNT:NAME[.fifo]` | `sqs:GetQueueUrl`, `sqs:SendMessage` | One packet JSON per message by default |
| SNS | `arn:aws:sns:REGION:ACCOUNT:NAME` | `sns:Publish` | One packet JSON per message |
| Kinesis Data Streams | `arn:aws:kinesis:REGION:ACCOUNT:stream/NAME` | `kinesis:PutRecords` | Encoded packet records |
| Data Firehose | `arn:aws:firehose:REGION:ACCOUNT:deliverystream/NAME` | `firehose:PutRecord` | NDJSON batch |
| DynamoDB | `arn:aws:dynamodb:REGION:ACCOUNT:table/NAME` | `dynamodb:DescribeTable`, `dynamodb:BatchWriteItem` | Packet properties mapped to an item |
| S3 | `arn:aws:s3:::BUCKET` | `s3:PutObject` on `arn:aws:s3:::BUCKET/*` | NDJSON objects |
| CloudWatch Logs | `arn:aws:logs:REGION:ACCOUNT:log-group:NAME` | `logs:CreateLogStream`, `logs:PutLogEvents` on log streams | Text formatter: prefixed payload text; protocol-aware formatter: request-packet JSON; one event per packet |
| AWS IoT Data | `arn:aws:iot:REGION:ACCOUNT:topic/PATH` | `iot:Publish` | Packet JSON, or binary payload in dynamic mode |
| Location tracker | `arn:aws:geo:REGION:ACCOUNT:tracker/NAME` | `geo:BatchUpdateDevicePosition` | Device position updates extracted with BREX |

Scope delivery permissions to the specific target, including aliases/qualifiers and API stage/method/path. SQS/SNS batch APIs use their respective `SendMessage`/`Publish` IAM actions. Do not infer unsupported SNS FIFO group configuration from SQS-specific arguments.

Destination roles may additionally need:

- `logs:CreateLogStream` and `logs:PutLogEvents` on configured delivery-error log streams.
- `cloudwatch:PutMetricData` on `"*"` when `MetricsEnabled` is true; restrict with `cloudwatch:namespace = Proxylity/UDP Gateway`.
- Appropriate KMS key permissions and key policies for the actual encrypted service. These are service-specific, not a universal wildcard KMS policy.

## Common destination options

```json
{
  "DestinationArn": "arn:aws:lambda:us-east-1:123456789012:function:handler",
  "Role": { "Arn": "arn:aws:iam::123456789012:role/GatewayDelivery" },
  "Formatter": "base64",
  "Batching": { "Count": 10, "TimeoutInSeconds": 0.05 },
  "MetricsEnabled": true,
  "LogGroupName": "/proxylity/delivery-errors"
}
```

`Formatter` is per destination: `base64`, `hex`, `utf8`, `ascii`, `coap`, `coap+`, or `syslog`. The first four produce string `Data`; the protocol-aware formatters produce object `Data` for requests, replies, and PacketSource messages. Choose `coap+` for content-aware CoAP or `syslog` for RFC 5424/3164 fields. See the [packet contract](./PACKET-FORMAT.md) for payload types, migration, and parse/encoding errors.

Structured fields can be consumed without Lambda: DynamoDB stores `Data` as a map, EventBridge/SNS can filter fields, and S3/Firehose NDJSON can be queried as structs in Athena. CloudWatch Logs protocol-aware destinations write the full JSON request packet without the text formatter's prefix; Logs Insights can query `Data.severity`, `Data.hostname`, etc. Use `utf8` on a separate destination when original syslog text is wanted. Enable delivery-error logs/metrics and handle malformed records explicitly.

`FilterExpression` is also per destination and is evaluated before delivery; it is a BREX expression over packet bytes, not a JSON-field EventBridge pattern. See architecture for regional ARN maps, batching, and metric semantics. For CDK, prefer [specialized L2 destinations](./CDK.md) to derive delivery IAM; caller-supplied roles and `ArnDestination` require explicit permissions.

## Lambda: sync, async, streaming, tenants

All options belong under `Arguments`:

| Argument | Meaning |
|---|---|
| `UseAsyncInvoke: true` | Lambda `Event` invocation; output ignored; AWS async retry/destination policies apply |
| `UseResponseStreaming: true` | Invoke with response stream; requires a streaming implementation |
| `TenantId` | Static tenant ID for a Lambda function configured for tenant isolation |
| `TenantIdExpression` | BREX-derived tenant ID |
| `TenantIdFormatter` | `ascii`, `utf8`, `hex`, or `base64`; not `coap`, `coap+`, or `syslog` |

Never enable async invocation and response streaming together. Do not set both static and expression-derived tenant IDs without checking precedence in the deployed adapter. Tenant-aware batches are segmented by tenant before delivery. Validate the extracted tenant identifier; it must not become an accidental authorization boundary. Tenant isolation is not provided merely by setting an argument on an ordinary Lambda function.

```json
{
  "Arguments": {
    "TenantIdExpression": "[0:4]",
    "TenantIdFormatter": "hex",
    "UseResponseStreaming": true
  }
}
```

Choose runtime versions supported by the target region and existing project. Go uses an OS-only runtime such as `provided.al2023`, not the retired managed `go1.x`. NativeAOT can reduce startup costs but is not a latency guarantee. For durable/background handlers, verify AWS runtime and invocation requirements separately.

## Step Functions and API Gateway

Express is invoked synchronously; Standard starts asynchronously. Grant `states:DescribeStateMachine` for type detection. Standard cannot return immediate UDP replies, but a workflow can explicitly publish delayed packets through PacketSource.

API Gateway bridges to a configured **POST** method. Use IAM authentication and an HTTP/backend integration. REST APIs support VTL request/response transformation; HTTP APIs do not offer the same VTL mapping capability. A backend's arbitrary JSON response does not automatically become UDP replies: preserve tags and map it to the gateway response contract. Store third-party credentials in protected configuration, not committed mapping templates.

## SQS: format, groups, deduplication

```json
{
  "Arguments": {
    "MessageGroupIdExpression": "[0:4]",
    "MessageGroupIdFormatter": "hex",
    "MessageDeduplicationIdExpression": "[4:8]",
    "MessageDeduplicationIdFormatter": "hex"
  }
}
```

- For FIFO, configure an explicit `MessageGroupIdExpression`: the current control-plane validator requires it. Documentation describing an implicit default group is not sufficient to pass that validator.
- Grouping can also support standard-queue fairness; fairness is not FIFO ordering.
- The documented adapter assigns random deduplication IDs when no expression is set. Do not assume enabling queue content-based deduplication deduplicates UDP traffic. Prefer a bounded protocol/device/transaction ID; do not deduplicate legitimate identical heartbeats.
- `Arguments.SendRaw` and `Arguments.UseMessageAttributes` change the default envelope. Verify consumer expectations, encoding, and SQS allowed-character limits before using raw mode for binary protocols.
- FIFO orders accepted messages within a group; it does not repair ingress loss/reordering or guarantee exactly-once application effects. Keep consumers idempotent and configure queue redrive.

## Kinesis

Use `Arguments.PartitionKeyExpression` plus **`PartitionKeyExpressionFormatter`** (not `PartitionKeyFormatter`):

```json
{
  "Arguments": {
    "PartitionKeyExpression": "[0:4]",
    "PartitionKeyExpressionFormatter": "hex"
  }
}
```

Use device keys only when per-key grouping is required; skewed keys can create hot shards. Validate record and request size limits as well as count.

## IoT Data

The ARN identifies an MQTT **topic**, not a topic rule. Static mode publishes packet JSON. Dynamic mode publishes raw payload bytes to a topic below the ARN's base path:

```json
{
  "Arguments": {
    "DynamicTopicSuffix": true,
    "TopicSuffixExpression": "[0:4]",
    "TopicSuffixFormatter": "hex"
  }
}
```

Without the suffix expression, the documented suffix is `{source_ip}/{source_port}`. Scope `iot:Publish` to the base topic and intended subtopics. Verify generated topic names/lengths and use QoS 0 expectations; this is not guaranteed delivery.

## Location trackers

Example payload layout: 4-byte device ID, signed little-endian latitude and longitude in microdegrees:

```json
{
  "Arguments": {
    "DeviceIdExpression": "u32le[0:4]",
    "LatitudeExpression": "i32le[4:8]",
    "LongitudeExpression": "i32le[8:12]",
    "ScaleFactor": 0.000001
  }
}
```

All three expressions are required. Prefer an explicit `ScaleFactor` matching the device protocol rather than relying on type-dependent angular defaults. Optional settings include `AccuracyExpression`, `TimestampExpression`, `PositionPropertyExpressions`, and **`TimeUnit`** (`seconds` or `milliseconds`). The current validator accepts `TimeUnit`; some website text instead says `TimestampTimeUnit`, which it rejects. Check actual adapter/deployment behavior before configuring a custom timestamp.

Validate coordinate ranges, timestamp units, and device IDs with real packet fixtures. Position updates do not generate acknowledgments; add a separate processing destination if the protocol requires one.

## EventBridge, storage, and logs

- EventBridge event matching uses `source: ["proxylity"]` and `detail-type: ["udp-gateway-packet-ingress"]`; packet metadata lives in `detail`.
- DynamoDB discovers key attribute names. The documented partition key value is `remote_ip:remote_port local_ip:local_port`, and the sort key is the arrival timestamp. Design for collisions, throughput, retention, and actual table schema rather than assuming an application-specific device key.
- Firehose and S3 store NDJSON, not one object per datagram. Set size thresholds with JSON/base64 overhead and downstream API limits in mind.
- Object Lock modes have materially different retention/deletion consequences. Never enable irreversible compliance retention without confirmation.
- CloudWatch Logs as a packet destination is different from `LogGroupName` delivery-error logging. Gate raw payload capture, redact secrets, and set retention.
