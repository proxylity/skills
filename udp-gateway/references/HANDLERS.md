# Handler implementation

The examples below state their formatter explicitly. Do not combine a base64-only handler with `Formatter: coap`, `coap+`, `syslog`, or `utf8`. Protocol-aware formatters deliver object-valued `Data`; read fields directly and return objects, without JSON-stringifying them. See the [packet-format reference](./PACKET-FORMAT.md) for encoding and error handling.

## Node.js: base64 echo

Inline CloudFormation `ZipFile` / SAM `InlineCode` uses CommonJS `index.handler`:

```javascript
exports.handler = async (event) => {
  if (!Array.isArray(event.Messages)) {
    throw new TypeError("Expected UDP Gateway Messages array");
  }
  return {
    Replies: event.Messages.map(message => ({
      Tag: message.Tag,
      Data: message.Data
    }))
  };
};
```

This echoes arbitrary bytes without decoding/re-encoding. To process bytes use `Buffer.from(message.Data, "base64")` and encode response bytes with `.toString("base64")`. Node's decoder is permissive; validate protocol structure and length rather than assuming decoding authenticates or validates a packet. Use `export const handler` only in a packaged ES-module project such as an `.mjs` file.

For `utf8`, return text directly; do not base64-encode it. For no reply, omit that message from `Replies`, not its `Tag` from a reply object.

## Python: base64 processing

Python can be inline (`index.handler`) or packaged (`app.handler`); SAM is optional, not required by the language.

```python
import base64

def handler(event, context):
    messages = event["Messages"]
    if not isinstance(messages, list):
        raise TypeError("Expected UDP Gateway Messages array")
    replies = []
    for message in messages:
        payload = base64.b64decode(message["Data"], validate=True)
        replies.append({
            "Tag": message["Tag"],
            "Data": base64.b64encode(payload).decode("ascii"),
        })
    return {"Replies": replies}
```

This deliberately surfaces invalid base64. In a production handler, explicitly decide whether one malformed protocol message fails the invocation or is logged and excluded; do not silently discard it. Log tags and error categories rather than raw credentials/payloads.

## Go: base64 processing

Use `github.com/aws/aws-lambda-go/lambda` with a supported Go toolchain and an OS-only Lambda runtime (`provided.al2023`). Keep dependency versions pinned by the project.

```go
package main

import (
    "context"
    "encoding/base64"
    "fmt"

    "github.com/aws/aws-lambda-go/lambda"
)

type Message struct {
    Tag  string `json:"Tag"`
    Data string `json:"Data"`
}

type Request struct {
    Messages []Message `json:"Messages"`
}

type Reply struct {
    Tag  string `json:"Tag"`
    Data string `json:"Data"`
}

type Response struct {
    Replies []Reply `json:"Replies"`
}

func handler(ctx context.Context, request Request) (Response, error) {
    if request.Messages == nil {
        return Response{}, fmt.Errorf("expected Messages array")
    }
    replies := make([]Reply, 0, len(request.Messages))
    for _, message := range request.Messages {
        payload, err := base64.StdEncoding.DecodeString(message.Data)
        if err != nil {
            return Response{}, fmt.Errorf("packet %q: invalid base64: %w", message.Tag, err)
        }
        replies = append(replies, Reply{
            Tag: message.Tag,
            Data: base64.StdEncoding.EncodeToString(payload),
        })
    }
    return Response{Replies: replies}, nil
}

func main() { lambda.Start(handler) }
```

An allocated empty slice serializes as `[]`, not `null`. Build a Linux `bootstrap` for the selected architecture. If using SAM's Makefile builder, declare `Metadata: { BuildMethod: makefile }` on the function and implement `build-<LogicalId>`; a Makefile alone does not select that builder. Otherwise use the repository's normal build/package workflow.

## .NET SDK 2.x: typed async handler

Current SDK/template source targets .NET 10 and templates reference `Proxylity.UdpGateway.LambdaSdk` 2.0.0. Verify package feed availability and project compatibility before selecting versions; older examples may still pin SDK 1.x.

Recommended scaffolding:

```bash
dotnet new install Proxylity.Templates
dotnet new proxylity-udp-async -n MyUdpService
# Or NativeAOT:
dotnet new proxylity-udp-async-aot -n MyUdpService
```

Inspect generated package versions before restoring/building. Reference `Amazon.Lambda.Core` explicitly in the handler project and align its version with the selected SDK; do not assume a project reference to SDK source supplies its private build dependencies. Do not assume installing a template package installs SAM, a Linux compiler, or the matching .NET SDK.

