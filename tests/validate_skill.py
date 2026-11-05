"""Local regression checks for the portable UDP Gateway skill."""

import ast
import base64
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "udp-gateway"


def blocks(path, language):
    return re.findall(
        rf"^```{re.escape(language)}\r?\n(.*?)^```",
        path.read_text(encoding="utf-8"),
        re.MULTILINE | re.DOTALL,
    )


class SkillTests(unittest.TestCase):
    def test_frontmatter_and_size(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        self.assertRegex(frontmatter, r"(?m)^name: udp-gateway$")
        description = re.search(r'(?m)^description: (".*")$', frontmatter)
        self.assertIsNotNone(description)
        self.assertLessEqual(len(json.loads(description.group(1))), 1024)
        self.assertLess(len(text.splitlines()), 500)

    def test_relative_markdown_links_exist(self):
        for path in SKILL.rglob("*.md"):
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                if "://" in target or target.startswith("#"):
                    continue
                self.assertTrue(
                    (path.parent / target.split("#", 1)[0]).exists(),
                    f"Broken link in {path.relative_to(ROOT)}: {target}",
                )

    def test_coap_discovery_guidance(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        description = json.loads(re.search(r'(?m)^description: (".*")$', text).group(1))
        for phrase in ["constrained-device", "sensor telemetry", "device commands", "HTTP/MQTT"]:
            self.assertIn(phrase, description)
        self.assertIn("(./references/COAP.md)", text)
        self.assertIn("before inventing a custom datagram protocol", text)
        self.assertIn("rather than assuming UDP is always preferable", text)

    def test_json_examples_parse(self):
        count = 0
        for path in SKILL.rglob("*.md"):
            for source in blocks(path, "json"):
                json.loads(source)
                count += 1
        self.assertGreaterEqual(count, 10)

    def test_python_handler_echo_contract(self):
        source = blocks(SKILL / "references" / "HANDLERS.md", "python")[0]
        ast.parse(source)
        namespace = {}
        exec(compile(source, "HANDLERS.md:python", "exec"), namespace)
        handler = namespace["handler"]
        self.assertEqual(handler({"Messages": []}, None), {"Replies": []})
        messages = [
            {"Tag": f"packet-{index}", "Data": base64.b64encode(payload).decode("ascii")}
            for index, payload in enumerate([b"", bytes(range(256)), "hello \u2603".encode()])
        ]
        self.assertEqual(
            handler({"Messages": messages}, None),
            {"Replies": messages},
        )
        with self.assertRaises(KeyError):
            handler({}, None)
        with self.assertRaises(TypeError):
            handler({"Messages": None}, None)
        with self.assertRaises(ValueError):
            handler({"Messages": [{"Tag": "bad", "Data": "***"}]}, None)

    def test_protocol_formatter_reply_examples(self):
        examples = [
            json.loads(source)
            for source in blocks(SKILL / "references" / "PACKET-FORMAT.md", "json")
        ]
        replies = [
            reply
            for example in examples
            for reply in example.get("Replies", [])
            if isinstance(reply["Data"], dict)
        ]
        self.assertEqual(len(replies), 2)
        for reply in replies:
            data = reply["Data"]
            self.assertTrue(reply["Tag"])
            self.assertEqual(data["Type"], 2)
            self.assertIsInstance(data["MessageId"], int)
            base64.b64decode(data["Token"], validate=True)
            if "ContentFormat" in data:
                self.assertEqual(data["ContentFormat"], 60)
                self.assertEqual(data["Payload"], {"0": "accepted"})
                self.assertNotIn("PayloadDecoded", data)
            else:
                self.assertEqual(base64.b64decode(data["Payload"], validate=True), b"hello")
                option = next(item for item in data["Options"] if item["Number"] == 12)
                self.assertEqual(
                    int.from_bytes(base64.b64decode(option["Value"], validate=True), "big"),
                    0,
                )

    def test_syslog_formatter_examples(self):
        examples = [
            json.loads(source)
            for source in blocks(SKILL / "references" / "PACKET-FORMAT.md", "json")
        ]
        parsed = next(item for item in examples if "schema_version" in item)
        self.assertEqual(set(parsed), {
            "schema_version", "parse_ok", "format", "pri", "facility", "severity",
            "facility_name", "severity_name", "version", "timestamp", "hostname",
            "app_name", "proc_id", "msg_id", "structured_data", "message", "raw",
        })
        self.assertEqual(parsed["schema_version"], 1)
        self.assertTrue(parsed["parse_ok"])
        self.assertEqual(parsed["facility"], parsed["pri"] >> 3)
        self.assertEqual(parsed["severity"], parsed["pri"] & 7)
        self.assertIsNone(parsed["raw"])
        outbound = next(
            message
            for example in examples
            for message in example.get("Messages", [])
            if message.get("Formatter") == "syslog"
        )
        self.assertEqual(outbound["Remote"], {"Address": "203.0.113.10", "Port": 514})
        self.assertIsInstance(outbound["Data"], dict)
        self.assertEqual(outbound["Data"]["severity_name"], "err")

    def test_starter_access_logging_and_formatter(self):
        template = json.loads((SKILL / "assets" / "starter.template.json").read_text(encoding="utf-8"))
        self.assertNotIn("Default", template["Parameters"]["ClientCidrToAllow"])
        resources = template["Resources"]
        listener = resources["UdpListener"]["Properties"]
        self.assertEqual(listener["Protocols"], ["udp"])
        self.assertEqual(listener["ClientRestrictions"]["Networks"], [{"Ref": "ClientCidrToAllow"}])
        destination = listener["Destinations"][0]
        self.assertEqual(destination["Formatter"], "base64")
        self.assertEqual(destination["LogGroupName"], {"Ref": "DeliveryErrorLogs"})
        self.assertTrue(destination["MetricsEnabled"])
        for name in ["HandlerLogs", "DeliveryErrorLogs"]:
            self.assertEqual(resources[name]["Properties"]["RetentionInDays"], 14)
        handler = resources["PacketHandler"]["Properties"]
        self.assertEqual(handler["LoggingConfig"]["LogGroup"], {"Ref": "HandlerLogs"})
        statements = resources["DestinationRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
        actions = {action for statement in statements for action in statement["Action"]}
        self.assertTrue({
            "lambda:InvokeFunction", "cloudwatch:PutMetricData",
            "logs:CreateLogStream", "logs:PutLogEvents",
        } <= actions)
        metrics = next(s for s in statements if "cloudwatch:PutMetricData" in s["Action"])
        self.assertEqual(
            metrics["Condition"]["StringEquals"]["cloudwatch:namespace"],
            "Proxylity/UDP Gateway",
        )

    def test_listener_metrics_accounting(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        architecture = (SKILL / "references" / "ARCHITECTURE.md").read_text(encoding="utf-8")
        for text in [skill, architecture]:
            self.assertIn("before protocol processing", text)
            self.assertIn("suspended-listener datagrams count only as", text)
            self.assertIn("every successfully sent datagram", text)
            self.assertIn("Listener and destination/source counters overlap", text)
            self.assertIn("max(1, ceil(recorded byte length / 1024))", text)
            self.assertIn("PacketSource publishes only `EgressPackets` and `EgressBytes`", text)
            self.assertIn("`PacketSource=<source_id>`", text)
            self.assertIn("bound listener's `MetricsEnabled` setting and observability role", text)
            self.assertNotIn("metrics are independent, not roll-ups", text)
        self.assertIn("FilteredBytes / (IngressBytes + FilteredBytes)", architecture)
        self.assertIn("for a nonzero denominator", architecture)
        self.assertIn("1056-byte datagram is one destination/source egress unit but two listener egress units", architecture)
        self.assertIn("Invalid transport packets admitted on an active listener remain ingress", architecture)
        self.assertIn("not once per control datagram or retransmission", architecture)

    def test_asl_contract_is_jsonata(self):
        definitions = [
            json.loads(source)
            for source in blocks(SKILL / "references" / "HANDLERS.md", "json")
        ]
        definition = next(item for item in definitions if "States" in item)
        self.assertEqual(definition["QueryLanguage"], "JSONata")
        state = definition["States"][definition["StartAt"]]
        self.assertTrue(state["End"])
        self.assertNotIn("Parameters", state)
        self.assertIn("$states.input.Messages", state["Output"]["Replies"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
