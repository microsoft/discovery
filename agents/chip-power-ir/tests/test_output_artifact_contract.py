"""Check published artifact metadata against source, not invented solver results."""
import ast
from pathlib import Path
import unittest

import yaml


AGENTS = Path(__file__).resolve().parents[2]
ENVELOPE = "common_design_envelope.json"
LEGACY_ENVELOPE = "final_results.json"


class OutputArtifactContractTests(unittest.TestCase):
    def test_all_published_tool_descriptions_use_the_authoritative_artifact(self):
        tools = sorted(AGENTS.glob("chip-*/tools/*/tool.yaml"))
        self.assertEqual(len(tools), 43)
        for tool in tools:
            with self.subTest(package=tool.parents[2].name):
                text = tool.read_text(encoding="utf-8-sig")
                self.assertNotIn(LEGACY_ENVELOPE, text)
                definition = yaml.safe_load(text)
                for action in definition.get("actions", []):
                    description = action.get("description", "")
                    if "/output/" in description:
                        self.assertIn("/output/" + ENVELOPE, description)

    def test_native_writers_still_emit_the_documented_envelope(self):
        tools = sorted(AGENTS.glob("chip-*/tools/*/tool.yaml"))
        self.assertEqual(len(tools), 43)
        for tool in tools:
            with self.subTest(package=tool.parents[2].name):
                source = next(tool.parent.glob("*_utils.py"))
                tree = ast.parse(source.read_text(encoding="utf-8-sig"))
                writer = next(node for node in tree.body
                              if isinstance(node, ast.FunctionDef)
                              and node.name == "save_final_results")
                joins = [node for node in ast.walk(writer)
                         if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                         and node.func.attr == "join" and len(node.args) >= 2
                         and isinstance(node.args[0], ast.Name)
                         and node.args[0].id in ("_OUTPUT_DIR", "OUTPUT_DIR", "OUTPUT")
                         and isinstance(node.args[1], ast.Constant)
                         and node.args[1].value == ENVELOPE]
                self.assertTrue(joins, "native writer no longer names the authoritative envelope")


if __name__ == "__main__":
    unittest.main()