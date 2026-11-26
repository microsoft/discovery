import importlib.util
import ast
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).resolve().parents[1] / "tools" / "pdk-binding" / "pdk_binding_utils.py"
SPEC = importlib.util.spec_from_file_location("density_binding_under_test", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MagicDensityWindowTests(unittest.TestCase):
    def test_registered_launcher_has_identical_window_helper(self):
        launcher = SOURCE.with_name("services_launcher.py")
        def helper(path):
            return next(n for n in ast.parse(path.read_text()).body
                        if isinstance(n, ast.FunctionDef) and n.name == "_magic_density_window_size")
        self.assertEqual(ast.dump(helper(SOURCE)), ast.dump(helper(launcher)))

    def test_synthetic_checker_includes_prorated_tenth_tile(self):
        # A parser unit fixture, not a substitute for a licensed/pinned PDK.
        text = (
            'box size 70um 70um\nfor w in range(y, y + 9):\n'
            '    atotal = 81.0 + 9.0 * locxfrac + 9.0 * locyfrac + locxfrac * locyfrac\n'
        )
        for number in range(1, 6):
            minimum, maximum = ((0.45, 0.76) if number == 5 else (0.35, 0.60))
            text += (f'if met{number}accum < {minimum}:\n    pass\n'
                     f'elif met{number}accum > {maximum}:\n    pass\n')
        with tempfile.TemporaryDirectory() as directory:
            checker = Path(directory) / "synthetic_density_checker.py"
            checker.write_text(text, encoding="utf-8")
            result = MODULE._parse_magic_density_rules(str(checker))
        self.assertIsNotNone(result)
        self.assertEqual(result["window_um"], dict(width=700.0, height=700.0, measurement_step=70.0))
        self.assertEqual(result["layers"]["met1"], dict(minimum=0.35, maximum=0.60))
        self.assertEqual(result["layers"]["met5"], dict(minimum=0.45, maximum=0.76))

    def test_pinned_external_checker_when_explicitly_configured(self):
        configured = os.environ.get("CHIP_TEST_MAGIC_DENSITY_CHECKER")
        if not configured:
            self.skipTest("external PDK integration: set CHIP_TEST_MAGIC_DENSITY_CHECKER")
        checker = Path(configured)
        self.assertTrue(checker.is_file(), configured)
        result = MODULE._parse_magic_density_rules(str(checker))
        self.assertIsNotNone(result, "configured checker is absent, ambiguous, or unsupported")
        self.assertEqual(set(result["layers"]), {f"met{n}" for n in range(1, 6)})

    def test_ambiguous_or_absent_partial_tile_formula_fails_closed(self):
        self.assertIsNone(MODULE._magic_density_window_size("", 70, 9))
        self.assertIsNone(MODULE._magic_density_window_size(
            "atotal = 64.0 + 8.0 * locxfrac + 8.0 * locyfrac + locxfrac * locyfrac", 70, 9))


if __name__ == "__main__":
    unittest.main()
