"""Exercise the contributed launcher and historical overlay without deployment receipts."""
import ast
import contextlib
import io
import os
from pathlib import Path
import shlex
import unittest
from unittest import mock

import yaml


PACKAGES = Path(__file__).resolve().parents[4]
NAMES = (
    "chip-debug-root-cause", "chip-dft", "chip-lec", "chip-low-power-upf",
    "chip-logic-synthesis", "chip-uarch-ppa", "chip-ppa-dse",
    "chip-hierarchical-soc-integration",
)


def overlay_inputs(package):
    directory = next((PACKAGES / package / "tools").iterdir())
    source = (PACKAGES / package / "services-overlay.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    patches = ast.literal_eval(next(
        node.value for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "patches"
                for target in node.targets)))
    files = {item["path"]: (directory / Path(item["path"]).name).read_text(encoding="utf-8")
             for item in patches}
    return directory, source, patches, files


def execute_overlay(source, files):
    class WorkerPath:
        def __init__(self, path):
            self.path = path

        def read_text(self):
            return files[self.path]

        def write_text(self, text):
            files[self.path] = text

    with mock.patch("pathlib.Path", WorkerPath), contextlib.redirect_stdout(io.StringIO()):
        exec(compile(source, "<historical-services-overlay>", "exec"), {})


class ServicesOverlayDispatch(unittest.TestCase):
    def test_registered_source_launcher_executes_current_worker(self):
        for package in NAMES:
            directory, _, _, _ = overlay_inputs(package)
            definition = yaml.safe_load((directory / "tool.yaml").read_text(encoding="utf-8"))
            action = next(item for item in definition["actions"] if item["name"] == "run")
            with self.subTest(agent=package):
                self.assertEqual(shlex.split(action["command"]),
                                 ["python3", "-u", "/app/action_launcher.py"])
                source = (directory / "action_launcher.py").read_text(encoding="utf-8")
                for code in (0, 1, 2):
                    with mock.patch("runpy.run_path", side_effect=SystemExit(code)) as native, \
                            mock.patch.dict(os.environ, {}, clear=False):
                        with self.assertRaises(SystemExit) as result:
                            exec(compile(source, "<registered-launcher>", "exec"), {})
                        self.assertEqual(result.exception.code, code)
                        native.assert_called_once_with("/app/run.py", run_name="__main__")
                        self.assertEqual(os.environ["TMPDIR"], "/workdir")
                dockerfile = (directory / "Dockerfile").read_text(encoding="utf-8")
                self.assertIn("action_launcher.py", dockerfile)

    def test_historical_overlay_is_idempotent_on_current_source(self):
        for package in NAMES:
            _, source, patches, files = overlay_inputs(package)
            before = dict(files)
            with self.subTest(agent=package):
                execute_overlay(source, files)
                self.assertEqual(files, before)
                for patch in patches:
                    tree = ast.parse(files[patch["path"]])
                    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                                and n.name == patch["function"])
                    self.assertEqual(ast.get_source_segment(files[patch["path"]], node),
                                     patch["after"])

    def test_historical_overlay_rejects_unknown_source_drift(self):
        for package in NAMES:
            _, source, patches, files = overlay_inputs(package)
            patch = patches[0]
            files[patch["path"]] = files[patch["path"]].replace(
                patch["after"], patch["after"] + "\n    # unqualified source drift\n")
            # Add executable drift inside the target function (comments alone
            # after its last statement are outside the AST function range).
            files[patch["path"]] = files[patch["path"]].replace(
                "def " + patch["function"] + "(path=None):",
                "def " + patch["function"] + "(path=None):\n    drift_sentinel = True")
            with self.subTest(agent=package), self.assertRaisesRegex(RuntimeError, "precondition mismatch"):
                execute_overlay(source, files)


if __name__ == "__main__":
    unittest.main()