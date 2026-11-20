import importlib.util
import json
import os
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1] / "tools" / "constraints"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sdc_author = load_module("sdc_author")
run = load_module("run")


class AuthorSdcRegressionTest(unittest.TestCase):
    def test_clock_trace_crosses_buffers_and_fails_closed_on_native_trace_errors(self):
        script = sdc_author._ENUM_TCL
        self.assertIn("set _net [get_nets -quiet -of_objects $_pin]", script)
        self.assertIn("get_fanout -from $_port -flat -trace_arcs all", script)
        self.assertNotIn("get_fanin", script)
        self.assertIn("dict exists $_clock_pin_names $_name", script)
        self.assertIn("if {$_clk_trace_ok}", script)
        self.assertIn("_emit CLKPORTS [lsort -unique $_clkports]", script)
        self.assertIn("get_ports -quiet -of_objects $_net", script)

    def test_exit_code_uses_configured_output_directory(self):
        with tempfile.TemporaryDirectory() as output_dir:
            path = pathlib.Path(output_dir) / "common_design_envelope.json"
            path.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
            old = os.environ.get("CHIP_OUTPUT_DIR")
            os.environ["CHIP_OUTPUT_DIR"] = output_dir
            try:
                self.assertEqual(0, run._authoritative_exit_code())
            finally:
                if old is None:
                    os.environ.pop("CHIP_OUTPUT_DIR", None)
                else:
                    os.environ["CHIP_OUTPUT_DIR"] = old

    def test_unavailable_enumeration_keeps_four_value_contract(self):
        result = sdc_author.author_sdc(
            {"clock_ports": None, "clock_pins": None}, {}, top="guarded_scan")
        self.assertEqual(4, len(result))
        self.assertIsNone(result[0])
        self.assertEqual({}, result[3])

    def test_guarded_scan_ports_are_timed_as_ordinary_io(self):
        enum = {
            "clock_ports": ["clk u_scan_ff/CLK"],
            "clock_pins": ["u_scan_ff/CLK"],
            "inputs": ["clk", "scan_en", "scan_in"],
            "outputs": ["scan_out"],
        }
        intent = {
            "clocks": {
                "clk": {
                    "period_ns": 20.0,
                    "waveform_ns": [0.0, 10.0],
                    "uncertainty_ns": {"setup": 0.05, "hold": 0.05},
                    "source": "MYTOP4-HIERSOC-SPEC-1.0/SR-040",
                }
            },
            "input_delay_ns": {
                "min": 0.5, "max": 2.5,
                "source": "MYTOP4-HIERSOC-SPEC-1.0/SR-041",
            },
            "output_delay_ns": {
                "min": 0.5, "max": 2.5,
                "source": "MYTOP4-HIERSOC-SPEC-1.0/SR-041",
            },
            "clock_transition_ns": 0.1,
            "clock_latency_ns": {"network_pre_cts": 0.3},
            "macro_input_transition_ns": 0.1,
            "macro_output_load_pf": 0.05,
            "macro_electrical_source": "MYTOP4-HIERSOC-SPEC-1.0-A.1/SR-040",
            "design_rules": {
                "max_transition_ns": 1.4,
                "max_capacitance_pf": 0.2,
                "max_fanout": 20,
                "source": "MYTOP4-HIERSOC-SPEC-1.0/SR-042",
            },
        }
        lines, emitted, holes, classes = sdc_author.author_sdc(
            enum, intent, top="guarded_scan")
        text = "\n".join(lines)
        self.assertFalse(holes)
        self.assertIn("create_clock -name clk -period 20.000", text)
        self.assertIn("set_clock_uncertainty -setup 0.050", text)
        self.assertIn("set_clock_uncertainty -hold 0.050", text)
        self.assertIn("set_clock_transition 0.100 [get_clocks clk]", text)
        self.assertIn("set_clock_latency 0.300 [get_clocks clk]", text)
        self.assertIn(
            "set_input_transition 0.100 [get_ports {scan_en}]", text)
        self.assertIn("set_input_transition 0.100 [get_ports {scan_in}]", text)
        self.assertIn("set_load 0.050 [get_ports {scan_out}]", text)
        self.assertIn("set_input_delay -clock clk -max 2.500 [get_ports {scan_en}]", text)
        self.assertIn("set_input_delay -clock clk -min 0.500 [get_ports {scan_in}]", text)
        self.assertIn("set_output_delay -clock clk -max 2.500 [get_ports {scan_out}]", text)
        self.assertNotIn("set_case_analysis", text)
        self.assertNotIn("set_multicycle_path", text)
        self.assertIn("set_max_transition 1.400 [current_design]", text)
        self.assertEqual("data", classes["scan_en"])
        self.assertEqual(10, len(emitted))
        verification = sdc_author.verify_electrical_intent(text, enum, intent)
        self.assertTrue(verification["pass"])
        self.assertEqual(5, verification["verified_commands"])

    def test_missing_macro_electrical_intent_fails_closed(self):
        enum = {
            "clock_ports": ["clk u_ff/CLK"],
            "clock_pins": ["u_ff/CLK"],
            "inputs": ["clk", "rst_n", "data[0]"],
            "outputs": ["sum[0]"],
        }
        intent = {
            "clocks": {
                "clk": {
                    "period_ns": 20.0,
                    "source": "MYTOP4-HIERSOC-SPEC-1.0/SR-040",
                }
            },
            "input_delay_ns": {"value": 3.0, "source": "SR-041"},
            "output_delay_ns": {"value": 3.0, "source": "SR-041"},
        }
        lines, _, holes, _ = sdc_author.author_sdc(
            enum, intent, top="bsum16")
        self.assertIsNotNone(lines)
        self.assertEqual(
            {
                "clock_transition_not_supplied",
                "pre_cts_clock_latency_not_supplied",
                "macro_input_transition_not_supplied",
                "macro_output_load_not_supplied",
            },
            {hole["kind"] for hole in holes},
        )


if __name__ == "__main__":
    unittest.main()