Handler and managed entry point:

```csharp
using Amazon.Lambda.Core;
using Proxylity.UdpGateway.LambdaSdk;

[assembly: LambdaSerializer(typeof(UdpGatewayLambdaJsonSerializer))]

namespace MyUdpService;

public sealed class Handler : IUdpGatewayHandlerAsync
{
    public Task<UdpGatewayReply> HandleAsync(
        UdpGatewayMessage message, ILambdaLogger logger)
    {
        logger.LogLine($"Received packet with {message.Data.Length} bytes");
        return Task.FromResult(message.Reply(message.Data));
    }
}

public static class Function
{
    private static readonly Handler Handler = new();

    public static Task<UdpGatewayBatchResponse> FunctionHandler(
        UdpGatewayBatchRequest request, ILambdaContext context) =>
        UdpGatewayBatchProcessor.ProcessAsync(Handler, request, context);
}
```

Use `message.NoReply()` when no response is needed. Synchronous handlers implement `IUdpGatewayHandler` and use `UdpGatewayBatchProcessor.Process`.

Important SDK details:

- `UdpGatewayBatchRequest.Messages` and response `Replies` are lists, not arrays.
- `message.DataString` maps to wire JSON `Data`; `message.Data` is decoded `byte[]`. Do not base64-decode it again.
- `message.Reply(bytes)` preserves the tag/formatter and supplies reply metadata. SDK 2.x's semantic reply methods replace older raw-byte handler returns.
- The checked SDK byte decoder supports `base64`, `hex`, `utf8`, `ascii`, not protocol-aware object `Data` (`coap`, `coap+`, `syslog`). Use a raw JSON handler for those formats unless the installed SDK explicitly supports them. The CDK NuGet package is infrastructure tooling, not a replacement handler SDK.
- Use **`UdpGatewayLambdaJsonSerializer`**, not the default AWS serializer, for the SDK models. It includes source-generated serialization and handles empty base64 payloads.
- `ProcessAsync` runs per-message handlers in parallel and converts per-message exceptions to no-reply results. Do not assume that throwing inside a handler fails the whole Lambda batch. Explicitly log/measure failures; if batch failure is required, implement that policy instead of relying on this helper.
- Do not assume SDK models retain every wire metadata field. Use a raw event model when you need fields such as `Inner` or ingress routing context that the typed model does not expose.

### NativeAOT bootstrap

The AOT template supplies an executable, `PublishAot`, runtime support dependencies, and `provided.al2023` / `bootstrap`. Its bootstrap is:

```csharp
using Amazon.Lambda.RuntimeSupport;
using Proxylity.UdpGateway.LambdaSdk;

namespace MyUdpService;

public static class Program
{
    public static async Task Main()
    {
        await LambdaBootstrapBuilder
            .Create<UdpGatewayBatchRequest, UdpGatewayBatchResponse>(
                Function.FunctionHandler, new UdpGatewayLambdaJsonSerializer())
            .Build()
            .RunAsync();
    }
}
```

Build in a compatible Linux environment for the Lambda architecture. Do not invent an annotations-generated handler name or use reflection-based serializers as an AOT shortcut.

### Raw JSON alternative

For managed .NET, a `JsonObject` handler with the standard AWS System.Text.Json serializer can implement the wire contract directly. This is a different serialization path from the SDK. For NativeAOT, explicitly configure source-generated serialization for your actual models/runtime bootstrap; do not label an arbitrary reflection-based `JsonObject` example as AOT-ready.

## WireGuard: raw inner IP packet handler

Use `proxylity-wg-async` or `proxylity-wg-async-aot` for the SDK's `DecapsulatedHandler` path. That base class parses **complete inner IP packets**, dispatches UDP/TCP/ICMPv4/ICMPv6, and returns complete response IP packet bytes. Wire it through `UdpGatewayBatchProcessor.ProcessAsync`, not a nonexistent `HandleBatchAsync`.

The key override signature is:

```csharp
public override Task<byte[]?> HandleAsync(
    PacketDotNet.UdpPacket packet,
    RemoteEndpoint remote,
    ILambdaLogger logger)
```

Copy the full packet-construction pattern from the current tunnel template: reverse source/destination IPs and ports, attach the transport payload, update transport/IP checksums, and return the parent IP packet's bytes. Return `null` for no reply. A bare UDP payload is not a complete IP reply.

