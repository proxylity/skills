# Designing CoAP applications with UDP Gateway

Use this guide when selecting a device protocol or building a CoAP application, not only when asked to decode a packet. Keep the [packet contract](./PACKET-FORMAT.md) as the source for envelope fields, Content-Format mappings, CBOR wrappers, and formatter errors; this guide covers design and implementation choices.

## 1. Evaluate CoAP before inventing a protocol

CoAP offers compact resource-oriented requests, standard methods/status codes, content types, discovery, and optional observation/block-wise extensions. UDP Gateway removes the need to operate listener servers; `coap+` additionally translates supported content to JSON values that AWS applications can use directly. Neither removes application protocol or security responsibilities.

| Requirement | Consider | Check before choosing |
|---|---|---|
| Constrained native devices, small readings, resource reads/writes | CoAP over UDP Gateway with `coap+` | Client library, datagram budget, retry/loss tolerance, secure transport |
| JSON-friendly cloud code with compact device encoding | CoAP + CBOR or SenML CBOR | Schema/units, exact numeric range, formatter mapping, client support |
| Existing custom UDP binary protocol or byte-exact payload forwarding | Existing protocol + `base64`, or CoAP + `coap` | Preserve compatibility; do not force a migration solely for formatter convenience |
| Browser-facing APIs, large documents, conventional web integrations | HTTP/HTTPS | Browsers do not have arbitrary UDP sockets; no universal CoAP proxy is supplied |
| Persistent brokered pub/sub, topic ecosystem, offline-session needs | MQTT and the chosen broker's QoS/session features | CoAP Observe is not an MQTT broker, retained message, or durable offline queue |
| Ordered reliable byte stream, bulk transfer | HTTP/TCP or another suitable transport | CoAP block-wise transfer is an application extension, not free stream reliability |

Compare measured airtime, total bytes including security, power, latency, request loss, cloud cost, and operational complexity. Compact framing does not establish a universal battery, latency, or price improvement. Preserve an existing suitable HTTP/MQTT integration unless the user approves migration.

## 2. Establish the resource and content contract

Define stable resource paths and supported methods rather than inventing packet opcodes. For example:

| Resource | Method | Representation / behavior |
|---|---|---|
| `/.well-known/core` | GET | Link-format discovery (Content-Format 40), advertise only implemented capabilities |
| `/status` | GET | Small CBOR status object (60) or agreed JSON representation (50) |
| `/readings` | POST | Validated reading with device identity, measurement time, units, and application event ID |
| `/config` | GET / PUT | Read or replace authorized configuration; version/precondition policy where supported |

- GET is safe; PUT should express an idempotent replacement. POST retries can repeat effects: use a durable application operation ID and atomic deduplication for commands/ingestion.
- Choose response codes intentionally: `2.05` Content for reads, `2.04` Changed for an applied update, appropriate `4.xx` for client errors, and `5.xx` for backend failure. A transport ACK alone does not mean a command completed or data was persisted.
- Specify Content-Format for request bodies and response representations. Use Accept (option 17) when negotiating response formats, and implement or explicitly reject unsupported negotiation; do not infer response format blindly from a body that may be absent.
- Validate decoded values, ranges, units, object/array shape, and authorization. Formatting does not make a payload trustworthy. `PayloadError` means the payload is base64 fallback, not the declared content type.
- Bound payload sizes to the path MTU and client/service limits, including DTLS/tunnel overhead. Avoid IP fragmentation. Decide explicitly whether to implement block-wise transfers or reject oversized operations.

### Choose the representation

- **JSON (50):** straightforward for existing web/device libraries and debugging.
- **CBOR (60):** compact binary on the device, JSON values in the cloud through `coap+`. Use stable keys; integer keys arrive as decimal property names. Reserved wrappers preserve values without plain JSON equivalents, but re-encoding is not byte-exact.
- **SenML JSON/CBOR (110/112), SenSML (111/113):** standard measurement records with names, units, and time/base fields; prefer these when shared measurement semantics help interoperability. The formatter translates labels, not application meaning or base-value resolution.
- **Text (0), link-format (40), XML (41):** use when the resource/client needs them; XML remains a string, not a parsed document.
- **`coap` rather than `coap+`:** keep base64 payload bytes for unsupported media types, byte-level signatures, opaque/encrypted application content, or exact encoding requirements. Unknown/absent Content-Formats under `coap+` also remain base64.

Changing from `coap` to `coap+` changes recognized payloads from base64 strings into decoded values. Update handlers, consumers, schemas, and replies together; do not silently migrate an existing destination.

## 3. Pick an AWS processing pattern

