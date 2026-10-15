const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..", "udp-gateway");
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

(async () => {
  await validate(lines.join(separator));
  for (const snippet of snippets) {
    await validate(snippet);
  }
  assert.ok(snippets.length > 0);
  console.log(`Passed starter and ${snippets.length} documented JavaScript handler contract checks.`);
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
