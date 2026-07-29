# Destination Reference — Proxylity UDP Gateway

Each destination requires an IAM role that Proxylity's `ServiceRole` can assume. The role must grant the minimum permissions for that specific destination.

---

## AWS Lambda

**DestinationArn**: Lambda function ARN (`arn:aws:lambda:{region}:{account}:function:{name}`)

**IAM policy statement:**

```json
{
  "Effect": "Allow",
  "Action": ["lambda:InvokeFunction"],
  "Resource": ["<function ARN>"]
}
```

**Destination configuration:**

```json
{
  "DestinationArn": { "Fn::GetAtt": ["MyFunction", "Arn"] },
  "Role": { "Arn": { "Fn::GetAtt": ["DestinationRole", "Arn"] } },
  "Batching": { "Count": 1000, "TimeoutInSeconds": 1 },
  "Formatter": "base64",
  "MetricsEnabled": true
}
```

**Formatter options**: `base64` (default), `utf8`, `ascii`, `hex`, `coap`

**Runtime recommendations:**
- Node.js 22.x — simplest for inline code
- Python 3.12 — concise, best ecosystem for data processing
- Go 1.x — highest throughput, requires SAM CLI to compile
- .NET NativeAOT — ~100ms cold start, requires SAM CLI; best for latency-sensitive protocols

---

## AWS Step Functions (Express)

**DestinationArn**: State machine ARN (`arn:aws:states:{region}:{account}:stateMachine:{name}`)

**IAM policy statement:**

```json
{
  "Effect": "Allow",
  "Action": ["states:StartSyncExecution"],
  "Resource": ["<state machine ARN>"]
}
```

**Destination configuration:**

```json
{
  "DestinationArn": { "Fn::GetAtt": ["CoapStateMachine", "Arn"] },
  "Role": { "Arn": { "Fn::GetAtt": ["DestinationRole", "Arn"] } },
  "Batching": { "Count": 1, "TimeoutInSeconds": 0.05 },
  "Formatter": "coap",
  "MetricsEnabled": true
}
```

**Requirements:**
- State machine type must be `EXPRESS` — Standard is not supported.
- State machine returns `{ "Replies": [...] }` as output.
- No Lambda cold-start overhead; ~50ms per execution overhead.

**SAM resource example:**

```json
"MyStateMachine": {
  "Type": "AWS::Serverless::StateMachine",
  "Properties": {
    "Type": "EXPRESS",
    "DefinitionUri": "state-machine.asl.json",
    "DefinitionSubstitutions": { "TableName": { "Ref": "MyTable" } },
    "Role": { "Fn::GetAtt": ["StateMachineRole", "Arn"] },
    "Logging": {
      "Level": "ALL",
      "IncludeExecutionData": true,
      "Destinations": [{ "CloudWatchLogsLogGroup": { "LogGroupArn": { "Fn::GetAtt": ["ExecutionLogs", "Arn"] } } }]
    }
  }
}
```

---

## Amazon EventBridge

**DestinationArn**: Must be a **region-keyed JSON object**, not a plain ARN.

```json
"DestinationArn": {
  "us-east-1": "arn:aws:events:us-east-1:123456789012:event-bus/default",
  "us-west-2": "arn:aws:events:us-west-2:123456789012:event-bus/default"
}
```

Use `"*"` as a wildcard key for any unspecified region:

```json
"DestinationArn": { "*": "arn:aws:events:us-east-1:123456789012:event-bus/default" }
```

**IAM policy statement:**

```json
{
  "Effect": "Allow",
  "Action": ["events:PutEvents"],
  "Resource": ["arn:aws:events:{region}:{account}:event-bus/default"]
}
```

**Each packet** becomes an EventBridge event with:
- `source`: `"proxylity"`
- `detail-type`: `"udp-gateway-packet-ingress"`
- `detail`: the `RequestPacket` object

**Create an EventBridge Rule** to process packets:

```json
"ProxylityRule": {
  "Type": "AWS::Events::Rule",
  "Properties": {
    "EventPattern": {
      "source": ["proxylity"],
      "detail-type": ["udp-gateway-packet-ingress"]
    },
    "State": "ENABLED",
    "Targets": [{ "Id": "MyTarget", "Arn": "..." }]
  }
}
```

---

## Amazon SQS (Standard Queue)

**DestinationArn**: Queue ARN (`arn:aws:sqs:{region}:{account}:{name}`)

**IAM policy statement:**

```json
{
  "Effect": "Allow",
  "Action": ["sqs:SendMessage"],
  "Resource": ["<queue ARN>"]
}
```

One `RequestPacket` per SQS message body (JSON).

---

## Amazon SQS (FIFO Queue)

**DestinationArn**: FIFO Queue ARN (must end in `.fifo`)

**IAM policy statement:**

```json
{
  "Effect": "Allow",
  "Action": ["sqs:SendMessage"],
  "Resource": ["<queue ARN>"]
}
```

**FIFO requires a `PartitionKeyExpression`** to set the message group ID:

```json
{
  "DestinationArn": { "Fn::GetAtt": ["DeviceQueue", "Arn"] },
  "Role": { "Arn": "..." },
  "PartitionKeyExpression": "[0:4]",
  "PartitionKeyFormatter": "hex"
}
```

