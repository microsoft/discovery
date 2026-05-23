"""Unit tests for sta_utils.py (no OpenSTA binary needed)."""
import os
import sys
import tempfile
import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))
from sta_utils import (
    detect_clock_ports, detect_io_ports, generate_sdc,
    parse_sta_report, extract_section, extract_value
)

SAMPLE_NETLIST = """
module counter(clk, rst_n, en, count, overflow);
  input clk;
  input rst_n;
  input en;
  output [7:0] count;
  output overflow;
  wire _00_;
  sky130_fd_sc_hd__dfrtp_1 _reg0_ (.D(_00_), .CLK(clk), .RESET_B(rst_n), .Q(count[0]));
endmodule
"""

SAMPLE_LOG = """
Linking design: counter
============================================================
STATIC TIMING ANALYSIS REPORT
============================================================

Design:  counter
PDK:     sky130
Clock:   clk (period=10 ns)

=== Setup Timing (Max Delay) ===
Startpoint: en (input port clocked by clk)
Endpoint: _reg0_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

  Delay    Time   Description
---------------------------------------------------------
   0.00    0.00   clock clk (rise edge)
   2.00    2.00   input external delay
   0.10    2.10 ^ en (in)
   0.15    2.25 ^ _logic_/Z (sky130_fd_sc_hd__and2_0)
   0.12    2.37 ^ _reg0_/D (sky130_fd_sc_hd__dfrtp_1)
           2.37   data arrival time

  10.00   10.00   clock clk (rise edge)
   0.00   10.00   clock network delay (ideal)
  -0.10    9.90   library setup time
           9.90   data required time
---------------------------------------------------------
           9.90   data required time
          -2.37   data arrival time
---------------------------------------------------------
           7.53   slack (MET)

=== Hold Timing (Min Delay) ===
Startpoint: en (input port clocked by clk)
Endpoint: _reg0_ (rising edge-triggered flip-flop clocked by clk)

           0.12   slack (MET)

=== Worst Slack ===
Setup (max): 7.5300
Hold  (min): 0.1200

=== Timing Summary ===
No paths found.

=== Check Setup/Hold Violations ===
No violations found.
"""


class TestDetectClockPorts:
    def test_finds_clk(self):
        tmp = os.path.join(tempfile.gettempdir(), "test_clk.v")
        try:
            with open(tmp, 'w') as f:
                f.write(SAMPLE_NETLIST)
            clocks = detect_clock_ports(tmp)
            assert 'clk' in clocks
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_no_clock(self):
        tmp = os.path.join(tempfile.gettempdir(), "test_noclk.v")
        try:
            with open(tmp, 'w') as f:
                f.write("module top(data_in, data_out); input data_in; output data_out; endmodule")
            clocks = detect_clock_ports(tmp)
            assert len(clocks) == 0
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_missing_file(self):
        clocks = detect_clock_ports("/nonexistent/file.v")
        assert clocks == []


class TestDetectIoPorts:
    def test_finds_ports(self):
        tmp = os.path.join(tempfile.gettempdir(), "test_io.v")
        try:
            with open(tmp, 'w') as f:
                f.write(SAMPLE_NETLIST)
            io = detect_io_ports(tmp)
            assert 'clk' in io['inputs']
            assert 'rst_n' in io['inputs']
            assert 'en' in io['inputs']
            assert 'overflow' in io['outputs']
        finally:
            try: os.unlink(tmp)
            except OSError: pass


class TestGenerateSdc:
    def test_basic_sdc(self):
        tmp = os.path.join(tempfile.gettempdir(), "test_sdc.v")
        try:
            with open(tmp, 'w') as f:
                f.write(SAMPLE_NETLIST)
            sdc = generate_sdc(tmp, clk_port="clk", clk_period=10.0)
            assert 'create_clock' in sdc
            assert 'clk' in sdc
            assert 'set_input_delay' in sdc
            assert 'set_output_delay' in sdc
            assert 'ASSUMPTIONS' in sdc
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_custom_period(self):
        tmp = os.path.join(tempfile.gettempdir(), "test_sdc2.v")
        try:
            with open(tmp, 'w') as f:
                f.write(SAMPLE_NETLIST)
            sdc = generate_sdc(tmp, clk_port="clk", clk_period=5.0)
            assert '5.0' in sdc or '5' in sdc
            assert '200.0 MHz' in sdc
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_auto_detect_clock(self):
        tmp = os.path.join(tempfile.gettempdir(), "test_sdc3.v")
        try:
            with open(tmp, 'w') as f:
                f.write(SAMPLE_NETLIST)
            sdc = generate_sdc(tmp, clk_port="nonexistent", clk_period=10.0)
            assert 'clk' in sdc
        finally:
            try: os.unlink(tmp)
            except OSError: pass


class TestParseStaReport:
    def test_parse_report(self):
        tmp_path = os.path.join(tempfile.gettempdir(), "test_sta.log")
        try:
            with open(tmp_path, 'w') as f:
                f.write(SAMPLE_LOG)
            report = parse_sta_report(tmp_path)
            assert 'OPENSTA' in report
            assert '7.5300' in report
            assert 'MET' in report
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def test_missing_file(self):
        report = parse_sta_report("/nonexistent/file.log")
        assert 'ERROR' in report


class TestExtractValue:
    def test_setup_slack(self):
        val = extract_value(SAMPLE_LOG, r'Setup \(max\):\s*([-\d.]+)')
        assert val == pytest.approx(7.53, rel=1e-3)

    def test_hold_slack(self):
        val = extract_value(SAMPLE_LOG, r'Hold\s+\(min\):\s*([-\d.]+)')
        assert val == pytest.approx(0.12, rel=1e-3)

    def test_no_match(self):
        val = extract_value("no data here", r'Setup:\s*([-\d.]+)')
        assert val is None


class TestExtractSection:
    def test_extract_setup(self):
        section = extract_section(SAMPLE_LOG, "Setup Timing (Max Delay)", "Hold Timing (Min Delay)")
        assert section is not None
        assert 'slack (MET)' in section

    def test_no_section(self):
        section = extract_section("nothing here", "Setup", "Hold")
        assert section is None
