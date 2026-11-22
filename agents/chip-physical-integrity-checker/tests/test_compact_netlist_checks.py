import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "tools" / (
    "physical-integrity-checker") / "physical_integrity_checker_utils.py"
SPEC = importlib.util.spec_from_file_location("integrity_utils", SOURCE)
UTILS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UTILS)


class CompactNetlistChecksTest(unittest.TestCase):
    def test_quoted_and_unquoted_liberty_cell_names_match_netlist(self):
        liberty = 'cell ("sky130_fd_sc_hd__buf_1") {} cell (BUF) {}'
        with patch("builtins.open", return_value=io.StringIO(liberty)):
            cells = UTILS._liberty_cells(["fixture.lib"])
        self.assertEqual({"sky130_fd_sc_hd__buf_1", "BUF"}, cells)
        with patch("builtins.open", return_value=io.StringIO(
                "module TOP(input A, output X); "
                "sky130_fd_sc_hd__buf_1 u0(.A(A),.X(X)); endmodule")):
            self.assertEqual((0, []), UTILS._netlist_checks("fixture.v", cells))

    def check_netlist(self, text):
        with patch("builtins.open", return_value=io.StringIO(text)):
            return UTILS._netlist_checks("fixture.v", {"BUF"})

    def test_unknown_cell_after_module_header_is_detected(self):
        self.assertEqual((0, ["UNKNOWN"]), self.check_netlist(
            "module TOP(input A, output Y); UNKNOWN u0(.A(A), .Y(Y)); endmodule"))

    def test_known_cell_after_module_header_passes(self):
        self.assertEqual((0, []), self.check_netlist(
            "module TOP(input A, output Y); BUF u0(.A(A), .Y(Y)); endmodule"))

    def test_compact_assign_is_counted(self):
        self.assertEqual((1, []), self.check_netlist(
            "module TOP(input A, output Y); assign Y=A; endmodule"))

    def test_comments_do_not_add_cells_or_assigns(self):
        self.assertEqual((0, []), self.check_netlist(
            "/* UNKNOWN fake(); assign Y=A; */\n"
            "module TOP(input A, output Y);\n"
            "// UNKNOWN fake(); assign Y=A;\nBUF u0(.A(A), .Y(Y)); endmodule"))


if __name__ == "__main__":
    unittest.main()