Messages with the same message group ID are delivered in order. See ARCHITECTURE.md for BREX syntax details.

---

## Amazon Kinesis Data Streams

**DestinationArn**: Kinesis stream ARN (`arn:aws:kinesis:{region}:{account}:stream/{name}`)

**IAM policy statement:**

```json
{
  "Effect": "Allow",
  "Action": ["kinesis:PutRecords"],
  "Resource": ["<stream ARN>"]
}
```

**Optional partition key** (for shard routing):

```json
{
  "DestinationArn": { "Fn::GetAtt": ["DataStream", "Arn"] },
  "Role": { "Arn": "..." },
  "PartitionKeyExpression": "[0:4]",
  "PartitionKeyFormatter": "hex",
  "Batching": { "Count": 500, "TimeoutInSeconds": 1 }
}
```

Without `PartitionKeyExpression`, Proxylity uses a default partition key (random distribution across shards).

---

## Amazon Kinesis Data Firehose

**DestinationArn**: Firehose delivery stream ARN (`arn:aws:firehose:{region}:{account}:deliverystream/{name}`)

**IAM policy statement:**

```json
{
  "Effect": "Allow",
  "Action": ["firehose:PutRecordBatch"],
  "Resource": ["<delivery stream ARN>"]
}
```

Packets are delivered as NDJSON (newline-delimited JSON), one `RequestPacket` per line. Common use: buffer to S3 (with optional Glacier tiering) or deliver to OpenSearch.

**Firehose to S3 with encryption and WORM archival** — see `syslog/` example for a complete implementation including KMS encryption, S3 Object Lock (GOVERNANCE or COMPLIANCE mode), Glacier lifecycle transitions, and CloudWatch alarms.

---

## Amazon DynamoDB

**DestinationArn**: DynamoDB table ARN (`arn:aws:dynamodb:{region}:{account}:table/{name}`)

**IAM policy statement:**

```json
{
  "Effect": "Allow",
  "Action": ["dynamodb:PutItem", "dynamodb:BatchWriteItem"],
  "Resource": ["<table ARN>"]
}
```

One DynamoDB item per `RequestPacket`. The primary key is the `Remote.IpAddress:Remote.Port — Local.Domain:Local.Port` tuple; the sort key is `ReceivedAt`. All `RequestPacket` properties are mapped to item attributes.

---

## Amazon S3

**DestinationArn**: S3 bucket ARN (`arn:aws:s3:::{bucket}`)

**IAM policy statement:**

```json
{
  "Effect": "Allow",
  "Action": ["s3:PutObject"],
  "Resource": ["arn:aws:s3:::{bucket}/*"]
}
```

Packets are written as NDJSON objects. Objects are prefixed by date/time. Use lifecycle rules for Glacier archival and Object Lock for WORM compliance.

---

## Amazon CloudWatch Logs

**DestinationArn**: Log group ARN (`arn:aws:logs:{region}:{account}:log-group:{name}`)

**IAM policy statement:**

```json
{
  "Effect": "Allow",
  "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
  "Resource": ["<log group ARN>:*"]
}
```

`Data` is written as the log message text (UTF-8). One log event per packet. Use CloudWatch Metric Filters on the log group to alert on patterns (e.g., syslog severity levels).

---

## Amazon API Gateway (HTTP Bridge)

**DestinationArn**: API Gateway invoke ARN

**IAM policy statement:**

```json
{
  "Effect": "Allow",
  "Action": ["execute-api:Invoke"],
  "Resource": ["arn:aws:execute-api:{region}:{account}:{api-id}/{stage}/{method}/{resource}"]
}
```

API Gateway acts as a bridge from UDP to HTTP. Use Velocity Template Language (VTL) mapping templates in API Gateway to transform the `RequestPacket` into the HTTP request body and inject headers (e.g., `Authorization: Bearer <token>`). See `supabase-udp/` for a JWT-injection pattern using Step Functions for credential rotation.

---

## AWS IoT Core

**DestinationArn**: IoT topic rule ARN

**IAM policy statement:**

```json
{
  "Effect": "Allow",
  "Action": ["iot:Publish"],
  "Resource": ["arn:aws:iot:{region}:{account}:topic/{topic}"]
}
```

**Static mode**: Each packet delivered as a JSON-encoded `RequestPacket` MQTT message.

**Dynamic mode**: Raw binary payload only, no JSON wrapping — useful when IoT device firmware expects a specific binary format.

---

## Complete DestinationRole Template (Lambda example)

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
    "Policies": [{
      "PolicyName": "AllowLambdaInvoke",
      "PolicyDocument": {
        "Version": "2012-10-17",
        "Statement": [
          {
            "Effect": "Allow",
            "Action": ["lambda:InvokeFunction"],
            "Resource": [{ "Fn::GetAtt": ["MyFunction", "Arn"] }]
          },
          {
            "Effect": "Allow",
            "Action": ["cloudwatch:PutMetricData"],
            "Resource": "*"
          }
        ]
      }
    }]
  }
}
```

Add `cloudwatch:PutMetricData` with `Resource: "*"` whenever `"MetricsEnabled": true` is set on a destination — it is required for metrics reporting.
