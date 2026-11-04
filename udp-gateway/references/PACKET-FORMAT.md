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
| CloudWatch Logs | Prefixed text for text formatters; full request-packet JSON for protocol-aware formatters | None |
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
- `Data`: a **string** for `base64`, `hex`, `utf8`, `ascii`; a **JSON object** for `coap`, `coap+`, `syslog`. Do not parse/stringify an object-valued `Data` a second time.
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
| `coap` | Parsed CoAP object; `Payload` is base64 | CoAP object; `Payload` is base64 |
| `coap+` | CoAP object; `Payload` decoded by Content-Format | CoAP object; `Payload` encoded by Content-Format |
| `syslog` | Parsed RFC 5424/3164 fields object | Fields object encoded into RFC 5424/3164 text |

Use base64 for arbitrary binary data, especially when bytes are not valid text. Do not depend on hex letter casing. For the checked .NET SDK handlers, `message.Data` decodes the first four formats and `message.Reply(bytes)` handles the matching output encoding. Use a raw JSON handler for protocol-aware object `Data` unless the installed SDK explicitly supports it.

These are destination and PacketSource formatters, not argument sub-formatters. Tenant IDs, partition keys, group IDs, and topic suffixes still accept only the four text encodings.

### CoAP

For protocol selection, resource design, a `coap+` handler, and application-owned reliability/security, load the [CoAP design guide](./COAP.md). This section defines the encoding contract.

Example synchronous reply for an ACK content response:

```json
{
  "Replies": [{
    "Tag": "opaque-coap-tag",
    "Data": {
      "Type": 2,
      "Code": "2.05",
      "MessageId": 12345,
      "Token": "AQI=",
      "Options": [
        { "Number": 12, "Value": "" }
      ],
      "Payload": "aGVsbG8="
    }
  }]
}
```

`Type` is numeric (0 CON, 1 NON, 2 ACK, 3 RST). Inbound `Code` is the raw integer (e.g. 1 = GET, 69 = 2.05); replies accept an integer or a code string such as `"2.05"`. `Method` and `Path` are inbound conveniences, ignored on output. Preserve the request token and choose the message ID/type according to CoAP semantics. Options are an array with numeric `Number` and base64 `Value`, not human-readable option-name/value strings. Repeated options remain separate array entries. `Token` and `Payload` are base64.

For option 12 (Content-Format), the example uses the empty byte representation of text/plain (0). Set reply `Data` directly to the CoAP object, **not** `JSON.stringify(...)`, `json.dumps(...)`, or base64 JSON. The `coap` formatter does not interpret Content-Format; `ContentFormat` and `PayloadDecoded` are not a content-aware encoding API for `coap`.

### Content-aware CoAP (`coap+`)

Use `coap+` when the application wants decoded content instead of base64 payload bytes. The message shape is the same as `coap`, with numeric `ContentFormat` promoted from option 12 when present and decoded content in **`Payload`**, not `PayloadDecoded`.

| Content-Format | Media type | `Payload` value |
|---|---|---|
| 0 | text/plain | UTF-8 string |
| 40 | application/link-format | Array of link objects |
| 41 | application/xml | Original XML markup string; not parsed or validated |
| 50 | application/json | JSON value |
| 60 | application/cbor | JSON mapping of CBOR |
| 110, 111 | application/senml+json, application/sensml+json | JSON value |
| 112, 113 | application/senml+cbor, application/sensml+cbor | SenML JSON records with standard label names |
| Other or absent | Unrecognized / unspecified | Base64 string, as with `coap` |

Example reply to a CON request carrying CBOR readings, with the original `Tag`, `MessageId`, and `Token`:

```json
{
  "Replies": [{
    "Tag": "opaque-coap-plus-tag",
    "Data": {
      "Type": 2,
      "Code": "2.04",
      "MessageId": 4660,
      "Token": "qrs=",
      "ContentFormat": 60,
      "Payload": { "0": "accepted" }
    }
  }]
}
```

In replies, prefer `ContentFormat` instead of manually constructing option 12; if both are set, option 12 wins regardless of property order. Text/XML require strings. JSON must be valid without duplicate property names. XML must be UTF-8; it is not sanitized or made safe by formatting.