| Pattern | Use for | Important boundary |
|---|---|---|
| Synchronous Lambda with `coap+` | Resource routing, validation, authorization, read/write logic, immediate CoAP responses | Application returns CoAP object `Data` with the original packet `Tag` |
| Step Functions Express | Bounded request/response orchestration over decoded fields | Execution latency must fit the CoAP exchange budget; return the `Replies` envelope |
| Direct EventBridge, SQS/SNS, DynamoDB, S3/Firehose destinations | Telemetry storage, routing, analytics without a decoding Lambda | These deliveries do not generate CoAP ACKs or application success responses |
| Async Lambda / Standard workflow + PacketSource | Long operations and delayed replies/notifications | Requires explicit application exchange state, outbound addressing, egress/session context |

For code-free telemetry, `coap+` lets EventBridge rules inspect `Data.Payload`, DynamoDB store maps, and Athena query archived JSON. Those services do not validate device identity, deduplicate application effects, or implement a CoAP server. Avoid sending the same ingress packet to both a side-effecting direct destination and a handler that independently persists it unless duplication is intentional and controlled.

For CDK, use `Listener` with the appropriate `ListenerProtocol` and `new LambdaDestination({ fn, formatter: Formatter.COAP_PLUS })` (or the selected direct destination). The formatter belongs to the destination, not the protocol factory. For CloudFormation, set destination `Formatter: "coap+"`. See [CDK](./CDK.md) and [destinations/IAM](./DESTINATIONS.md); the base64 starter handler must be replaced, not just its formatter.

### Worked example: a read-only CON profile

This synchronous Node.js handler serves `GET /status` as CBOR and discovery as link-format. It demonstrates object-valued `Data`, batch correlation, and formatter errors without inventing persistence or command success. It deliberately supports **CON requests only**, with no Accept negotiation, queries, proxying, Observe, or block-wise support. Use clients configured for this narrow profile; it is not a general-purpose CoAP server.

```javascript
exports.handler = async (event) => {
  if (!Array.isArray(event.Messages)) {
    throw new TypeError("Expected UDP Gateway Messages array");
  }
  const Replies = [];
  for (const message of event.Messages) {
    const request = message.Data;
    if (typeof message.Tag !== "string" || !request ||
        typeof request !== "object" || Array.isArray(request)) {
      throw new TypeError("Expected tagged CoAP object Data");
    }
    if (request.Error) {
      console.warn("Malformed CoAP request", { Tag: message.Tag, Error: request.Error });
      continue;
    }
    if (request.Type !== 0) {
      if (request.Type === 1) {
        console.warn("NON request unsupported by this CON-only example", { Tag: message.Tag });
      }
      continue;
    }
    if (!Number.isInteger(request.Code) || request.Code < 1 || request.Code > 31) {
      console.warn("Not a resource request in this example", { Tag: message.Tag });
      continue;
    }
    let response;
    if (request.PayloadError) {
      console.warn("Invalid CoAP payload", { Tag: message.Tag, Error: request.PayloadError });
      response = { Code: "4.00", ContentFormat: 0, Payload: "invalid payload" };
    } else if ((request.Options || []).some(option =>
      option.Number % 2 === 1 && option.Number !== 11)) {
      response = { Code: "4.02", ContentFormat: 0, Payload: "unsupported critical option" };
    } else if (request.Path !== "/status" && request.Path !== "/.well-known/core") {
      response = { Code: "4.04", ContentFormat: 0, Payload: "not found" };
    } else if (request.Method !== "GET") {
      response = { Code: "4.05", ContentFormat: 0, Payload: "method not allowed" };
    } else if (request.Path === "/.well-known/core") {
      response = {
        Code: "2.05", ContentFormat: 40,
        Payload: [{ href: "/status", rt: "service-status", ct: 60 }],
      };
    } else {
      response = { Code: "2.05", ContentFormat: 60, Payload: { status: "ok" } };
    }
    Replies.push({
      Tag: message.Tag,
      Data: { Type: 2, MessageId: request.MessageId, Token: request.Token, ...response },
    });
  }
  return { Replies };
};
```

The status is an application liveness example, not a backend health guarantee. Empty CON pings and inbound responses are outside this resource-only profile and produce no reply; add CoAP ping/RST handling if clients need it. `Options` are already parsed by the formatter; unsupported critical options (odd option numbers, except supported Uri-Path 11) yield Bad Option. Elective options can be ignored; an Observe request receives an ordinary response without an Observe option, not a subscription. Discovery intentionally does not advertise `obs`.

The handler relies on the gateway's decoded CoAP headers. Do not copy incoming Uri-Path/Observe/block options wholesale into replies. A CON piggybacked ACK uses the request's message ID/token; ACK/RST packets are not new resource requests. A NON response needs its own server message ID, not blindly the request ID. Add proper NON handling and exchange state if required by the client profile. `Tag` is gateway routing correlation, while the CoAP token is client exchange correlation; neither is an authenticated device ID.

