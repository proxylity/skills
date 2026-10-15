# Packet contracts and formatters

This is a practical contract reference, **not a complete versioned JSON Schema**. Exact optional metadata and transport details must be checked against a captured event and the deployed adapter. Older published schemas omit newer fields/formatters.

## Destination envelopes

| Destination | Input | Immediate replies |
|---|---|---|
| Synchronous Lambda | `{"Messages":[RequestPacket,...]}` | `{"Replies":[ResponsePacket,...]}` |
| Async Lambda | Same batch | None; return value ignored |
| Step Functions Express | Same batch | Execution output containing `Replies` |
| Step Functions Standard | Same batch | None; workflow is asynchronous |
| API Gateway POST | Same batch | HTTP response mapped to `Replies` |
| SNS / SQS | One packet JSON per message by default | None |
| EventBridge | One packet in event `detail` | None |
| Kinesis | Packet records | None |
| S3 / Firehose | NDJSON packet records | None |
| DynamoDB | Packet properties as item attributes | None |
| CloudWatch Logs | UTF-8 payload text as log events | None |
| IoT Data | Packet JSON in static mode; raw bytes in dynamic mode | None |
| Location tracker | Extracted device positions | None |

SQS `SendRaw` / `UseMessageAttributes` alter the default envelope. Queue-triggered Lambda receives an **AWS SQS event**, not a direct UDP Gateway batch; a downstream Lambda return value does not automatically become UDP replies. Use PacketSource explicitly for delayed replies.

## Request packet

```json
{
  "Tag": "opaque-tag",
  "Remote": {
    "IpAddress": "203.0.113.10",
    "Port": 45678
  },
  "Local": {
    "Domain": "ingress-1",
    "Port": 15678
  },
  "ReceivedAt": "2026-10-14T12:00:00Z",
  "Formatter": "base64",
  "Data": "AAEC/w=="
}
```

- `Tag`: opaque request/reply correlation value. Do not parse it, synthesize it, use it as authentication, or assume it is a durable application idempotency key.
- `Remote.IpAddress` / `Port`: outer sender endpoint. WireGuard may additionally supply `Remote.PeerKey`.
- `Local.Domain` / `Port`: listener endpoint context. The returned domain label is used with `.proxylity.com`.
- `ReceivedAt`: arrival timestamp where supplied.
- `Formatter`: encoding/formatter selected by the destination.
- `Data`: **string**, including when the formatter represents structured CoAP JSON.
- `IngressRegion`: preserve the routing context where supplied for async/session-bound egress. Verify whether it is at packet or envelope level in the actual event; it is not guaranteed by older schemas or typed SDK models.
- `Inner`: decapsulated tunnel addressing metadata when present. Keep the actual field values/types; do not invent a schema requiring string protocol/version values. Examples also use numeric IP protocol/version.

`Inner` can carry `SourceAddress`, `SourcePort`, `DestinationAddress`, `DestinationPort`, `Protocol`, and `Version`; non-UDP protocols need their appropriate representation. Do not treat an inner address as a public client source for CIDR restrictions.

## Synchronous response packet

For base64 echo:

```json
{
  "Replies": [{
    "Tag": "opaque-tag",
    "Data": "AAEC/w=="
  }]
}
```

Match the original `Tag`; the gateway uses it to route the reply. Reply `Data` is encoded with the **destination formatter**, not unconditionally base64. SDK replies additionally serialize formatter/generated-time metadata.

Use `{"Replies":[]}` for no response. Multiple input messages may produce zero, one, or multiple replies according to protocol needs. Test empty/single/multi-message batches and do not collapse arrays into a single object. A reply missing `Tag` is malformed, not a no-reply mechanism.

## Formatter symmetry

| Formatter | Inbound `Data` | Reply `Data` |
|---|---|---|
| `base64` | Standard base64 of bytes | Standard base64 of response bytes |
| `hex` | Hex-encoded bytes | Hex-encoded response bytes |
| `utf8` | UTF-8 decoded text | Response text |
| `ascii` | ASCII decoded text | ASCII response text |
| `coap` | Stringified parsed CoAP object | Stringified CoAP response object |

Use base64 for arbitrary binary data, especially when bytes are not valid text. Do not depend on hex letter casing. For .NET SDK handlers, `message.Data` decodes the first four formats and `message.Reply(bytes)` handles the matching output encoding. `coap` is not supported by that byte decoder.

### CoAP

Example formatter object for an ACK content response:

```json
{
  "Type": 2,
  "Code": "2.05",
  "MessageId": 12345,
  "Token": "AQI=",
  "Options": [
    { "Number": 12, "Value": "AA==" }
  ],
  "Payload": "aGVsbG8="
}
```

`Type` is numeric (0 CON, 1 NON, 2 ACK, 3 RST); `Code` uses CoAP code strings such as `"2.05"`. Preserve the request token and choose the message ID/type according to CoAP semantics. Options are an array with numeric `Number` and base64 `Value`, not human-readable option-name/value strings. `Token` and `Payload` are base64.

For option 12 (Content-Format), the example encodes text/plain (0). For a raw JSON handler, set reply `Data` to `JSON.stringify(coapResponse)` / `json.dumps(coap_response)`, **not** to the object itself and **not** to base64 of that JSON.

Recognized content formats can also include `ContentFormat` and `PayloadDecoded`. With a recognized content format, a reply may encode structured `PayloadDecoded`; otherwise use lossless base64 `Payload`. Verify supported content types rather than assuming arbitrary JSON/CBOR/SenML support in every deployment.

Observe subscription state, notification scheduling, confirmable-message retries, block-wise assembly, and authorization belong to your application. Parsing CoAP is not a full CoAP application server.

## WireGuard modes

After WireGuard decryption, distinguish:

1. **Raw inner IP packet path:** input bytes include the full IP packet. SDK `DecapsulatedHandler` parses these using `PacketDotNet.LinkLayers.Raw`; replies must be complete IP packets with correct checksums. The class name does not mean it accepts a bare UDP payload.
2. **`DecapsulatedDelivery: true`:** listener exposes application payload/protocol data with `Inner` metadata. Use application-level processing and the matching formatter. Do not feed this payload to a raw-IP parser.

WireGuard outer headers/encryption are managed by the gateway; normal tunnel delivery is not a request to implement WireGuard cryptography in Lambda.

## PacketSource messages differ from replies

PacketSource uses `{"Messages":[...]}`, explicit outbound addressing, and an SNS `EgressRegion` attribute. It does not use synchronous `Tag` routing.

```json
{
  "Messages": [{
    "Remote": { "Address": "203.0.113.10", "Port": 45678 },
    "Formatter": "base64",
    "Data": "AAEC/w=="
  }]
}
```

Note **`Remote.Address`**, not inbound `Remote.IpAddress`. In WireGuard, include `Remote.PeerKey`; for decapsulated application-payload delivery also supply outbound `Inner` addressing. Reverse request source/destination as appropriate; do not blindly copy `Inner` into a response.

See the architecture reference for registration, permissions, NAT/session lifetime, and `EgressRegion` routing. Confirm DTLS/WebRTC sourced-message session support in the deployed service before assuming the WireGuard message contract applies unchanged.
