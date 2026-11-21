import ast
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


class OwnedServicesExit(unittest.TestCase):
    def test_default_entrypoints_propagate_persisted_domain_verdict(self):
        packages = Path(__file__).resolve().parents[4]
        names = ("chip-debug-root-cause", "chip-dft", "chip-lec",
                 "chip-low-power-upf", "chip-logic-synthesis", "chip-uarch-ppa",
                 "chip-ppa-dse", "chip-hierarchical-soc-integration")
        artifact = Path(__file__).with_name("qualification39-entrypoint-envelope.json")
        original_open = open

        def redirected_open(path, *args, **kwargs):
            if str(path) in ("/output/common_design_envelope.json", "/output/final_results.json"):
                return original_open(artifact, *args, **kwargs)
            return original_open(path, *args, **kwargs)

        try:
            for name in names:
                path = next((packages / name / "tools").glob("*/run.py"))
                tree = ast.parse(path.read_text(encoding="utf-8"))
                entrypoint = next(n for n in tree.body
                                  if isinstance(n, ast.FunctionDef) and n.name == "run_from_params")
                utility = next(n.names[0].name for n in ast.walk(entrypoint)
                               if isinstance(n, ast.Import) and n.names[0].asname == "utils")
                spec = importlib.util.spec_from_file_location(name + "_default_run", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for verdict, expected in (("pass", 0), ("fail", 1), ("not_assessable", 1)):
                    with self.subTest(agent=name, verdict=verdict):
                        result = {"status": "completed", "validation": {"verdict": verdict}}
                        utils = types.SimpleNamespace(
                            quick_setup=mock.Mock(), dispatch=mock.Mock(return_value=result),
                            save_final_results=lambda data: artifact.write_text(
                                json.dumps(data), encoding="utf-8"))
                        output = io.StringIO()
                        with mock.patch.dict(sys.modules, {utility: utils}), \
                                mock.patch("builtins.open", side_effect=redirected_open), \
                                contextlib.redirect_stdout(output), \
                                contextlib.redirect_stderr(output):
                            code = module.run_from_params({"scenario": "unit_stub"})
                        self.assertEqual(code, expected)
                        utils.dispatch.assert_called_once_with({"scenario": "unit_stub"})
                        self.assertEqual("CDE_JSON=" in output.getvalue(), bool(expected))
        finally:
            artifact.unlink(missing_ok=True)

    def test_domain_verdict_controls_exit(self):
        packages = Path(__file__).resolve().parents[4]
        names = ("chip-debug-root-cause", "chip-dft", "chip-lec",
                 "chip-low-power-upf", "chip-logic-synthesis", "chip-uarch-ppa",
                 "chip-ppa-dse", "chip-hierarchical-soc-integration")
        artifact = Path(__file__).with_name("qualification39-exit-envelope.json")
        try:
            for name in names:
                path = next((packages / name / "tools").glob("*/run.py"))
                spec = importlib.util.spec_from_file_location(name + "_run", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for status, verdict, expected in (
                    ("completed", "pass", 0), ("completed", "pass_with_caveats", 0),
                    ("completed", "review", 0), ("completed", "fail", 1),
                    ("completed", "not_assessable", 1), ("failed", "pass", 1),
                    ("completed", None, 1),
                ):
                    with self.subTest(agent=name, status=status, verdict=verdict):
                        artifact.write_text(json.dumps({
                            "status": status, "validation": {"verdict": verdict}
                        }), encoding="utf-8")
                        output = io.StringIO()
                        with contextlib.redirect_stdout(output):
                            code = module._authoritative_exit_code(str(artifact))
                        self.assertEqual(code, expected)
                        self.assertEqual("CDE_JSON=" in output.getvalue(), bool(expected))
        finally:
            artifact.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