## 4. Own reliability and longer-lived exchanges

- **CON/retries/duplicates:** specify bounded retransmission/backoff and maximum exchange lifetime. Do not assume formatter parsing supplies automatic ACKs, duplicate suppression, or application retries. Persist exchange/idempotency state where needed across concurrent Lambda invocations and regions; a process-local map is insufficient.
- **Slow work/separate response:** a prompt empty ACK has code 0 and no token/payload; it acknowledges a CON message but does not finish the request. A later separate response uses the original request token and a server-assigned message ID. PacketSource has no synchronous `Tag` routing: retain authorized remote/tunnel addresses and ingress egress-region context, and handle confirmation/retry state yourself.
- **Observe:** implement registration/cancellation, token/client/resource keys, expiry, sequence freshness, notification scheduling, and CON acknowledgement/RST handling. Store subscriptions durably with access control; a Lambda return or formatter does not create an observation.
- **Block-wise:** implement Block1/Block2 negotiation, offsets, ordering, size limits, expiry, and representation consistency, or explicitly reject unsupported critical options. Decoded content assumes a complete content payload; do not assume `coap+` reassembles blocks or independently decodes fragments. For a block-transfer implementation, consider `coap` with application-managed assembly/encoding.
- **Server push:** PacketSource can send an explicitly addressed CoAP notification but does not establish NAT reachability, a durable client session, or Observe state. Verify active DTLS/tunnel sessions and the actual deployed PacketSource support for the transport; expire stale addresses/subscriptions.

See the [architecture reference](./ARCHITECTURE.md) for PacketSource registration, `EgressRegion`, transport/session constraints, and regional routing. Treat the [CoAP examples](./EXAMPLES.md) as patterns to adapt, not proof that those lifecycle features are automatic.

## 5. Secure the application boundary

Use DTLS for compatible CoAP clients when confidentiality and authenticated transport are required; use WireGuard only when clients support that tunnel and its operational model. Plain CoAP/UDP is not encrypted. DTLS termination at the gateway is not end-to-end encryption through the cloud backend.

Restrict actual outer source CIDRs, provision/rotate device credentials securely, and map validated identity to resource/tenant permissions. Do not trust a JSON device ID, source IP, CoAP token, or claimed resource path as authentication. Confirm how authenticated transport identity reaches the application before basing authorization on it. Do not assume arbitrary PSK identity fields are exposed in events.

OSCORE or signed/opaque payloads need a separately verified end-to-end design; `coap+` does not decrypt or validate them. Parsing/re-encoding can change signed bytes. Limit public discovery detail and response sizes, rate-limit appropriately, and avoid using untrusted requests for reflection/amplification. Keep replay-sensitive early data disabled for non-idempotent commands unless explicit replay protection is designed.

## 6. Verify the actual protocol outcome

1. Locally test empty/multi-message batches, distinct gateway tags and CoAP tokens, valid JSON/CBOR/SenML values, unsupported formats/options/methods, malformed packets, `PayloadError`, and invalid application schemas.
2. With an authorized deployed endpoint and a real CoAP client, test a CON GET, decoded content, discovery, and expected error codes. For the example, request `/status` without Accept and decode its Content-Format 60 response as CBOR; request `/.well-known/core` and verify the link document on the wire.
3. Check actual message types, message IDs, tokens, options, encoding, and response size. Local handler tests cannot prove the gateway's wire encoding or a working DTLS exchange.
4. Inject packet loss, duplicate requests, and concurrent/retried operations. Verify one application effect, bounded retry/load, and explicit failure reporting. A successful UDP send, Lambda invocation, or empty ACK is not proof of persistence.
5. If implementing NON, separate responses, Observe, or blocks, test their complete lifecycles, stale state, cancellation, restarts, expiry, NAT/session loss, and multi-region ownership. Do not declare them supported based on a single successful packet.
6. Measure cold/warm backend latency plus destination batching delay against the chosen CoAP timers; inspect formatter/delivery errors and protect payloads in logs. Prefer immediate bounded work when piggybacking; design separate responses when the latency budget cannot be met.

## Standards and current service contract

- [RFC 7252: CoAP](https://www.rfc-editor.org/rfc/rfc7252.html): methods, options, messages, request/response semantics.
- [RFC 6690: link-format discovery](https://www.rfc-editor.org/rfc/rfc6690.html).
- [RFC 7641: Observe](https://www.rfc-editor.org/rfc/rfc7641.html).
- [RFC 7959: block-wise transfers](https://www.rfc-editor.org/rfc/rfc7959.html).
- [RFC 8428: SenML](https://www.rfc-editor.org/rfc/rfc8428.html).
- [Payload formatter documentation](https://www.proxylity.com/docs/destinations/formatters.html): supported content mappings and errors, not a promise of full CoAP server behavior.
