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
