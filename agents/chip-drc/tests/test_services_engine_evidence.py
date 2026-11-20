import ast
import contextlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest


class EngineEvidenceTests(unittest.TestCase):
    def wrapper(self):
        source = Path(__file__).resolve().parents[1] / "tools" / "drc" / "services_launcher.py"
        function = next(n for n in ast.parse(source.read_text()).body
                        if isinstance(n, ast.FunctionDef) and n.name == "_log_engine_result")
        namespace = dict(json=json, os=os, _drc_utils=SimpleNamespace(_OUTPUT_DIR="unavailable-output"))
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        return namespace["_log_engine_result"]

    def test_exact_engine_results_and_identity_are_preserved(self):
        for count in (0, 1, None):
            result = dict(engine="klayout" if count is not None else "magic",
                          count=count, ok=count is not None, per_rule={})
            calls = []
            def worker(*args, **kwargs):
                calls.append((args, kwargs))
                return result
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                returned = self.wrapper()(worker)("layout", top="TOP")
            self.assertIs(returned, result)
            self.assertEqual(calls, [(("layout",), dict(top="TOP"))])
            self.assertEqual(json.loads(output.getvalue().split("=", 1)[1]), result)


if __name__ == "__main__":
    unittest.main()
