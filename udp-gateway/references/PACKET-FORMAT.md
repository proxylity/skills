# Packet Format Reference — Proxylity UDP Gateway

## Delivery Format by Destination Type

| Destination | Inbound Format | Outbound (Replies) |
|---|---|---|
| Lambda | JSON object: `{ "Messages": [RequestPacket, ...] }` | JSON object: `{ "Replies": [ResponsePacket, ...] }` |
| Step Functions Express | JSON object: `{ "Messages": [RequestPacket, ...] }` | JSON object: `{ "Replies": [ResponsePacket, ...] }` |
| API Gateway | JSON object: `{ "Messages": [RequestPacket, ...] }` | JSON object: `{ "Replies": [ResponsePacket, ...] }` |
| SNS | One JSON-encoded `RequestPacket` per message | Not applicable (write-only) |
| SQS (standard or FIFO) | One JSON-encoded `RequestPacket` per SQS message | Not applicable (write-only) |
| EventBridge | One `RequestPacket` per event; assigned to `detail` field; `source` = `"proxylity"`, `detail-type` = `"udp-gateway-packet-ingress"` | Not applicable |
| DynamoDB | One record per `RequestPacket`; primary key = src/dst tuple; sort key = arrival timestamp; packet properties mapped to attributes | Not applicable |
| Firehose | NDJSON: one JSON-encoded `RequestPacket` per line | Not applicable |
| S3 | NDJSON: one JSON-encoded `RequestPacket` per line | Not applicable |
| CloudWatch Logs | Packet `Data` as UTF-8 string; one log event per `RequestPacket` | Not applicable |
| IoT Core (static mode) | One JSON-encoded `RequestPacket` per MQTT message | Not applicable |
| IoT Core (dynamic mode) | Raw binary payload, no JSON wrapping | Not applicable |

---

## RequestPacket — Full JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "RequestPacket",
  "type": "object",
  "required": ["Tag", "Remote", "Local", "Data"],
  "properties": {
    "Tag": {
      "type": "string",
      "description": "Unique identifier for this packet within the batch. Include in Replies to send a response to this packet's sender."
    },
    "Remote": {
      "type": "object",
      "required": ["IpAddress", "Port"],
      "properties": {
        "IpAddress": { "type": "string", "description": "Sender's IP address" },
        "Port":      { "type": "integer", "description": "Sender's UDP source port" },
        "PeerKey":   { "type": "string", "format": "byte", "description": "WireGuard peer public key (base64), if applicable" }
      }
    },
    "Local": {
      "type": "object",
      "required": ["Domain", "Port"],
      "properties": {
        "Domain": { "type": "string", "description": "Ingress subdomain that received the packet, e.g. 'ingress-1'" },
        "Port":   { "type": "integer", "description": "Listener port that received the packet" }
      }
    },
    "ReceivedAt": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp when the packet was received"
    },
    "Formatter": {
      "type": "string",
      "enum": ["base64", "hex", "utf8", "ascii", "coap"],
      "description": "Encoding applied to Data"
    },
    "Data": {
      "type": "string",
      "description": "Packet payload. Encoding depends on Formatter. For coap, this is a stringified JSON object."
    },
    "Inner": {
      "type": "object",
      "description": "Present only when DecapsulatedDelivery is enabled on a WireGuard listener. Contains the decapsulated IP header.",
      "required": ["Protocol", "Version", "SourceAddress", "SourcePort", "DestinationAddress", "DestinationPort"],
      "properties": {
        "Protocol":           { "type": "string", "description": "Inner IP protocol, e.g. 'UDP'" },
        "Version":            { "type": "string", "description": "IP version, e.g. 'IPv4'" },
        "SourceAddress":      { "type": "string" },
        "SourcePort":         { "type": "integer" },
        "DestinationAddress": { "type": "string" },
        "DestinationPort":    { "type": "integer" }
      }
    }
  }
}
```

---

## ResponsePacket — Full JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ResponsePacket",
  "type": "object",
  "required": ["Tag", "Data"],
  "properties": {
    "Tag": {
      "type": "string",
      "description": "Must match the Tag of the RequestPacket being replied to. Proxylity routes the reply to the sender's IP:port."
    },
    "Data": {
      "type": "string",
      "format": "byte",
      "description": "Response payload in base64 encoding. Always base64 regardless of the destination formatter."
    }
  }
}
```

**Important**: `Data` in responses is always base64-encoded, even when the formatter for inbound packets is `utf8` or `coap`.

---

## Formatter Details

### `base64` (default)

Raw packet bytes encoded as standard base64. Decode before processing:

```javascript
// Node.js
const bytes = Buffer.from(message.Data, 'base64');

// Python
import base64
data = base64.b64decode(message['Data'])

// Go
data, _ := base64.StdEncoding.DecodeString(message.Data)
```

