const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..", "skills", "udp-gateway");
const template = JSON.parse(
  fs.readFileSync(path.join(root, "assets", "starter.template.json"), "utf8")
);
const inlineCode = template.Resources.PacketHandler.Properties.InlineCode;
const [separator, lines] = inlineCode["Fn::Join"];
const markdown = fs.readFileSync(path.join(root, "references", "HANDLERS.md"), "utf8");
const snippets = [...markdown.matchAll(/^```javascript\r?\n([\s\S]*?)^```/gm)]
  .map(match => match[1]);

async function validate(source) {
  const context = { exports: {}, console: { log() {} } };
  vm.runInNewContext(source, context);
  const handler = context.exports.handler;
  const normalize = value => JSON.parse(JSON.stringify(value));
  assert.deepEqual(normalize(await handler({ Messages: [] })), { Replies: [] });
  const messages = [
    { Tag: "empty", Data: "" },
    { Tag: "binary", Data: Buffer.from(Array.from({ length: 256 }, (_, i) => i)).toString("base64") },
    { Tag: "unicode", Data: Buffer.from("hello \u2603").toString("base64") }
  ];
  assert.deepEqual(
    normalize(await handler({ Messages: messages })),
    { Replies: messages }
  );
  await assert.rejects(() => handler({}), /Expected UDP Gateway Messages array/);
  await assert.rejects(() => handler({ Messages: null }), /Expected UDP Gateway Messages array/);
}

async function validateCoap(source) {
  const warnings = [];
  const context = { exports: {}, console: { warn: (...args) => warnings.push(args) } };
  vm.runInNewContext(source, context);
  const invoke = async Messages => JSON.parse(JSON.stringify(
    await context.exports.handler({ Messages })
  ));
  const request = (Tag, overrides = {}) => ({
    Tag,
    Formatter: "coap+",
    Data: {
      Type: 0, Code: 1, MessageId: 4660, Token: "AQI=",
      Method: "GET", Path: "/status",
      Options: [{ Number: 11, Value: "c3RhdHVz" }],
      ...overrides
    }
  });
  assert.deepEqual(await invoke([]), { Replies: [] });
  const status = request("status");
  const discovery = request("discovery", {
    MessageId: 4661, Token: "AwQ=", Path: "/.well-known/core",
    Options: [
      { Number: 11, Value: "LndlbGwta25vd24=" },
      { Number: 11, Value: "Y29yZQ==" }
    ]
  });
  const result = await invoke([status, discovery]);
  assert.deepEqual(result, { Replies: [
    { Tag: "status", Data: {
      Type: 2, MessageId: 4660, Token: "AQI=",
      Code: "2.05", ContentFormat: 60, Payload: { status: "ok" }
    } },
    { Tag: "discovery", Data: {
      Type: 2, MessageId: 4661, Token: "AwQ=",
      Code: "2.05", ContentFormat: 40,
      Payload: [{ href: "/status", rt: "service-status", ct: 60 }]
    } }
  ] });
  assert.deepEqual(await invoke([status, status]), {
    Replies: [result.Replies[0], result.Replies[0]]
  });
  const cases = [
    [{ PayloadError: "invalid CBOR", Payload: "/w==" }, "4.00"],
    [{ Path: "/missing" }, "4.04"],
    [{ Code: 2, Method: "POST" }, "4.05"],
    [{ Options: [{ Number: 17, Value: "PA==" }] }, "4.02"],
    [{ Options: [{ Number: 23, Value: "" }] }, "4.02"],
    [{ Options: [{ Number: 15, Value: "YT0x" }] }, "4.02"]
  ];
  for (const [overrides, code] of cases) {
    const { Replies } = await invoke([request("error", overrides), status]);
    assert.equal(Replies.length, 2);
    assert.equal(Replies[0].Tag, "error");
    assert.equal(Replies[0].Data.Code, code);
    assert.equal(Replies[0].Data.ContentFormat, 0);
    assert.equal(typeof Replies[0].Data.Payload, "string");
    assert.deepEqual(Replies[1], result.Replies[0]);
  }
  const ignored = [
    { Tag: "malformed", Data: { Error: "truncated CoAP", Raw: "AA==" } },
    request("non", { Type: 1 }),
    request("ack", { Type: 2, Code: 0 }),
    request("rst", { Type: 3, Code: 0 }),
    request("ping", { Code: 0 }),
    request("response", { Code: 69 })
  ];
  assert.deepEqual(await invoke([...ignored, status]), { Replies: [result.Replies[0]] });
  const observed = (await invoke([
    request("observe", { Options: [{ Number: 6, Value: "" }] })
  ])).Replies[0];
  assert.equal(observed.Data.Code, "2.05");
  assert.equal(observed.Data.Options, undefined);
  assert.ok(warnings.some(([message]) => message === "Malformed CoAP request"));
  assert.ok(warnings.some(([message]) => message === "Invalid CoAP payload"));
  assert.ok(warnings.some(([message]) => message.includes("NON request unsupported")));
  for (const invalid of [
    { Tag: "string", Data: "{}" },
    { Tag: "null", Data: null },
    { Tag: "array", Data: [] },
    { Data: {} }
  ]) {
    await assert.rejects(() => invoke([invalid]), /Expected tagged CoAP object Data/);
  }
  await assert.rejects(() => context.exports.handler({}), /Expected UDP Gateway Messages array/);
  await assert.rejects(() => context.exports.handler({ Messages: null }), /Expected UDP Gateway Messages array/);
}

(async () => {
  await validate(lines.join(separator));
  for (const snippet of snippets) {
    await validate(snippet);
  }
  assert.ok(snippets.length > 0);
  const coapMarkdown = fs.readFileSync(path.join(root, "references", "COAP.md"), "utf8");
  const coapSnippets = [...coapMarkdown.matchAll(/^```javascript\r?\n([\s\S]*?)^```/gm)]
    .map(match => match[1]);
  assert.equal(coapSnippets.length, 1);
  await validateCoap(coapSnippets[0]);
  console.log(`Passed starter, ${snippets.length} base64 handler, and coap+ handler contract checks.`);
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
