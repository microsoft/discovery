"""Local policy regression only; these tests do not qualify native engines."""
import contextlib
import io
import json
from pathlib import Path
import runpy
import shlex
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import mock_open, patch

import yaml

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = (
    "chip-analog-spice", "chip-antenna-erc", "chip-dfm-litho-yield",
    "chip-drc", "chip-lvs", "chip-library-development", "chip-pdk-binding",
)


class FabricationExecutionPolicyTests(unittest.TestCase):
    def test_default_declared_action_is_the_source_launcher(self):
        for package in PACKAGES:
            path = next((ROOT / "agents" / package / "tools").glob("*/tool.yaml"))
            definition = yaml.safe_load(path.read_text(encoding="utf-8"))
            action = next(a for a in definition["actions"] if a["name"] == "run")
            with self.subTest(package=package):
                self.assertEqual(shlex.split(action["command"]),
                                 ["python3", "-u", "/app/action_launcher.py"])
                self.assertTrue((path.parent / "action_launcher.py").is_file())
                dockerfile = (path.parent / "Dockerfile").read_text(encoding="utf-8")
                self.assertIn("COPY action_launcher.py /app/action_launcher.py", dockerfile)
                self.assertEqual(action["input_schema"]["type"], "object")
                self.assertEqual(action["input_schema"]["properties"], {})
                self.assertEqual(action["input_schema"].get("required", []), [])

    def test_direct_worker_and_declared_action_preserve_cde_and_gate_domain_failure(self):
        cases = (
            ("completed", "pass", 0, 0),
            ("completed", "pass_with_caveats", 0, 0),
            ("completed", "review", 0, 0),
            ("completed", "fail", 0, 1),
            ("completed", "not_assessable", 0, 1),
            ("completed", "completed", 0, 1),
            ("completed", "partial_pass", 0, 1),
            ("completed", None, 0, 1),
            ("completed", "unknown", 0, 1),
            ("failed", "fail", 1, 1),
            ("blocked", "not_assessable", 0, 1),
            ("completed", "pass", 2, 2),
        )
        for package in PACKAGES:
            path = next((ROOT / "agents" / package / "tools").glob("*/tool.yaml"))
            worker = runpy.run_path(str(path.parent / "run.py"), run_name="policy_test")
            action = next(a for a in yaml.safe_load(path.read_text(encoding="utf-8"))["actions"]
                          if a["name"] == "run")
            argv = shlex.split(action["command"])
            launcher = path.parent / Path(argv[-1]).name
            code = compile(launcher.read_text(encoding="utf-8"), str(launcher), "exec")
            for status, verdict, native_exit, expected in cases:
                envelope = {"status": status, "validation": {"verdict": verdict}, "sentinel": ["unchanged", 7]}
                with self.subTest(package=package, status=status, verdict=verdict, native_exit=native_exit):
                    output = io.StringIO()
                    with patch("builtins.open", mock_open(read_data=json.dumps(envelope))), \
                            contextlib.redirect_stdout(output):
                        source_exit = worker["_authoritative_exit_code"]("persisted.json")
                    self.assertEqual(source_exit, int(status != "completed" or verdict not in (
                        "pass", "pass_with_caveats", "review")))
                    self.assertEqual(json.loads(output.getvalue().split("CDE_JSON=")[1]), envelope)
                    output = io.StringIO()
                    before = sys.path[:]
                    try:
                        with patch("runpy.run_path", side_effect=SystemExit(native_exit)) as native, \
                                patch.dict(sys.modules, {"pdk_binding_utils": SimpleNamespace(
                                    _parse_magic_density_rules=lambda path: None,
                                    __file__="/app/pdk_binding_utils.py"),
                                    "drc_utils": SimpleNamespace(
                                        _run_klayout_drc=lambda *args, **kwargs: {},
                                        _run_magic_drc=lambda *args, **kwargs: {},
                                        _OUTPUT_DIR="/output")}), \
                                patch("os.path.isfile", return_value=True), \
                                patch("builtins.open", mock_open(read_data=json.dumps(envelope))), \
                                contextlib.redirect_stdout(output):
                            with self.assertRaises(SystemExit) as exc:
                                exec(code, {"__name__": "__main__"})
                        self.assertEqual(exc.exception.code, expected)
                        native.assert_called_once_with("/app/run.py", run_name="__main__")
                        lines = output.getvalue().splitlines()
                        self.assertEqual(json.loads(next(l[9:] for l in lines if l.startswith("CDE_JSON="))), envelope)
                        self.assertEqual(
                            json.loads(next(l.split("=", 1)[1] for l in lines if l.startswith("SERVICES_EXIT_JSON="))),
                            {"worker_exit": native_exit, "effective_exit": expected},
                        )
                    finally:
                        sys.path[:] = before

    def test_missing_verdict_fails_closed_in_both_launchers(self):
        envelope = {"status": "completed", "validation": {}, "sentinel": ["unchanged"]}
        for package in PACKAGES:
            directory = next((ROOT / "agents" / package / "tools").iterdir())
            for name in ("action_launcher.py", "services_launcher.py"):
                path = directory / name
                code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
                before = sys.path[:]
                try:
                    with self.subTest(package=package, launcher=name), \
                            patch("runpy.run_path", side_effect=SystemExit(0)), \
                            patch.dict(sys.modules, {
                                "pdk_binding_utils": SimpleNamespace(
                                    _parse_magic_density_rules=lambda path: None,
                                    __file__="/app/pdk_binding_utils.py"),
                                "drc_utils": SimpleNamespace(
                                    _run_klayout_drc=lambda *args, **kwargs: {},
                                    _run_magic_drc=lambda *args, **kwargs: {},
                                    _OUTPUT_DIR="/output")}), \
                            patch("os.path.isfile", return_value=True), \
                            patch("builtins.open", mock_open(read_data=json.dumps(envelope))), \
                            contextlib.redirect_stdout(io.StringIO()):
                        with self.assertRaises(SystemExit) as exc:
                            exec(code, {"__name__": "__main__"})
                        self.assertEqual(exc.exception.code, 1)
                finally:
                    sys.path[:] = before

    def test_direct_worker_missing_or_malformed_envelope_fails_closed(self):
        for package in PACKAGES:
            path = next((ROOT / "agents" / package / "tools").glob("*/run.py"))
            worker = runpy.run_path(str(path), run_name="policy_test")
            with self.subTest(package=package, error="missing"):
                with patch("builtins.open", side_effect=FileNotFoundError):
                    self.assertEqual(worker["_authoritative_exit_code"](), 1)
            with self.subTest(package=package, error="malformed"):
                with patch("builtins.open", mock_open(read_data="not JSON")):
                    self.assertEqual(worker["_authoritative_exit_code"](), 1)


if __name__ == "__main__":
    unittest.main()
