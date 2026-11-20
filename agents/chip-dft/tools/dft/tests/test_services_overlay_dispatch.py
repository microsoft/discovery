import ast
import contextlib
import io
import json
from pathlib import Path
import shlex
import sys
import unittest
from unittest import mock


class ServicesOverlayDispatch(unittest.TestCase):
    def test_registered_command_patches_then_executes_native_worker(self):
        packages = Path(__file__).resolve().parents[4]
        for package in ("chip-debug-root-cause", "chip-dft", "chip-lec",
                        "chip-low-power-upf", "chip-logic-synthesis",
                        "chip-uarch-ppa", "chip-ppa-dse",
                        "chip-hierarchical-soc-integration"):
            with self.subTest(agent=package):
                deployment = json.loads((packages / package / "services-deployment.json").read_text(encoding="utf-8"))
                argv = shlex.split(deployment["effective_command"])
                self.assertEqual(argv[:2], ["python3", "-c"])
                self.assertEqual(len(argv), 3, "Services executes argv, not shell &&")
                directory = packages / package / "tools" / deployment["tool_directory"]
                files = {}
                for patch in deployment["source_patches"]:
                    source = (directory / Path(patch["path"]).name).read_text(encoding="utf-8")
                    if patch.get("before_source"):
                        old = patch["before_source"]
                    elif patch["function"] == "_authoritative_exit_code":
                        start = patch["after"].index('            with open(_p, encoding="utf-8")')
                        end = patch["after"].index("\n        except Exception:", start)
                        old = (patch["after"][:start] +
                               '            return 0 if json.load(open(_p)).get("status") == "completed" else 1' +
                               patch["after"][end:])
                    else:
                        old = patch["after"].replace(
                            '        # Yosys proc retains vector registers as one cell; scan chains shift\n'
                            '        # storage bits, not vector-cell instances.\n'
                            '        width = max(1, len(cell.get("connections", {}).get("Q", [])))\n',
                            "").replace("+= width", "+= 1")
                    files[patch["path"]] = source.replace(patch["after"], old)

                class WorkerPath:
                    def __init__(self, path):
                        self.path = path

                    def read_text(self):
                        return files[self.path]

                    def write_text(self, text):
                        files[self.path] = text

                with mock.patch("pathlib.Path", WorkerPath), \
                        mock.patch("os.execv") as native_exec, \
                        mock.patch.dict("os.environ", {}, clear=False), \
                        contextlib.redirect_stdout(io.StringIO()):
                    exec(compile(argv[2], "<registered-command>", "exec"), {})
                native_exec.assert_called_once_with(
                    sys.executable, [sys.executable, "-u", "/app/run.py"])
                for patch in deployment["source_patches"]:
                    tree = ast.parse(files[patch["path"]])
                    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                                and n.name == patch["function"])
                    self.assertEqual(ast.get_source_segment(files[patch["path"]], node),
                                     patch["after"])


if __name__ == "__main__":
    unittest.main()
