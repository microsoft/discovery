import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "tools/dfm"
sys.path.insert(0, str(SOURCE))
SPEC = importlib.util.spec_from_file_location("dfm_utils", SOURCE / "dfm_utils.py")
dfm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dfm)


class DensityContractTest(unittest.TestCase):
    def params(self):
        return {"layout": "test.gds", "pdk_binding": {"dfm_rules": {
            "density_window": {"min": 0.1, "max": 0.9, "window_um": 700, "step_um": 70},
            "layers": [{"name": "met1", "layer": 68, "datatype": 20}]
        }}}

    def test_explicit_rolling_step_reaches_geometry_engine(self):
        with patch.object(dfm.layout_geometry, "load", return_value="layout"), patch.object(
                dfm.layout_geometry, "windowed_density", return_value={
                    "assessable": True, "windows": [{"density": 0.5}]
                }) as measure:
            result = dfm._dfm_check(self.params())
        measure.assert_called_once_with("layout", 68, 700, step_um=70, datatype=20)
        self.assertEqual(result["validation"]["verdict"], "pass")

    def test_missing_required_layer_never_passes_via_other_metrics(self):
        params = self.params()
        params["metrics"] = {"met1": {"single_via_count": 0, "redundant_via_count": 1}}
        with patch.object(dfm.layout_geometry, "load", return_value="layout"), patch.object(
                dfm.layout_geometry, "windowed_density", return_value={
                    "assessable": False, "note": "layer absent"
                }):
            result = dfm._dfm_check(params)
        self.assertEqual(result["validation"]["verdict"], "not_assessable")
        self.assertIn("met1", result["validation"]["note"])


if __name__ == "__main__":
    unittest.main()
