"""Registered action transport regressions; no EDA engine results are simulated as signoff."""
import contextlib
import io
import json
from pathlib import Path
import runpy
import shlex
import sys
import unittest
from unittest import mock

import yaml

AGENTS = Path(__file__).resolve().parents[2]
NAMES = ("chip-eco", "chip-floorplanning", "chip-placement", "chip-routing",
         "chip-cts", "chip-pdn", "chip-opendb-utilities")


class FixedFileActionTests(unittest.TestCase):
    def test_no_catalog_action_interpolates_caller_json(self):
        tools = sorted(AGENTS.glob("*/tools/*/tool.yaml"))
        self.assertEqual(len(tools), 43)
        for path in tools:
            definition = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            for action in definition["actions"]:
                with self.subTest(path=path, action=action["name"]):
                    self.assertNotIn("{{params_json}}", action["command"])

    def test_registered_files_and_services_instructions_agree(self):
        for name in NAMES:
            path = next((AGENTS / name).glob("tools/*/tool.yaml"))
            definition = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            action = next(item for item in definition["actions"] if item["name"] == "run")
            with self.subTest(agent=name):
                self.assertEqual(shlex.split(action["command"]),
                                 ["python3", "-B", "-u", "/app/run.py", "--params-file", "/input/params.json"])
                self.assertEqual(action["input_schema"].get("properties"), {})
                self.assertEqual(action["input_schema"].get("required"), [])
                instructions = (AGENTS / name / "services-instructions.md").read_text(encoding="utf-8")
                self.assertIn("/input/params.json", instructions)
                self.assertNotIn("Keep the existing single-line", instructions)

    def test_explicit_file_preserves_unicode_quotes_and_ignores_alternate_inputs(self):
        payload = {"scenario": "synthetic_transport", "literal": "owner's μ 1'b0; $(not-a-shell)"}
        for name in NAMES:
            path = next((AGENTS / name).glob("tools/*/run.py"))
            worker = runpy.run_path(str(path), run_name="transport_test")
            namespace = worker["main"].__globals__
            run = mock.Mock(return_value=0)
            opener = mock.mock_open(read_data=json.dumps(payload, ensure_ascii=False))
            with self.subTest(agent=name), \
                    mock.patch.dict(namespace, {"run_from_params": run, "_run": run}), \
                    mock.patch.object(sys, "argv", ["run.py", "--params-file", "/input/params.json"]), \
                    mock.patch("builtins.open", opener), contextlib.redirect_stdout(io.StringIO()):
                try:
                    code = worker["main"]()
                except SystemExit as exc:
                    code = exc.code
                self.assertEqual(code, 0)
                run.assert_called_once_with(payload)
                opener.assert_called_once_with("/input/params.json", encoding="utf-8-sig")

    def test_invalid_explicit_file_never_falls_back_to_another_file(self):
        for name in NAMES:
            path = next((AGENTS / name).glob("tools/*/run.py"))
            worker = runpy.run_path(str(path), run_name="transport_test")
            namespace = worker["main"].__globals__
            for raw in ("{", "[]", "{}"):
                run = mock.Mock()
                fallback = mock.Mock(side_effect=AssertionError("must not fall back"))
                with self.subTest(agent=name, raw=raw), \
                        mock.patch.dict(namespace, {"run_from_params": run, "_run": run,
                            "_find_params_file": fallback, "_file_params": fallback,
                            "_fail_closed": mock.Mock(side_effect=SystemExit(1)),
                            "_fail": mock.Mock(return_value=1)}), \
                        mock.patch.object(sys, "argv", ["run.py", "--params-file", "/input/params.json"]), \
                        mock.patch("builtins.open", mock.mock_open(read_data=raw)), \
                        contextlib.redirect_stdout(io.StringIO()):
                    try:
                        code = worker["main"]()
                    except SystemExit as exc:
                        code = exc.code
                    self.assertEqual(code, 1)
                    run.assert_not_called()
                    fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()