### `utf8` / `ascii`

`Data` is a plain string — the packet payload decoded as text. No decoding needed.

```javascript
const text = message.Data;  // already a string
```

### `hex`

`Data` is a lowercase hex string (e.g. `"deadbeef"`).

### `coap`

`Data` is a JSON string containing a parsed CoAP message object. Parse with `JSON.parse(message.Data)`:

```json
{
  "Version": 1,
  "Type": "Confirmable",
  "Code": "GET",
  "MessageId": 12345,
  "Token": "base64-token",
  "Options": [
    { "Number": 11, "Name": "Uri-Path", "Value": "time" }
  ],
  "Payload": ""
}
```

CoAP option numbers follow RFC 7252. Common options: 3 = Uri-Host, 4 = ETag, 7 = Uri-Port, 11 = Uri-Path, 15 = Uri-Query, 17 = Accept, 60 = Size1.

---

## Lambda Handler Examples

### Node.js (base64 payload, echo response)

```javascript
exports.handler = async (event) => {
  const replies = event.Messages.map(msg => ({
    Tag: msg.Tag,
    Data: msg.Data  // echo back the same base64 payload
  }));
  return { Replies: replies };
};
```

### Python (utf8 text, count by sender)

```python
import base64

def handler(event, context):
    counts = {}
    for msg in event['Messages']:
        ip = msg['Remote']['IpAddress']
        counts[ip] = counts.get(ip, 0) + 1
    
    seen = set()
    replies = []
    for msg in event['Messages']:
        ip = msg['Remote']['IpAddress']
        if ip not in seen:
            seen.add(ip)
            replies.append({
                'Tag': msg['Tag'],
                'Data': base64.b64encode(str(counts[ip]).encode()).decode()
            })
    return {'Replies': replies}
```

### Go (binary packet processing)

```go
package main

import (
    "context"
    "encoding/base64"
    "github.com/aws/aws-lambda-go/lambda"
)

type Message struct {
    Tag    string `json:"Tag"`
    Remote struct { IpAddress string `json:"IpAddress"` } `json:"Remote"`
    Data   string `json:"Data"`
}

type Event struct { Messages []Message `json:"Messages"` }

type Reply  struct { Tag string `json:"Tag"` ; Data string `json:"Data"` }
type Response struct { Replies []Reply `json:"Replies"` }

func handler(ctx context.Context, event Event) (Response, error) {
    replies := make([]Reply, 0, len(event.Messages))
    for _, msg := range event.Messages {
        payload, _ := base64.StdEncoding.DecodeString(msg.Data)
        // ... process payload ...
        encoded := base64.StdEncoding.EncodeToString(payload)
        replies = append(replies, Reply{Tag: msg.Tag, Data: encoded})
    }
    return Response{Replies: replies}, nil
}

func main() { lambda.Start(handler) }
```

### C# .NET NativeAOT (fastest cold start ~100ms)

```csharp
using System.Text.Json;
using Amazon.Lambda.Core;

[assembly: LambdaSerializer(typeof(Amazon.Lambda.Serialization.SystemTextJson.DefaultLambdaJsonSerializer))]

public record Remote(string IpAddress, int Port);
public record Local(string Domain, int Port);
public record Message(string Tag, Remote Remote, Local Local, string Data, string ReceivedAt);
public record Event(Message[] Messages);
public record Reply(string Tag, string Data);
public record Response(Reply[] Replies);

public class Function
{
    public Response FunctionHandler(Event input, ILambdaContext context)
    {
        var replies = input.Messages
            .Select(m => new Reply(m.Tag, m.Data))  // echo
            .ToArray();
        return new Response(replies);
    }
}
```

---

## EventBridge Event Structure

When using an EventBridge destination, each packet arrives as an EventBridge event:

```json
{
  "version": "0",
  "id": "...",
  "source": "proxylity",
  "detail-type": "udp-gateway-packet-ingress",
  "account": "123456789012",
  "region": "us-east-1",
  "detail": {
    "Tag": "abc123",
    "Remote": { "IpAddress": "1.2.3.4", "Port": 5678 },
    "Local":  { "Domain": "ingress-1", "Port": 15678 },
    "Data": "<base64 or decoded>",
    "ReceivedAt": "2024-01-01T00:00:00.000Z"
  }
}
```

Use EventBridge Rules with `source: ["proxylity"]` and `detail-type: ["udp-gateway-packet-ingress"]` to filter and route to further targets.

---

## Step Functions Express Input/Output

The state machine input is the same `{ "Messages": [...] }` envelope as Lambda. Use JSONata or JSONPath expressions to access packet fields within states.

JSONata example — extract sender IP from first message:
```
States.input.Messages[0].Remote.IpAddress
```

The state machine must return `{ "Replies": [...] }` as its output to send responses back to clients. Only Express workflows are supported.