CBOR integer map keys become decimal property names; canonical integer names encode back to integer keys. Non-JSON values use reserved `$cbor` wrappers (e.g. `{"$cbor":"bytes","value":"AQI="}` for bytes, or an `integer` wrapper with a decimal string for integers outside JSON's exact range). Mixed/colliding map keys require a `map` wrapper. Do not coerce large integers to JavaScript numbers or assume exact byte preservation: use `coap` for lossless payload bytes. Consult the [formatter documentation](https://www.proxylity.com/docs/destinations/formatters.html#coap-plus-cbor) for wrapper fields and link-format structures before generating them.

SenML CBOR translates standard labels to names such as `bn`, `n`, `u`, `v`; `vd` is unpadded base64url. Base values are not resolved. Unknown integer labels, invalid field types, and mandatory extensions are rejected. SenSML processes whole payloads, not an incremental application stream.

**Migration:** `coap` remains byte-oriented; switching to `coap+` is an explicit application contract change for recognized media types. Update request handling and reply payloads together, including downstream schemas. Unsupported/absent Content-Formats retain base64 behavior. Do not simply change the formatter on a handler that always base64-decodes `Payload`.

Observe subscription state, notification scheduling, confirmable-message retries, block-wise assembly, and authorization belong to your application. Parsing CoAP is not a full CoAP application server.

### Syslog (`syslog`)

Choose `syslog` to receive JSON fields from RFC 5424 and BSD-style RFC 3164 messages (detected per packet), or to generate syslog from JSON replies/PacketSource messages. Lowercase field names are significant.

| Field | Contract |
|---|---|
| `schema_version`, `parse_ok` | Currently `1`; boolean parse status |
| `format`, `version` | `rfc5424` or `rfc3164`; RFC 5424 version, otherwise null |
| `pri`, `facility`, `severity` | PRI 0-191; facility = PRI >> 3 (0-23), severity = PRI & 7 (0-7) |
| `facility_name`, `severity_name` | Names such as `local4`, `notice`; severity 0 is most urgent |
| `timestamp` | Device timestamp normalized to ISO 8601 UTC, or null |
| `hostname`, `app_name`, `proc_id`, `msg_id` | Header fields; RFC 3164 TAG/PID map to app/proc; msg_id null |
| `structured_data` | RFC 5424 object keyed by SD-ID, with string-valued parameters |
| `message`, `raw` | Parsed message; original text in `raw` on parse failure, otherwise raw null |

Every inbound field is present; unavailable values are null. Handle `parse_ok: false` explicitly, preserving `raw` for diagnostics/quarantine under the project's privacy policy. A malformed RFC 5424 message is not retried as RFC 3164, and a valid PRI can survive a parse failure. Invalid UTF-8 is replaced with U+FFFD; use a byte formatter if exact legacy bytes matter.

For example, the request packet's `Data` for an RFC 5424 notice can be:

```json
{
  "schema_version": 1,
  "parse_ok": true,
  "format": "rfc5424",
  "pri": 165,
  "facility": 20,
  "severity": 5,
  "facility_name": "local4",
  "severity_name": "notice",
  "version": 1,
  "timestamp": "2026-11-02T10:15:30.123Z",
  "hostname": "edge-01",
  "app_name": "gateway",
  "proc_id": "4321",
  "msg_id": "LINK",
  "structured_data": { "origin@32473": { "site": "hq" } },
  "message": "link down on eth1",
  "raw": null
}
```

RFC 3164 timestamps assume UTC/current year, or previous year if the result would be more than a day in the future. Use envelope `ReceivedAt` for retention, partitions, and alarms rather than trusting device time. Sender/listener addresses are in `Remote`/`Local`, not `Data`. Repeated structured-data parameters are comma-joined; repeated SD-IDs merge, so parsing is not a byte-preserving archival format.

For code-free ingestion, use S3/Firehose NDJSON with `Data` as an Athena struct, DynamoDB maps, EventBridge/SNS field filtering, or CloudWatch Logs JSON queries such as `filter Data.severity <= 3` (err and worse). Keep unparsed records observable rather than silently discarding them.

Example server-initiated syslog to a collector (publish to the registered PacketSource SNS topic with the required `EgressRegion` attribute):

```json
{
  "Messages": [{
    "Remote": { "Address": "203.0.113.10", "Port": 514 },
    "Formatter": "syslog",
    "Data": {
      "facility_name": "local0",
      "severity_name": "err",
      "hostname": "aws-bridge",
      "app_name": "forwarder",
      "message": "disk 92% full"
    }
  }]
}
```

Outbound fields are optional: `format` defaults to `rfc5424`, `version` to 1, and priority to `user.notice` (PRI 13). `pri` wins over numeric facility/severity, which win over names. A non-null `raw` sends that text verbatim and overrides all other fields. To modify a failed parse into a generated message, clear `raw`; `schema_version` and `parse_ok` are ignored on output. Header fields must meet printable-ASCII/no-spaces and protocol length limits. For RFC 3164, `msg_id` and structured data are not sent. With no timestamp, RFC 5424 emits `-`; RFC 3164 uses current time. This formatter does not add transport reliability or authenticate the claimed hostname.

### Formatter errors and validation

- Malformed CoAP is delivered as `Data: {"Error":"...", "Raw":"<base64>"}`. Handle/log it explicitly; `Raw` can be used to send original bytes unchanged.
- A `coap+` content decoding failure delivers the message with base64 `Payload` and `PayloadError`. Do not interpret that string as decoded content or echo it back with the same recognized Content-Format. Reject it, fix it explicitly, or use `coap` when byte-preserving forwarding is required.
- Unparsed syslog is delivered with `parse_ok: false` and original text in `raw`. Do not treat it as a valid parsed event just because delivery succeeded.
- Decoding problems are also destination errors; enable `MetricsEnabled` and `LogGroupName` with their IAM grants. This preservation behavior is not a guarantee against transport loss, filtering, or downstream delivery failure.
- Outbound encoding errors (string `Data` for an object formatter, invalid base64/wrappers, invalid syslog names/headers) are reported and that reply is not sent; other replies in the batch can still be sent.

Test valid/malformed CoAP, recognized/unknown/absent Content-Formats, mismatched payloads and `PayloadError`, RFC 5424/3164, null fields and `parse_ok: false`, invalid UTF-8, structured data, and mixed valid/invalid reply batches. Check actual client bytes, not just JSON serialization. See the [current formatter specification](https://www.proxylity.com/docs/destinations/formatters.html) for detailed encoding constraints.

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