Do **not** set `DecapsulatedDelivery: true` for this raw-IP parsing path. That listener setting instead exposes application payloads with `Inner` addressing metadata and calls for the matching application-level handler/reply contract.

## Step Functions Express: valid JSONata echo

This complete ASL definition works with a base64 destination and preserves the array shape for zero, one, or many messages:

```json
{
  "QueryLanguage": "JSONata",
  "StartAt": "BuildReplies",
  "States": {
    "BuildReplies": {
      "Type": "Pass",
      "Output": {
        "Replies": "{% [$states.input.Messages.{\"Tag\": Tag, \"Data\": Data}] %}"
      },
      "End": true
    }
  }
}
```

Use `$states.input`, not `States.input`. Do not put JavaScript/object-projection syntax in a JSONPath `Parameters` expression. JSONata states use `Output`/`Arguments`/`Assign` as applicable, not JSONPath-only fields.

For an Express SAM state machine set `Type: EXPRESS`, its execution role, definition, and appropriate logging policy. The Proxylity destination role separately needs `states:DescribeStateMachine` and `states:StartSyncExecution`.

Validate ASL with `aws stepfunctions validate-state-machine-definition --definition file://state-machine.asl.json --type EXPRESS` when AWS access is available. Measure actual execution latency; Express avoids Lambda initialization but does not guarantee fixed response times.

## Lambda response streaming

Set `Arguments.UseResponseStreaming: true` and use an AWS-supported response-streaming implementation. A normal buffered handler does not become streaming because the destination flag is set.

The response contract is still a JSON object containing a `Replies` array. Emit reply objects incrementally within that array, preserve each `Tag`, use the destination formatter, and finish valid JSON. Do not substitute SSE, NDJSON, HTTP metadata framing, or raw UDP bytes unless the deployed adapter explicitly supports it. Test a first reply before function completion and additional replies, not just a final buffered response.

Use a runtime-supported streaming API (for example Node's `awslambda.streamifyResponse` in Lambda). Ordinary .NET SDK batch-return handlers above are buffered and do not implement streaming. Keep `UseAsyncInvoke` false and grant `lambda:InvokeFunction`. Account for function timeout, client reachability/session lifetime, backpressure, and AWS streaming charges/quotas.

## Lambda MicroVM HTTP application
A MicroVM image destination runs an ordinary HTTP server, not a Lambda handler. Listen on **port 8080** (fixed). Proxylity POSTs `{"Messages":[...]}` using the same request packet objects as Lambda functions, and the application returns HTTP 200 with `{"Replies":[{"Tag":"<message Tag>","Data":"..."}]}` (an empty array when there is no reply). Preserve each `Tag` and encode `Data` with the destination `Formatter` (`base64` by default). A MicroVM keeps its memory between requests, so per-client state can live in the process; it is lost when the MicroVM is terminated (at most 8 hours), so persist anything durable elsewhere.

Optional lifecycle hooks must be served on a **different port** (the example uses 9000) so they cannot be reached with the port 8080 token Proxylity holds. In SAM, enable `Hooks.MicrovmHooks.Run`; Lambda requires the `/ready` build hook whenever a hook is enabled, and routes traffic only after `/run` returns. Lambda POSTs `{"microvmId":"...","runHookPayload":"<JSON string>"}` to the run hook (path `/aws/lambda-microvms/runtime/v1/run` in the example). Proxylity's payload contains `Version`, `DestinationName`, `ImageArn`, `TenantId` (or null), `Region`, `Formatter`, `Port`, `StartedAt` and `ExtraData` (the `RunHookExtraData` argument, or null), never credentials. Read per-MicroVM values in `/run`, not at startup: the image is snapshotted after startup, so startup values are identical in every MicroVM. Keep `/run` free of once-per-tenant side effects (a duplicate MicroVM can start briefly), and return an error from `/run` only to deliberately fail the start.

```js
const http = require('http');
http.createServer((req, res) => {
  const chunks = [];
  req.on('data', (c) => chunks.push(c));
  req.on('end', () => {
    const { Messages = [] } = JSON.parse(Buffer.concat(chunks).toString() || '{}');
    const Replies = Messages.map((m) => ({ Tag: m.Tag, Data: m.Data })); // echo
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ Replies }));
  });
}).listen(8080);
```

Use the `lambda-microvm` example for a complete image (Dockerfile, hooks and SAM template). Do not return non-2xx for ordinary packet problems; a failed delivery makes Proxylity check the MicroVM state, and errors on a running MicroVM never start a new one.