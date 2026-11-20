import importlib.util
import io
import json
import pathlib
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[3]
NAMES = (
    "chip-constraints-sdc", "chip-sta", "chip-parasitic-extraction", "chip-power-ir",
    "chip-physical-integrity-checker", "chip-metal-fill", "chip-gds-assembly",
    "chip-streamout-xor",
)


def load_runner(name):
    source = next((ROOT / "agents-docker" / name).glob("tools/*/run.py"))
    spec = importlib.util.spec_from_file_location(name + "_transport", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DefaultSourceTransportTests(unittest.TestCase):
    def test_default_declared_action_has_no_shell_json_interpolation(self):
        for name in NAMES:
            with self.subTest(agent=name):
                tool = next((ROOT / "agents-docker" / name).glob("tools/*/tool.yaml"))
                text = tool.read_text(encoding="utf-8")
                self.assertIn('command: "python3 -u /app/run.py"', text)
                schema = text.split("    input_schema:\n", 1)[1]
                self.assertNotIn("params_json", schema)
                self.assertIn("properties: {}", schema)
                self.assertIn("additionalProperties: false", schema)

    def test_default_worker_loads_exact_unicode_and_apostrophe_file_content(self):
        params = {"scenario": "qualification", "literal": "counter's μ\\lane"}
        for name in NAMES:
            with self.subTest(agent=name):
                runner = load_runner(name)
                loader = getattr(runner, "_find_params_file", None) or runner._file_params
                def open_params(path, *args, **kwargs):
                    if path != "/input/params.json":
                        raise FileNotFoundError(path)
                    return io.StringIO(json.dumps(params, ensure_ascii=False))
                with mock.patch.object(runner.os.path, "exists",
                                       side_effect=lambda p: p == "/input/params.json"):
                    with mock.patch("builtins.open", side_effect=open_params):
                        self.assertEqual(params, loader())

    def test_missing_parameter_file_is_not_invented(self):
        for name in NAMES:
            with self.subTest(agent=name):
                runner = load_runner(name)
                loader = getattr(runner, "_find_params_file", None) or runner._file_params
                with mock.patch.object(runner.os.path, "exists", return_value=False):
                    with mock.patch("builtins.open", side_effect=FileNotFoundError):
                        self.assertIsNone(loader())

    def test_default_prompt_declares_the_same_file_transport(self):
        for name in NAMES:
            with self.subTest(agent=name):
                source = (ROOT / "agents-docker" / name / "agent.yaml").read_text(
                    encoding="utf-8")
                marker = "The following Services section overrides legacy CLI parameter transport."
                self.assertEqual(1, source.count(marker))
                self.assertIn("/input/params.json", source.split(marker, 1)[1])


if __name__ == "__main__":
    unittest.main()
