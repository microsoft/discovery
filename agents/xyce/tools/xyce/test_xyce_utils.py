"""Unit tests for xyce_utils.py (no Xyce binary needed)."""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(__file__))
from xyce_utils import (
    parse_subcircuit, detect_pdk, classify_port, classify_ports,
    generate_testbench, parse_prn_file, parse_mt0_file, generate_summary
)

SAMPLE_INVERTER = """
.subckt inverter in out vdd vss
M1 out in vdd vdd sky130_fd_pr__pfet_01v8 w=1u l=0.15u
M2 out in vss vss sky130_fd_pr__nfet_01v8 w=0.5u l=0.15u
.ends inverter
"""

SAMPLE_NAND = """
.subckt nand2 a b out vdd gnd
M1 out a vdd vdd sky130_fd_pr__pfet_01v8 w=1u l=0.15u
M2 out b vdd vdd sky130_fd_pr__pfet_01v8 w=1u l=0.15u
M3 out a mid gnd sky130_fd_pr__nfet_01v8 w=0.5u l=0.15u
M4 mid b gnd gnd sky130_fd_pr__nfet_01v8 w=0.5u l=0.15u
.ends nand2
"""

SAMPLE_WITH_ANALYSIS = """
* RC circuit
R1 1 2 1k
C1 2 0 1u
V1 1 0 PULSE(0 5 0 1n 1n 5m 10m)
.tran 0.1m 20m
.print tran V(1) V(2)
.end
"""

SAMPLE_PRN = """Index  TIME  V(1)  V(2)
0  0.000000e+00  0.000000e+00  0.000000e+00
1  1.000000e-04  5.000000e+00  3.160000e-01
2  2.000000e-04  5.000000e+00  6.320000e-01
3  3.000000e-04  5.000000e+00  9.500000e-01
End of Xyce(TM) Simulation
"""

SAMPLE_MT0 = """v2_max v2_risetime
4.999999e+00 1.234567e-03
"""


class TestParseSubcircuit:
    def test_inverter(self):
        tmp = os.path.join(tempfile.gettempdir(), "test_inv.cir")
        try:
            with open(tmp, 'w') as f:
                f.write(SAMPLE_INVERTER)
            info = parse_subcircuit(tmp)
            assert info is not None
            assert info["name"] == "inverter"
            assert "in" in info["ports"]
            assert "out" in info["ports"]
            assert "vdd" in info["ports"]
            assert info["pdk_hint"] == "sky130"
            assert info["has_analysis"] is False
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_with_analysis(self):
        tmp = os.path.join(tempfile.gettempdir(), "test_rc.cir")
        try:
            with open(tmp, 'w') as f:
                f.write(SAMPLE_WITH_ANALYSIS)
            info = parse_subcircuit(tmp)
            assert info is not None
            assert info["has_analysis"] is True
            assert info["name"] is None
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_missing_file(self):
        info = parse_subcircuit("/nonexistent/file.cir")
        assert info is None


class TestDetectPdk:
    def test_sky130(self):
        assert detect_pdk("M1 out in vdd sky130_fd_pr__pfet_01v8") == "sky130"

    def test_gf180(self):
        assert detect_pdk("M1 out in vdd nfet_03v3") == "gf180mcu"

    def test_unknown(self):
        assert detect_pdk("R1 1 2 1k") is None


class TestClassifyPort:
    def test_power(self):
        assert classify_port("vdd") == "power"
        assert classify_port("VCC") == "power"

    def test_ground(self):
        assert classify_port("vss") == "ground"
        assert classify_port("GND") == "ground"

    def test_clock(self):
        assert classify_port("clk") == "clock"
        assert classify_port("CLOCK") == "clock"

    def test_reset(self):
        assert classify_port("rst") == "reset"
        assert classify_port("rst_n") == "reset"

    def test_output(self):
        assert classify_port("out") == "output"
        assert classify_port("Q") == "output"

    def test_input(self):
        assert classify_port("a") == "input"
        assert classify_port("data") == "input"


class TestClassifyPorts:
    def test_inverter(self):
        c = classify_ports(["in", "out", "vdd", "vss"])
        assert c["input"] == ["in"]
        assert c["output"] == ["out"]
        assert c["power"] == ["vdd"]
        assert c["ground"] == ["vss"]

    def test_nand(self):
        c = classify_ports(["a", "b", "out", "vdd", "gnd"])
        assert "a" in c["input"]
        assert "b" in c["input"]
        assert c["output"] == ["out"]
        assert c["power"] == ["vdd"]
        assert c["ground"] == ["gnd"]


class TestGenerateTestbench:
    def test_inverter_testbench(self):
        tmp = os.path.join(tempfile.gettempdir(), "test_gen.cir")
        try:
            with open(tmp, 'w') as f:
                f.write(SAMPLE_INVERTER)
            tb = generate_testbench(tmp, pdk="sky130", sim_time="100n")
            assert ".tran" in tb
            assert ".print" in tb
            assert "PULSE" in tb
            assert "1.8" in tb  # sky130 VDD
            assert ".measure" in tb
            assert "inverter" in tb
            assert "ASSUMPTIONS" in tb
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_gf180_testbench(self):
        tmp = os.path.join(tempfile.gettempdir(), "test_gen_gf.cir")
        try:
            with open(tmp, 'w') as f:
                f.write(SAMPLE_INVERTER.replace("sky130_fd_pr__pfet_01v8", "pfet_03v3").replace("sky130_fd_pr__nfet_01v8", "nfet_03v3"))
            tb = generate_testbench(tmp, pdk="gf180mcu")
            assert "3.3" in tb  # gf180 VDD
            assert "gf180mcu" in tb.lower() or "design.xyce" in tb
        finally:
            try: os.unlink(tmp)
            except OSError: pass


class TestParsePrn:
    def test_basic(self):
        tmp = os.path.join(tempfile.gettempdir(), "test.prn")
        try:
            with open(tmp, 'w') as f:
                f.write(SAMPLE_PRN)
            data = parse_prn_file(tmp)
            assert data["num_points"] == 4
            assert "V(1)" in data["columns"] or "V(2)" in data["columns"]
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_missing(self):
        data = parse_prn_file("/nonexistent.prn")
        assert "error" in data


class TestParseMt0:
    def test_basic(self):
        tmp = os.path.join(tempfile.gettempdir(), "test.mt0")
        try:
            with open(tmp, 'w') as f:
                f.write(SAMPLE_MT0)
            meas = parse_mt0_file(tmp)
            assert "v2_max" in meas
            assert meas["v2_max"] == pytest.approx(5.0, rel=1e-3)
        finally:
            try: os.unlink(tmp)
            except OSError: pass

    def test_missing(self):
        meas = parse_mt0_file("/nonexistent.mt0")
        assert meas == {}
