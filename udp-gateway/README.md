# UDP Gateway Skill

A portable [Agent Skill](https://agentskills.io/) that helps AI agents design, implement, deploy, and troubleshoot [Proxylity UDP Gateway](https://proxylity.com) solutions on AWS.

## What it does

Guides agents through requirements, AWS CDK or CloudFormation/SAM infrastructure, Lambda and Step Functions handlers, direct AWS destinations, deployment, and round-trip testing. Covers UDP, WireGuard, DTLS, CoAP/coap+, syslog JSON, BREX filtering/extraction, SNS PacketSource push, regional registration, IoT Data, Location trackers, and listener/destination observability.

Includes current .NET SDK 2.x/template guidance, formatter-aware replies, Lambda async/streaming/tenant-isolation options, and availability-gated WebRTC guidance. [Verification notes](references/SOURCES.md) record the checked source revisions and known documentation discrepancies; local source support is not a deployment guarantee.

[CDK guidance](references/CDK.md) covers the npm, PyPI, and NuGet construct packages, L1/L2 selection, automatic IAM and escape hatches, and synthesis/deployment checks. The [packet reference](references/PACKET-FORMAT.md) covers object-valued protocol `Data`, content-aware CoAP migration, syslog field processing/sending, and malformed-packet handling.

[CoAP design guidance](references/COAP.md) helps agents evaluate CoAP for constrained-device telemetry, commands, and lightweight APIs before inventing custom UDP protocols. It covers HTTP/MQTT trade-offs, resource/content design, a tested `coap+` handler, discovery, and application-owned reliability, security, Observe, and block-wise transfers.

## Usage

This is a portable [Agent Skill](https://agentskills.io/) — compatible with GitHub Copilot, Claude Code, Cursor, Gemini CLI, and [many other agents](https://agentskills.io/#clients). Clone or reference the `udp-gateway/` folder and point your agent at it following your agent's skill installation instructions.

## Requirements

- A Proxylity-enabled AWS account with the required subscription/access for the target region
- AWS CLI configured with account credentials
- The handler's language toolchain when compiling code; a compatible Linux build environment for NativeAOT
- SAM CLI when using the SAM build/deploy workflow (optional; compiled artifacts can also be packaged/deployed through other tooling)
- For CDK: CDK v2, the matching construct package and language toolchain, plus a supported Node.js/jsii runtime (including Python/.NET apps)

## Starter

[assets/starter.template.json](assets/starter.template.json) provides a base64 UDP echo handler, explicit client CIDR parameter, delivery-error logging, metrics, and bounded log retention. It replies to every packet in a batch and safely handles empty batches. Supply the actual public client CIDR before deployment; the template has no open-access default.

## Validation

From the repository root, run:

```text
python tests/validate_skill.py
node tests/validate_handlers.cjs
cfn-lint udp-gateway/assets/starter.template.json
```

The Python checks use only the standard library; JavaScript checks require Node.js, and infrastructure linting requires an existing cfn-lint installation. Deployment and transport/session tests require an enabled AWS account and reachable client; local checks do not establish live service availability.

## Related

- [Proxylity website](https://proxylity.com)
- [proxylity/examples](https://github.com/proxylity/examples) — application patterns (verify versions and assumptions before copying)
- [proxylity/lambda-sdk-net](https://github.com/proxylity/lambda-sdk-net) — typed .NET handler contracts
- [proxylity/templates-net](https://github.com/proxylity/templates-net) — .NET project scaffolding
- [proxylity/cdk-udp-gateway](https://github.com/proxylity/cdk-udp-gateway) — L1/L2 AWS CDK constructs for TypeScript, Python, and .NET
- [Payload formatters](https://www.proxylity.com/docs/destinations/formatters.html) — coap/coap+, syslog, content mappings, and errors

## License

MIT — see [LICENSE](LICENSE)
