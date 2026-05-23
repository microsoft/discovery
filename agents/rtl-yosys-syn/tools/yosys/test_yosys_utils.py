#!/usr/bin/env python3
"""Unit tests for yosys_utils.py -- run with pytest.

These tests exercise the log parsing and report formatting functions
without requiring the Yosys binary to be installed.
"""
import pytest
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from yosys_utils import (
    parse_yosys_log_text,
    parse_yosys_log,
    format_synth_report,
    generate_synth_script,
    SUPPORTED_PDKS,
)

# ============= Sample Yosys log output for testing =============
SAMPLE_LOG = """
Yosys 0.40 (git sha1 a1bb0255d, clang++ 15.0.0 -fPIC -Os)

-- Running command `read_verilog counter.v' --

1. Executing Verilog-2005 frontend: counter.v
Parsing Verilog input from `counter.v' to AST representation.
Generating RTLIL representation for module `\\counter'.
Successfully finished Verilog frontend.

-- Running command `synth -top counter' --

2. Executing SYNTH pass.

2.1. Executing HIERARCHY pass (managing design hierarchy).

=== counter ===

   Number of wires:                 15
   Number of wire bits:             47
   Number of public wires:           5
   Number of public wire bits:      37
   Number of memories:               0
   Number of memory bits:            0
   Number of processes:              0
   Number of cells:                 42
     $_AND_                          8
     $_DFF_P_                       16
     $_NOT_                          4
     $_OR_                           6
     $_XOR_                          8

2.12. Printing statistics.

=== counter ===

   Number of wires:                 15
   Number of wire bits:             47
   Number of public wires:           5
   Number of public wire bits:      37
   Number of memories:               0
   Number of memory bits:            0
   Number of processes:              0
   Number of cells:                 30
     sky130_fd_sc_hd__and2_1         6
     sky130_fd_sc_hd__dfxtp_1       16
     sky130_fd_sc_hd__inv_1          2
     sky130_fd_sc_hd__or2_1          4
     sky130_fd_sc_hd__xor2_1         2

   Chip area for module '\\counter': 247.939200

End of script.
"""

SAMPLE_LOG_MINIMAL = """
=== test ===

   Number of wires:                  3
   Number of wire bits:              3
   Number of cells:                  1
     $_AND_                          1

End of script.
"""


class TestParseLogText:
    def test_parse_full_log(self):
        stats = parse_yosys_log_text(SAMPLE_LOG)
        # Should pick up the LAST stat section (post-mapping)
        assert stats["total_cells"] == 30
        assert stats["wires"] == 15
        assert stats["wire_bits"] == 47
        assert stats["memories"] == 0
        assert stats["memory_bits"] == 0
        assert stats["processes"] == 0
        assert stats["area"] == pytest.approx(247.9392, rel=1e-3)

    def test_cell_breakdown(self):
        stats = parse_yosys_log_text(SAMPLE_LOG)
        cells = stats["cells"]
        # Post-mapping cells from the last stat block
        assert "sky130_fd_sc_hd__dfxtp_1" in cells
        assert cells["sky130_fd_sc_hd__dfxtp_1"] == 16

    def test_flip_flop_detection(self):
        stats = parse_yosys_log_text(SAMPLE_LOG)
        # dfxtp cells are DFF-type
        assert stats["flip_flops"] >= 16

    def test_minimal_log(self):
        stats = parse_yosys_log_text(SAMPLE_LOG_MINIMAL)
        assert stats["total_cells"] == 1
        assert stats["wires"] == 3
        assert stats["area"] == 0.0

    def test_empty_log(self):
        stats = parse_yosys_log_text("")
        assert stats["total_cells"] == 0
        assert stats["cells"] == {}
        assert stats["area"] == 0.0

    def test_raw_stat_captured(self):
        stats = parse_yosys_log_text(SAMPLE_LOG)
        assert "counter" in stats["raw_stat"]


class TestParseLogFile:
    def test_parse_from_file(self):
        tmp_path = os.path.join(tempfile.gettempdir(), "test_yosys_log.log")
        try:
            with open(tmp_path, 'w') as f:
                f.write(SAMPLE_LOG)
            stats = parse_yosys_log(tmp_path)
            assert stats["total_cells"] == 30
            assert stats["area"] == pytest.approx(247.9392, rel=1e-3)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def test_missing_file(self):
        with pytest.raises(FileNotFoundError):
            parse_yosys_log("/nonexistent/path/log.log")


class TestFormatReport:
    def test_basic_report(self):
        stats = parse_yosys_log_text(SAMPLE_LOG)
        report = format_synth_report(stats, pdk="sky130",
                                      source="counter.v", top="counter")
        assert "YOSYS SYNTHESIS REPORT" in report
        assert "sky130" in report
        assert "counter.v" in report
        assert "247.94" in report
        assert "Total cells:" in report

    def test_empty_stats_report(self):
        stats = parse_yosys_log_text("")
        report = format_synth_report(stats)
        assert "Total cells:   0" in report


class TestGenerateSynthScript:
    def test_basic_script(self):
        script = generate_synth_script(
            ["design.v"], "/output/netlist.v", pdk="sky130", top="top_mod"
        )
        assert "read_verilog design.v" in script
        assert "synth -top top_mod" in script
        assert "sky130" in script
        assert "write_verilog -noattr /output/netlist.v" in script

    def test_no_top(self):
        script = generate_synth_script(
            ["a.v", "b.v"], "/output/out.v", pdk="gf180mcu"
        )
        assert "read_verilog a.v" in script
        assert "read_verilog b.v" in script
        assert "synth\n" in script  # no -top
        assert "gf180mcu" in script

    def test_invalid_pdk(self):
        with pytest.raises(ValueError, match="Unsupported PDK"):
            generate_synth_script(["x.v"], "o.v", pdk="invalid_pdk")

    def test_extra_commands(self):
        script = generate_synth_script(
            ["x.v"], "o.v", pdk="sky130",
            extra_commands=["opt_clean", "opt -full"]
        )
        assert "opt_clean" in script
        assert "opt -full" in script


class TestSupportedPdks:
    def test_sky130_in_supported(self):
        assert "sky130" in SUPPORTED_PDKS

    def test_gf180mcu_in_supported(self):
        assert "gf180mcu" in SUPPORTED_PDKS

    def test_lib_filenames(self):
        for pdk, lib in SUPPORTED_PDKS.items():
            assert lib.endswith(".lib"), f"{pdk} lib file should end with .lib"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
