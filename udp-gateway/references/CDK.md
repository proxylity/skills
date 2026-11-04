# AWS CDK constructs

Use the published [Proxylity CDK library](https://github.com/proxylity/cdk-udp-gateway) in an existing CDK v2 project rather than rebuilding its custom-resource wrappers. Both L1 and L2 are available from the same package.

## Packages and language bindings

| Language | Install in the project's dependency workflow | Import / namespace |
|---|---|---|
| TypeScript / JavaScript | `npm install @proxylity/cdk-udp-gateway` | `@proxylity/cdk-udp-gateway` |
| Python | `pip install proxylity-cdk-udp-gateway` | `import proxylity_cdk_udp_gateway as udp` |
| C# / .NET | `dotnet add package Proxylity.CDK.UdpGateway` | `using Proxylity.CDK.UdpGateway;` |

Registry pages: [npm](https://www.npmjs.com/package/@proxylity/cdk-udp-gateway), [PyPI](https://pypi.org/project/proxylity-cdk-udp-gateway/), [NuGet](https://www.nuget.org/packages/Proxylity.CDK.UdpGateway).

Inspect the manifest and lockfile before choosing a version; preserve the project's versioning policy. The reviewed release is **0.2.3**, including `Formatter.COAP_PLUS` and `Formatter.SYSLOG`. Its npm peer requirements are `aws-cdk-lib ^2.160.0` and `constructs ^10.0.0`; check the selected release's requirements in each language. Python and .NET bindings use jsii and need a supported Node.js runtime as well as their language toolchain. Do not confuse these infrastructure packages with the `Proxylity.UdpGateway.LambdaSdk` handler package or `Proxylity.Templates`.

TypeScript uses camelCase properties and methods; Python uses snake_case (`ListenerProtocol.udp()`, `client_restrictions`, `LambdaDestination(fn=...)`); C# uses PascalCase (`ListenerProtocol.Udp()`, `ListenerProps`, `ClientRestrictions`, `LambdaDestinationProps.Fn`). Enum member spellings also vary by binding. Read the installed API/types rather than mechanically copying TypeScript into Python or C#. Java and Go are not among the three verified published bindings.

## Choose the layer

| Surface | Use for | Responsibilities |
|---|---|---|
| L2 `Listener` + `ListenerProtocol` | Normal new CDK infrastructure | One typed protocol factory; inline destinations; config resolution; generated IAM/dependencies |
| L2 specialized destinations | Typed AWS resource targets | Service-specific delivery grants and formatter defaults |
| L2 `SnsPacketSource` | SNS-backed server push | Binds `listener` and `topic`; auto-creates subscription role unless supplied |
| L2 `RegionalArnRegistration` | Register regional compute for a global destination | Takes `destinationName`, `arn`, optional `ingressRegionKey` (defaults to stack region; `"*"` is fallback) |
| L1 `CfnListener` | Exact custom-resource properties or advanced unsupported L2 combinations | Caller supplies config, IAM, dependencies, and valid service properties |
| L1 `CfnDestinationArn`, `CfnPacketSource` | Exact regional registration / PacketSource properties | Faithful custom-resource mapping without derived IAM |

`ListenerProtocol.udp()`, `.wireGuard({...})`, `.dtls({...})`, and `.webRtc({...})` produce configurations for one `Listener`; do not invent separate `UdpListener`/`WireGuardListener` classes or combine protocols. A factory's presence does not establish deployed regional availability.

Specialized destinations include `LambdaDestination`, `SqsDestination`, `KinesisStreamDestination`, `FirehoseDestination`, `S3Destination`, `SnsDestination`, `StateMachineDestination`, `DynamoDbDestination`, `ApiGatewayDestination`, `CloudWatchLogsDestination`, `EventBridgeDestination`, `IotDataDestination`, and `LocationTrackerDestination`. Check each constructor's exact target property; they are not all named `resource`. Destination objects such as `new LambdaDestination({ fn })` are bound by the listener, not constructed with `(scope, id, props)`.

For L1, `ProxylityConfig.forStack(scope)` emits the account/region mapping once per stack; `serviceToken()`, `serviceRole()`, and `apiKey()` resolve its values. L2 `Listener` calls this helper automatically unless given `proxylityConfig`. L1 uses camelCase input properties and serializes service PascalCase keys. Destinations remain inline in `CfnListener.destinations`: there is **no `CfnDestination`** or standalone `Custom::ProxylityUdpGatewayDestination`.

## TypeScript stack example

This base64 echo stack requires a client CIDR with no public-access default. It creates bounded-retention log groups and explicitly enables destination metrics. Use a CDK v2 release exposing `Runtime.NODEJS_22_X`; the library's minimum peer version alone does not provide that newer runtime constant. Adapt the runtime to the target region/project without downgrading to a retired runtime.

```typescript
import { CfnOutput, CfnParameter, Stack, StackProps } from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import {
  Formatter, LambdaDestination, Listener, ListenerProtocol,
} from '@proxylity/cdk-udp-gateway';

export class UdpEchoStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);
    const clientCidr = new CfnParameter(this, 'ClientCidrToAllow', { type: 'String' });
    const handlerLogs = new logs.LogGroup(this, 'HandlerLogs', {
      retention: logs.RetentionDays.TWO_WEEKS,
    });
    const deliveryLogs = new logs.LogGroup(this, 'DeliveryErrorLogs', {
      retention: logs.RetentionDays.TWO_WEEKS,
    });
    const fn = new lambda.Function(this, 'Echo', {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: 'index.handler',
      logGroup: handlerLogs,
      code: lambda.Code.fromInline(`
        exports.handler = async (event) => {
          if (!Array.isArray(event.Messages)) {
            throw new TypeError("Expected UDP Gateway Messages array");
          }
          return { Replies: event.Messages.map(({ Tag, Data }) => ({ Tag, Data })) };
        };
      `),
    });
    const listener = new Listener(this, 'UdpListener', {
      protocol: ListenerProtocol.udp(),
      clientRestrictions: { networks: [clientCidr.valueAsString] },
      destinations: [new LambdaDestination({
        fn,
        formatter: Formatter.BASE64,
        metricsEnabled: true,
        logGroupName: deliveryLogs.logGroupName,
      })],
    });
    new CfnOutput(this, 'Endpoint', { value: listener.endpoint });
  }
}
```

`listener.domain` is only the subdomain label; `listener.endpoint` includes `.proxylity.com` and the port. `listener.port` is a string token; use `portAsNumber` if a numeric token is needed. `destinationNames` is a list token: select with `Fn.select`, not JavaScript indexing. Protocol-specific getters must match the configured transport; do not expose signaling bearer tokens or private configuration in outputs.

For content-aware CoAP or syslog, set the destination's `formatter` to `Formatter.COAP_PLUS` or `Formatter.SYSLOG` and replace the base64-only handler with the [object-valued packet contract](./PACKET-FORMAT.md). Infrastructure formatter selection does not adapt application code. `ArgumentFormatter` is separate and allows only `BASE64`, `HEX`, `ASCII`, `UTF8` for tenant IDs, partition keys, group IDs, and topic suffixes.

## IAM ownership and escape hatches

- Specialized L2 destinations create roles trusting the configured Proxylity `ServiceRole`, scoped delivery grants, optional metrics/log-stream grants, and policy dependencies. Do not replace that trust with the Lambda execution principal or add duplicate roles.
- A supplied `role` is used **as-is**: automatic trust and grants are disabled. The caller must supply service delivery, logging, metrics, KMS permissions/key policies where needed, and ordering after separately attached policies. The function execution role remains separate.
- `ArnDestination` accepts exactly one of `arn` or `arnMap`, plus optional L1-shaped `arguments`. It cannot infer service permissions from an opaque ARN: provide a correctly configured role, or explicitly attach delivery grants to the generated role. Do not assume it has the specialized destination's IAM behavior.
- For multi-region registration, an `ArnDestination` with `arnMap: {}` defines the global empty-map destination. Regional stacks use its exported destination name with `RegionalArnRegistration`; this is not registration by listener ID/index. Regional compute roles/permissions still need explicit design.
- `listener.cfnListener`, `source.cfnPacketSource`, and `registration.cfnDestinationArn` expose L1 escape hatches. Inspect synthesis before using overrides; do not bypass the one-protocol rule or invent unsupported wire keys.

## Build, inspect, deploy

1. Restore dependencies through the project's package manager and run its language build/type-check plus CDK assertion tests. For new tests, inspect synthesized custom-resource keys, CIDRs, formatter values, trust, target-scoped IAM, and policy dependencies.
2. Run `cdk synth` using the project's app command/context. Confirm `Mappings.ProxylityConfig`, one protocol, inline destinations, formatter, and log retention. Synthesis does not contact the service to validate subscription/config availability.
3. Supply the actual client CIDR via the project's parameter/context workflow; inspect `cdk diff` before deployment. Bootstrap each account/region if required by the app's asset/role workflow.
4. With authorization, run `cdk deploy` through the existing workflow. A Proxylity-enabled/subscribed AWS account, credentials, regional customer configuration, and handler assets are still required. CDK does not grant service entitlement.
5. Test the returned endpoint with real protocol fixtures and check delivery-error logs/metrics. A successful synthesis or stack deployment is not proof of working replies.

The [design article](https://builder.aws.com/content/3Ktv7mjsIo0Ns7XFHw5ZOyTAx2j/from-custom-resources-to-constructs-designing-a-cdk-library-for-serverless-udp) explains the L1/L2 layering. The repository/package README still describes L1 alone; use the selected package's exported types/API for the L2 surface instead of treating that older description as an absence of L2.
