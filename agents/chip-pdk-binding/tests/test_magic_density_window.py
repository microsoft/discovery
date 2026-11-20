import importlib.util
import ast
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

    def test_actual_checker_includes_prorated_tenth_tile(self):
        checker = ROOT / "pdk" / "sky130" / "sky130A" / "libs.tech" / "magic" / "check_density.py"
        result = MODULE._parse_magic_density_rules(str(checker))
        self.assertEqual(result["window_um"], dict(width=700.0, height=700.0, measurement_step=70.0))
        self.assertEqual(result["layers"]["met1"], dict(minimum=0.35, maximum=0.60))
        self.assertEqual(result["layers"]["met5"], dict(minimum=0.45, maximum=0.76))

    def test_ambiguous_or_absent_partial_tile_formula_fails_closed(self):
        self.assertIsNone(MODULE._magic_density_window_size("", 70, 9))
        self.assertIsNone(MODULE._magic_density_window_size(
            "atotal = 64.0 + 8.0 * locxfrac + 8.0 * locyfrac + locxfrac * locyfrac", 70, 9))


if __name__ == "__main__":
    unittest.main()
