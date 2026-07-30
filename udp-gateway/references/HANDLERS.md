# Handler Implementation Reference

Working handler skeletons extracted from [proxylity/examples](https://github.com/proxylity/examples). Use these as starting points, not the format description in the skill — the format description tells you *what* to produce, these tell you *how* to produce it in each runtime.

---

## Node.js (inline CloudFormation — no SAM required)

The simplest deployment: the handler is embedded directly in the CloudFormation template as a `ZipFile` string. No build step, no SAM, no S3 artifact.

**CloudFormation template fragment:**
```json
"Handler": {
  "Type": "AWS::Lambda::Function",
  "Properties": {
    "Runtime": "nodejs22.x",
    "Handler": "index.handler",
    "Code": {
      "ZipFile": {
        "Fn::Join": ["\n", [
          "exports.handler = async (inbound) => {",
          "  const counts = inbound.Messages.reduce((acc, m) => {",
          "    acc[m.Remote.IpAddress] = (acc[m.Remote.IpAddress] || 0) + 1;",
          "    return acc;",
          "  }, {});",
          "  const replies = inbound.Messages.flatMap(m => {",
          "    const count = counts[m.Remote.IpAddress];",
          "    if (count == null) return [];",
          "    counts[m.Remote.IpAddress] = null;",
          "    return [{ Tag: m.Tag, Data: btoa(count + '\\n') }];",
          "  });",
          "  return { Replies: replies };",
          "};"
        ]]
      }
    },
    "Role": { "Fn::GetAtt": ["HandlerRole", "Arn"] }
  }
}
```

**Standalone `index.mjs` (for `nodejs22.x` with ES modules):**
```javascript
export const handler = async (inbound) => {
  // inbound.Messages is the batch array; Data is base64 by default
  const replies = inbound.Messages.map(m => {
    const payload = Buffer.from(m.Data, 'base64');
    // ... process payload ...
    const response = Buffer.from('ok\n');
    return { Tag: m.Tag, Data: response.toString('base64') };
  });
  return { Replies: replies };
};
```

**Key points:**
- `inbound.Messages[i].Tag` — opaque string; must be echoed in the reply to route the response back to the correct client.
- `inbound.Messages[i].Data` — base64-encoded raw bytes when `Formatter` is `base64` (default). Use `Buffer.from(m.Data, 'base64')` to get bytes.
- Return `{ Replies: [] }` (not `null`, not `{}`) when there is nothing to reply.
- Fire-and-forget (no response needed): return `{ Replies: [] }` or omit the `Tag` from `Replies`.

---

## Python

Requires SAM CLI (`sam build && sam deploy`). Runtime: `python3.12` or `python3.11`.

**`src/app.py`:**
```python
import base64
from datetime import datetime, timezone
from typing import Any

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    messages = event.get('Messages', [])

    replies = []
    for msg in messages:
        raw = base64.b64decode(msg['Data'])          # bytes from client
        # ... process raw ...
        response = b'ok\n'
        replies.append({
            'Tag': msg['Tag'],
            'Data': base64.b64encode(response).decode(),
        })

    return {'Replies': replies}
```

**`template.yaml` Lambda resource fragment:**
```yaml
Handler:
  Type: AWS::Serverless::Function
  Properties:
    CodeUri: src/
    Handler: app.handler
    Runtime: python3.12
    Architectures: [x86_64]
    Role: !GetAtt HandlerRole.Arn
```

**Key points:**
- `msg['Remote']['IpAddress']` and `msg['Remote']['Port']` — client source address.
- `msg['Local']['Domain']` and `msg['Local']['Port']` — which listener endpoint received this packet.
- `msg['ReceivedAt']` — ISO 8601 timestamp string.
- `msg['Formatter']` — reflects the formatter configured on the destination (`base64`, `utf8`, `coap`, etc.).
- When `Formatter` is `utf8` or `ascii`, `msg['Data']` is already a decoded string — do **not** call `base64.b64decode` on it. The reply `Data` must still be base64 regardless of the inbound formatter.

---

## Go

Requires SAM CLI and Go ≥ 1.23. Produces a compiled `bootstrap` binary (Amazon Linux 2023 runtime `provided.al2023`).

**`src/main.go`:**
```go
package main

import (
    "context"
    "encoding/base64"

    "github.com/aws/aws-lambda-go/lambda"
)

type Remote struct {
    IpAddress string `json:"IpAddress"`
    Port      int    `json:"Port"`
}

type Local struct {
    Domain string `json:"Domain"`
    Port   int    `json:"Port"`
}

type Message struct {
    Tag        string `json:"Tag"`
    Remote     Remote `json:"Remote"`
    Local      Local  `json:"Local"`
    ReceivedAt string `json:"ReceivedAt"`
    Formatter  string `json:"Formatter"`
    Data       string `json:"Data"`
}

type InboundPackets struct {
    Messages []Message `json:"Messages"`
}

type OutboundPacket struct {
    Tag  string `json:"Tag"`
    Data string `json:"Data"`
}

type Response struct {
    Replies []*OutboundPacket `json:"Replies"`
}

func handler(ctx context.Context, inbound InboundPackets) (Response, error) {
    var replies []*OutboundPacket
    for _, msg := range inbound.Messages {
        raw, _ := base64.StdEncoding.DecodeString(msg.Data) // raw bytes from client
        _ = raw
        // ... process raw ...
        response := []byte("ok\n")
        replies = append(replies, &OutboundPacket{
            Tag:  msg.Tag,
            Data: base64.StdEncoding.EncodeToString(response),
        })
    }
    return Response{Replies: replies}, nil
}

func main() {
    lambda.Start(handler)
}
```

**`src/Makefile` (SAM calls this via `build-<LogicalId>`):**
```makefile
build-Handler:
	go mod tidy
	go mod vendor
	GOOS=linux GOARCH=amd64 go build -o bootstrap main.go
	mkdir -p $(ARTIFACTS_DIR)
	mv bootstrap $(ARTIFACTS_DIR)/bootstrap
	chmod +x $(ARTIFACTS_DIR)/bootstrap
```

**`template.yaml` Lambda resource fragment:**
```yaml
Handler:
  Type: AWS::Serverless::Function
  Properties:
    CodeUri: src/
    Handler: bootstrap
    Runtime: provided.al2023
    Architectures: [x86_64]
    Role: !GetAtt HandlerRole.Arn
```

**Key points:**
- The `aws-lambda-go` library handles JSON marshalling automatically — just define your structs with `json:` tags and pass `handler` to `lambda.Start`.
- Return `Response{Replies: nil}` (or an empty slice) to send no replies.
- For fire-and-forget workloads (SQS/Kinesis destinations), the return value is ignored — return `Response{}, nil`.

---

## .NET / C# — Typed SDK (recommended for new handlers)

Uses the `Proxylity.UdpGateway.LambdaSdk` NuGet package, which provides typed request/response classes and handles per-message dispatch. Best for NativeAOT (cold start ~100ms).

**`src/Function.cs`:**
```csharp
using Amazon.Lambda.Core;
using Proxylity.UdpGateway.LambdaSdk;

[assembly: LambdaSerializer(typeof(Amazon.Lambda.Serialization.SystemTextJson.DefaultLambdaJsonSerializer))]

public class Function
{
    public async Task<ProxylityLambdaResponse> FunctionHandler(
        ProxylityLambdaRequest request, ILambdaContext context)
    {
        if (request.Messages is not { Length: > 0 })
            return new ProxylityLambdaResponse { Replies = [] };

        var replies = new List<ResponsePacket>();
        foreach (var msg in request.Messages)
        {
            var raw = Convert.FromBase64String(msg.Data);  // bytes from client
            // ... process raw ...
            var response = "ok\n"u8.ToArray();
            replies.Add(new ResponsePacket
            {
                Tag  = msg.Tag,
                Data = Convert.ToBase64String(response),
            });
        }
        return new ProxylityLambdaResponse { Replies = [.. replies] };
    }
}
```

**`template.yaml` Lambda resource fragment (NativeAOT):**
```yaml
Handler:
  Type: AWS::Serverless::Function
  Properties:
    CodeUri: src/
    Handler: Handler::Function_FunctionHandler_Generated  # generated by NativeAOT tooling
    Runtime: provided.al2023
    Architectures: [x86_64]
    Role: !GetAtt HandlerRole.Arn
```

**Key points:**
- `ProxylityLambdaRequest.Messages` is `UdpGatewayMessage[]`. Each element has `Tag`, `Data` (base64), `Remote` (`IpAddress`, `Port`), `Local` (`Domain`, `Port`), `ReceivedAt`, `Formatter`.
- `ProxylityLambdaResponse.Replies` is `ResponsePacket[]`. Only set `Tag` and `Data`; `GeneratedAt` is optional.
- If no reply is needed, return `new ProxylityLambdaResponse { Replies = [] }`.

---

## .NET / C# — Raw `JsonObject` (no SDK dependency)

Use when you want no extra NuGet dependency or prefer to work with the raw JSON directly. Pattern from `dns-filter`.

**`src/Function.cs`:**
```csharp
using Amazon.Lambda.Core;
using System.Text.Json.Nodes;

[assembly: LambdaSerializer(typeof(Amazon.Lambda.Serialization.SystemTextJson.DefaultLambdaJsonSerializer))]

public class Function
{
    public async Task<JsonObject> FunctionHandler(JsonObject input, ILambdaContext context)
    {
        var packets = input["Messages"]?.AsArray()
            ?? throw new InvalidOperationException("Missing Messages — is this from UDP Gateway?");

        var replyTasks = packets.Select(async p =>
        {
            var tag  = p!["Tag"]!.ToString();
            var data = Convert.FromBase64String(p["Data"]!.ToString()); // raw bytes
            // ... process data ...
            var response = "ok\n"u8.ToArray();
            return (JsonNode)new JsonObject
            {
                ["Tag"]  = tag,
                ["Data"] = Convert.ToBase64String(response),
            };
        });

        var replies = await Task.WhenAll(replyTasks);
        return new JsonObject { ["Replies"] = new JsonArray(replies) };
    }
}
```

**Key points:**
- No `Proxylity.UdpGateway.LambdaSdk` dependency — only the standard AWS Lambda serializer.
- Suitable for fire-and-forget destinations (SQS, EventBridge, DynamoDB) where Proxylity ignores the return value anyway; simplifies the function to a plain `Task` return.
- For parallel per-packet processing: use `Task.WhenAll` as shown; for sequential processing use a simple `foreach`.

---

## Step Functions Express — no handler code

Step Functions Express workflows receive the same batch envelope as Lambda but there is no handler function to write. The state machine ASL replaces the handler. Proxylity invokes the state machine synchronously (Express) and reads `Replies` from the execution output.

**Minimal ASL that echoes each packet:**
```json
{
  "Comment": "Echo each packet back to the sender",
  "StartAt": "BuildReplies",
  "States": {
    "BuildReplies": {
      "Type": "Pass",
      "Parameters": {
        "Replies.$": "$.Messages[*].{ Tag: Tag, Data: Data }"
      },
      "End": true
    }
  }
}
```

**Key points:**
- The input to the execution is the same `{ "Messages": [...] }` batch envelope.
- The output must be `{ "Replies": [...] }` — same contract as Lambda.
- Use `"Type": "EXPRESS"` on the state machine resource; STANDARD workflows are async and cannot return replies.
- Zero Lambda cold start; ~50ms per-execution overhead from Step Functions itself.
- For data transformation without code, use JSONata states (`"QueryLanguage": "JSONata"`).

---

## WireGuard / Decapsulated handler (.NET SDK)

When `DecapsulatedDelivery: true` is set on the WireGuard listener, Proxylity strips the WireGuard envelope and delivers raw inner UDP packets. Use `DecapsulatedHandler` from the SDK.

```csharp
using PacketDotNet;
using Proxylity.UdpGateway.LambdaSdk;

public class MyHandler : DecapsulatedHandler
{
    // Called once per inner UDP payload; return response bytes or null for no reply
    public override async Task<byte[]?> HandleAsync(
        byte[] payload, RemoteEndpoint remote, ILambdaLogger logger)
    {
        // payload is the decrypted inner UDP payload (not the WireGuard envelope)
        logger.LogLine($"Received {payload.Length} bytes from {remote.IpAddress}:{remote.Port}");
        return await Task.FromResult<byte[]?>(null); // no reply
    }

    // Override per packet-type methods (IcmpV4Packet, UdpPacket, etc.) for typed dispatch
    public override async Task<byte[]?> HandleAsync(
        IcmpV4Packet packet, RemoteEndpoint remote, ILambdaLogger logger)
    {
        // Respond to ICMP echo requests (ping)
        var pong = new IcmpV4Packet(...) { TypeCode = IcmpV4TypeCode.EchoReply };
        return await Task.FromResult(pong.Bytes);
    }
}
```

**Key points:**
- `DecapsulatedHandler` dispatches by inner packet type; override only the types you care about.
- The outer Lambda function class wires this up via `new MyHandler().HandleBatchAsync(request, context)`.
- Responses are automatically re-encapsulated in WireGuard before delivery to the client.
- Requires `DecapsulatedDelivery: true` on the destination in the CloudFormation template.

---

## Common mistakes to avoid in generated handler code

| Mistake | Correct pattern |
|---|---|
| Returning `null` instead of `{ Replies: [] }` from Node.js | Always return `{ Replies: [] }` for no-reply |
| Forgetting `[assembly: LambdaSerializer(...)]` in C# | Required on every Lambda entry-point assembly |
| Calling `base64.b64decode` on `Data` when `Formatter` is `utf8` | Only decode base64 when `Formatter` is `base64` (the default) |
| Hardcoding `Tag` values in replies | Always echo `msg.Tag` from the inbound message |
| Returning replies for packets that should be fire-and-forget | Omit the `Tag` from `Replies` or return `Replies: []` |
| Using `STANDARD` Step Functions for request/response | Must use `EXPRESS`; STANDARD cannot return replies |
| Using `int` for `Port` in Go structs without a json tag | All struct fields need `json:"..."` tags matching the wire format |
