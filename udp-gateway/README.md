# UDP Gateway Skill

A portable [Agent Skill](https://agentskills.io/) that helps AI agents design, implement, deploy, and troubleshoot [Proxylity UDP Gateway](https://proxylity.com) solutions on AWS.

## What it does

Guides agents through the full workflow — gathering requirements, choosing a pattern, generating CloudFormation/SAM templates, writing packet handler code (Lambda, Step Functions) or configuring direct destinations (EventBridge, SQS, Kinesis, DynamoDB, S3, Firehose, CloudWatch Logs, API Gateway), deploying, and testing. Covers WireGuard encryption, CoAP, batching, multi-region deployment, and the full UDP packet request/response format.

## Usage

This is a portable [Agent Skill](https://agentskills.io/) — compatible with GitHub Copilot, Claude Code, Cursor, Gemini CLI, and [many other agents](https://agentskills.io/#clients). Clone or reference the `udp-gateway/` folder and point your agent at it following your agent's skill installation instructions.

## Requirements

- An AWS account subscribed to [Proxylity UDP Gateway](https://aws.amazon.com/marketplace/pp/prodview-cpvl5wgt2yo2e) on AWS Marketplace
- AWS CLI configured with account credentials
- SAM CLI (required only for compiled Lambda runtimes: .NET NativeAOT, Go, Java, Rust)

## Related

- [Proxylity website](https://proxylity.com)
- [proxylity/examples](https://github.com/proxylity/examples) — canonical working templates and handlers

## License

MIT — see [LICENSE](LICENSE)
