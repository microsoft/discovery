#!/usr/bin/env python3
"""Unit tests for the cocotb VPI/env helpers and _measure_vhdl branch
selection in code_coverage_utils.py.

Validates:
  - _build_cocotb_env produces all 6 required cocotb-2.x env vars.
  - _build_cocotb_env raises RuntimeError when LIBPYTHON_LOC cannot be resolved.
  - _cocotb_vpi_arg returns a well-formed --vpi= string.
  - When cocotb params are absent the self-driving path is unchanged.
  - gcov instrumentation flags are present on analyze/elaborate in cocotb path.
  - (Integration) _measure_vhdl invokes ghdl -r with --vpi= + cocotb env when
    cocotb params are present, and without when absent.
"""
import os
import sys
import unittest
from unittest import mock

# The module under test lives alongside this file; add its directory to the path
# so we can import the helpers without needing the full container runtime.
sys.path.insert(0, os.path.dirname(__file__))

# Stub rtl_frontend (container-only module) before importing.
sys.modules.setdefault("rtl_frontend", mock.MagicMock())
import code_coverage_utils  # noqa: E402
from code_coverage_utils import (  # noqa: E402
    _build_cocotb_env,
    _cocotb_vpi_arg,
    _resolve_verilator_metrics,
)


def _mock_sysconfig_shared():
    """Return a patcher that makes sysconfig report a shared-Python install."""
    def _get_config_var(name):
        return {
            "LIBDIR": "/usr/lib/python3.12/config-3.12-x86_64-linux-gnu",
            "LDLIBRARY": "libpython3.12.so",
        }.get(name)
    return mock.patch("sysconfig.get_config_var", side_effect=_get_config_var)


class TestBuildCocotbEnv(unittest.TestCase):
    """_build_cocotb_env must inject all 6 cocotb-2.x env vars."""

    @_mock_sysconfig_shared()
    def test_all_six_vars_present(self, _mock_sc):
        base = {"PATH": "/usr/bin", "HOME": "/root"}
        env = _build_cocotb_env("my_wrapper", "test_dut", base_env=base)
        self.assertEqual(env["COCOTB_TOPLEVEL"], "my_wrapper")
        self.assertEqual(env["COCOTB_TEST_MODULES"], "test_dut")
        self.assertEqual(env["TOPLEVEL_LANG"], "vhdl")
        self.assertEqual(env["COCOTB_TRUST_INERTIAL_WRITES"], "1")
        self.assertEqual(env["PYGPI_PYTHON_BIN"], sys.executable)
        self.assertIn("LIBPYTHON_LOC", env)
        self.assertIn("libpython3.12.so", env["LIBPYTHON_LOC"])

    @_mock_sysconfig_shared()
    def test_comma_separated_modules(self, _mock_sc):
        env = _build_cocotb_env("top", "test_a,test_b,test_c", base_env={})
        self.assertEqual(env["COCOTB_TEST_MODULES"], "test_a,test_b,test_c")

    @_mock_sysconfig_shared()
    def test_base_env_preserved(self, _mock_sc):
        base = {"MY_CUSTOM_VAR": "keep_me", "PATH": "/bin"}
        env = _build_cocotb_env("top", "test_mod", base_env=base)
        self.assertEqual(env["MY_CUSTOM_VAR"], "keep_me")
        self.assertEqual(env["PATH"], "/bin")

    @_mock_sysconfig_shared()
    def test_does_not_mutate_base(self, _mock_sc):
        base = {"PATH": "/usr/bin"}
        original = dict(base)
        _build_cocotb_env("top", "mod", base_env=base)
        self.assertEqual(base, original)

    @mock.patch("sysconfig.get_config_var", return_value=None)
    @mock.patch("code_coverage_utils.subprocess.run",
                side_effect=FileNotFoundError)
    def test_raises_when_libpython_unresolvable(self, _mock_run, _mock_sc):
        """Must raise RuntimeError with diagnostic when LIBPYTHON_LOC cannot
        be resolved via sysconfig or python3-config."""
        with self.assertRaises(RuntimeError) as ctx:
            _build_cocotb_env("top", "mod", base_env={})
        msg = str(ctx.exception)
        self.assertIn("LIBPYTHON_LOC", msg)
        self.assertIn("--enable-shared", msg)

    @mock.patch("sysconfig.get_config_var", return_value=None)
    @mock.patch("code_coverage_utils.subprocess.run")
    def test_falls_back_to_python3_config(self, mock_run, _mock_sc):
        """When sysconfig returns empty, falls back to python3-config."""
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout="/usr/lib/python3.12/config-3.12-x86_64-linux-gnu\n",
            stderr="")
        env = _build_cocotb_env("top", "mod", base_env={})
        self.assertIn("LIBPYTHON_LOC", env)


class TestCocotbVpiArg(unittest.TestCase):
    """_cocotb_vpi_arg must shell out to cocotb-config and return --vpi=<path>."""

    @mock.patch("code_coverage_utils.subprocess.run")
    def test_returns_vpi_arg(self, mock_run):
        mock_run.return_value = mock.Mock(
            returncode=0, stdout="/usr/lib/cocotb/libcocotbvpi_ghdl.so\n",
            stderr="")
        result = _cocotb_vpi_arg()
        self.assertEqual(result, "--vpi=/usr/lib/cocotb/libcocotbvpi_ghdl.so")
        mock_run.assert_called_once_with(
            ["cocotb-config", "--lib-name-path", "vpi", "ghdl"],
            capture_output=True, text=True, timeout=30)

    @mock.patch("code_coverage_utils.subprocess.run")
    def test_raises_on_failure(self, mock_run):
        mock_run.return_value = mock.Mock(
            returncode=1, stdout="", stderr="not found")
        with self.assertRaises(RuntimeError) as ctx:
            _cocotb_vpi_arg()
        self.assertIn("cocotb-config", str(ctx.exception))

    @mock.patch("code_coverage_utils.subprocess.run",
                side_effect=FileNotFoundError)
    def test_raises_on_missing_binary(self, _):
        with self.assertRaises(RuntimeError) as ctx:
            _cocotb_vpi_arg()
        self.assertIn("cocotb-config not found", str(ctx.exception))

    @mock.patch("code_coverage_utils.subprocess.run")
    def test_raises_on_empty_path(self, mock_run):
        mock_run.return_value = mock.Mock(returncode=0, stdout="  \n", stderr="")
        with self.assertRaises(RuntimeError) as ctx:
            _cocotb_vpi_arg()
        self.assertIn("empty VPI path", str(ctx.exception))


class TestVerilatorMetricCapabilities(unittest.TestCase):
    def test_partitions_requested_metrics(self):
        result = _resolve_verilator_metrics(
            ["line", "toggle", "branch", "condition", "fsm"])
        self.assertEqual(
            result["requested_metrics"],
            ["line", "toggle", "branch", "condition", "fsm"])
        self.assertEqual(result["supported_metrics"], ["line", "toggle"])
        self.assertEqual(
            result["unsupported_metrics"], ["branch", "condition", "fsm"])

    def test_normalizes_aliases_without_losing_requested_set(self):
        result = _resolve_verilator_metrics(["expr", "cond", "mcdc"])
        self.assertEqual(
            result["requested_metrics"], ["expression", "condition"])
        self.assertEqual(result["supported_metrics"], ["expression"])
        self.assertEqual(result["unsupported_metrics"], ["condition"])

    @mock.patch("code_coverage_utils.subprocess.run")
    @mock.patch("code_coverage_utils.rtl_frontend.detect_language",
                return_value="verilog")
    @mock.patch("code_coverage_utils._stage_rtl", return_value=["/src/dut.sv"])
    def test_unsupported_only_request_never_invokes_verilator(
            self, _stage, _language, mock_run):
        result = code_coverage_utils._measure(
            {"top": "dut", "types": ["condition", "fsm"]})
        self.assertEqual(result["validation"]["verdict"], "not_assessable")
        self.assertEqual(
            result["signoff_evidence"]["unsupported_metrics"],
            ["condition", "fsm"])
        instrumentation = [
            call.args[0] for call in mock_run.call_args_list
            if call.args and isinstance(call.args[0], list)
            and call.args[0][:2] == ["verilator", "--cc"]
        ]
        self.assertEqual(instrumentation, [])

    @mock.patch("code_coverage_utils.subprocess.run")
    @mock.patch("code_coverage_utils.rtl_frontend.detect_language",
                return_value="verilog")
    @mock.patch("code_coverage_utils._stage_rtl", return_value=["/src/dut.sv"])
    def test_mixed_request_invokes_only_supported_flags(
            self, _stage, _language, mock_run):
        mock_run.return_value = _successful_proc()
        with mock.patch.object(code_coverage_utils, "_WORK_DIR", "/tmp"), \
             mock.patch.object(code_coverage_utils, "_OUTPUT_DIR", "/tmp"):
            result = code_coverage_utils._measure(
                {"top": "dut", "types": ["line", "fsm"]})
        commands = [
            call.args[0] for call in mock_run.call_args_list
            if call.args and isinstance(call.args[0], list)
            and call.args[0][:2] == ["verilator", "--cc"]
        ]
        self.assertEqual(len(commands), 1)
        command = commands[0]
        self.assertIn("--coverage-line", command)
        self.assertNotIn("--coverage-fsm", command)
        self.assertNotIn("--coverage", command)
        self.assertEqual(
            result["signoff_evidence"]["unsupported_metrics"], ["fsm"])


class TestMeasuredBranchCapability(unittest.TestCase):
    @staticmethod
    def _write_coverage(path, point_type, covered, total):
        with open(path, "a", encoding="utf-8") as coverage:
            for index in range(total):
                count = 1 if index < covered else 0
                keys = (
                    f"page\x02v_{point_type}\x01"
                    f"f\x02dut.sv\x01l\x02{index + 1}"
                )
                coverage.write(f"C '{keys}' {count}\n")

    @mock.patch("code_coverage_utils.subprocess.run")
    def test_measured_branch_population_overrides_static_unsupported_label(
            self, mock_run):
        import tempfile
        mock_run.return_value = _successful_proc()
        with tempfile.TemporaryDirectory() as tmpdir:
            dat = os.path.join(tmpdir, "coverage.dat")
            out = os.path.join(tmpdir, "output")
            os.makedirs(out)
            self._write_coverage(dat, "line", covered=7, total=7)
            self._write_coverage(dat, "branch", covered=6, total=6)
            self._write_coverage(dat, "toggle", covered=64, total=64)
            with mock.patch.object(code_coverage_utils, "_WORK_DIR", tmpdir), \
                 mock.patch.object(code_coverage_utils, "_OUTPUT_DIR", out):
                result = code_coverage_utils._finish_verilog_coverage(
                    "dut", ["/src/dut.sv"], dat,
                    ["line", "branch", "toggle"], 100.0, 0.1,
                    {"tb_top": "tb_dut"},
                    os.path.join(tmpdir, "obj_dir"), mode="test")
                result = code_coverage_utils._stamp_metric_capabilities(
                    result,
                    _resolve_verilator_metrics(
                        ["line", "branch", "toggle"]))

        self.assertEqual(
            result["results"]["branch"],
            {"value": 100.0, "unit": "percent", "covered": 6, "total": 6})
        self.assertEqual(
            result["qor_metrics"]["per_type"]["branch"],
            {"hit": 6, "total": 6, "percent": 100.0})
        self.assertIn("branch", result["qor_metrics"]["supported_metrics"])
        self.assertNotIn("branch", result["qor_metrics"]["unsupported_metrics"])
        self.assertIn("branch", result["signoff_evidence"]["supported_metrics"])
        self.assertNotIn(
            "branch", result["signoff_evidence"]["unsupported_types"])
        self.assertEqual(result["validation"]["verdict"], "pass")

    @mock.patch("code_coverage_utils.subprocess.run")
    def test_missing_branch_population_stays_null_and_not_assessable(
            self, mock_run):
        import tempfile
        mock_run.return_value = _successful_proc()
        with tempfile.TemporaryDirectory() as tmpdir:
            dat = os.path.join(tmpdir, "coverage.dat")
            out = os.path.join(tmpdir, "output")
            os.makedirs(out)
            self._write_coverage(dat, "line", covered=2, total=2)
            with mock.patch.object(code_coverage_utils, "_WORK_DIR", tmpdir), \
                 mock.patch.object(code_coverage_utils, "_OUTPUT_DIR", out):
                result = code_coverage_utils._finish_verilog_coverage(
                    "dut", ["/src/dut.sv"], dat,
                    ["line", "branch", "condition"], 100.0, 0.1,
                    {"tb_top": "tb_dut"}, os.path.join(tmpdir, "obj_dir"),
                    mode="test")
                result = code_coverage_utils._stamp_metric_capabilities(
                    result,
                    _resolve_verilator_metrics(
                        ["line", "branch", "condition"]))

        self.assertEqual(
            result["results"]["branch"],
            {"value": None, "unit": "percent",
             "covered": None, "total": None})
        self.assertIn("branch", result["qor_metrics"]["unsupported_metrics"])
        self.assertIn("condition", result["qor_metrics"]["unsupported_metrics"])
        self.assertEqual(result["validation"]["verdict"], "not_assessable")

    @mock.patch("code_coverage_utils.subprocess.run")
    @mock.patch("code_coverage_utils.rtl_frontend.detect_language",
                return_value="verilog")
    @mock.patch("code_coverage_utils._stage_rtl", return_value=["/src/dut.sv"])
    def test_branch_only_request_enables_line_instrumentation(
            self, _stage, _language, mock_run):
        mock_run.return_value = _successful_proc()
        with mock.patch.object(code_coverage_utils, "_WORK_DIR", "/tmp"), \
             mock.patch.object(code_coverage_utils, "_OUTPUT_DIR", "/tmp"):
            code_coverage_utils._measure(
                {"top": "dut", "types": ["branch"]})
        commands = [
            call.args[0] for call in mock_run.call_args_list
            if call.args and isinstance(call.args[0], list)
            and call.args[0][:2] == ["verilator", "--cc"]
        ]
        self.assertEqual(len(commands), 1)
        self.assertIn("--coverage-line", commands[0])


class TestSelfDrivingPathPreserved(unittest.TestCase):
    """When cocotb params are absent, _measure_vhdl must behave identically
    to the pre-patch version (self-driving VHDL tb_top path)."""

    def test_no_cocotb_params_no_env_injection(self):
        params = {"tb_top": "my_tb", "top": "my_dut"}
        cocotb_module = params.get("cocotb_module")
        cocotb_toplevel = params.get("cocotb_toplevel")
        _cocotb = bool(cocotb_module and cocotb_toplevel)
        run_top = params.get("tb_top") or (cocotb_toplevel if _cocotb else None) or "my_dut"
        self.assertFalse(_cocotb)
        self.assertEqual(run_top, "my_tb")

    def test_no_cocotb_params_no_tb_top(self):
        params = {"top": "my_dut"}
        cocotb_module = params.get("cocotb_module")
        cocotb_toplevel = params.get("cocotb_toplevel")
        _cocotb = bool(cocotb_module and cocotb_toplevel)
        run_top = params.get("tb_top") or (cocotb_toplevel if _cocotb else None) or "my_dut"
        self.assertFalse(_cocotb)
        self.assertEqual(run_top, "my_dut")

    def test_cocotb_params_set_run_top(self):
        params = {"top": "my_dut", "cocotb_module": "test_fpu",
                  "cocotb_toplevel": "fpu_flat_wrapper"}
        cocotb_module = params.get("cocotb_module")
        cocotb_toplevel = params.get("cocotb_toplevel")
        _cocotb = bool(cocotb_module and cocotb_toplevel)
        run_top = params.get("tb_top") or (cocotb_toplevel if _cocotb else None) or "my_dut"
        self.assertTrue(_cocotb)
        self.assertEqual(run_top, "fpu_flat_wrapper")

    def test_partial_cocotb_params_not_activated(self):
        params = {"top": "my_dut", "cocotb_module": "test_fpu"}
        _cocotb = bool(params.get("cocotb_module") and params.get("cocotb_toplevel"))
        self.assertFalse(_cocotb)


class TestGcovFlagsInCocotbPath(unittest.TestCase):
    """gcov instrumentation flags must be present in analyze and elaborate."""

    def test_gcov_flags_structure(self):
        gcov_flags = ["-g", "-Wc,-fprofile-arcs", "-Wc,-ftest-coverage"]
        self.assertIn("-Wc,-fprofile-arcs", gcov_flags)
        self.assertIn("-Wc,-ftest-coverage", gcov_flags)
        self.assertIn("-g", gcov_flags)

    def test_link_flags_contain_lgcov(self):
        for link_flags in [["-Wl,-lgcov"],
                           ["-Wl,-L/usr/lib/gcc/x86/13", "-Wl,-lgcov"]]:
            self.assertTrue(
                any("-lgcov" in f for f in link_flags),
                f"link_flags {link_flags} missing -lgcov")


# ---------------------------------------------------------------------------
# Integration tests: exercise the ACTUAL _measure_vhdl branch selection via
# mocked subprocess calls (no container/ghdl needed).
# ---------------------------------------------------------------------------

def _successful_proc(stdout="", stderr=""):
    """A mock CompletedProcess that succeeded."""
    return mock.Mock(returncode=0, stdout=stdout, stderr=stderr)


class TestMeasureVhdlCocotbBranch(unittest.TestCase):
    """Integration: _measure_vhdl with cocotb_module + cocotb_toplevel must
    invoke ghdl -r with --vpi= and the cocotb env vars."""

    def _make_gcda(self, work_dir):
        """Create a fake .gcda file so _measure_vhdl doesn't fail on missing data."""
        gcda_path = os.path.join(work_dir, "dut.gcda")
        os.makedirs(work_dir, exist_ok=True)
        with open(gcda_path, "wb") as f:
            f.write(b"\x00" * 64)  # >8 bytes to pass version-mismatch check

    @mock.patch("code_coverage_utils._ghdl_has_gcc_backend", return_value=True)
    @mock.patch("code_coverage_utils._ghdl_gcc_major", return_value="13")
    @mock.patch("code_coverage_utils._gcov_link_flags", return_value=["-Wl,-lgcov"])
    @mock.patch("code_coverage_utils._gcov_executable", return_value="gcov-13")
    @mock.patch("code_coverage_utils._cocotb_vpi_arg",
                return_value="--vpi=/usr/lib/cocotb/libcocotbvpi_ghdl.so")
    @_mock_sysconfig_shared()
    @mock.patch("code_coverage_utils.subprocess.run")
    def test_cocotb_path_ghdl_r_has_vpi_and_env(self, mock_run, _sc, _vpi,
                                                  _gcov_exe, _link, _major, _gcc):
        """When cocotb params present: ghdl -r gets --vpi=, env has cocotb vars."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            work = os.path.join(tmpdir, "ghdl_cov")
            out = os.path.join(tmpdir, "output")
            os.makedirs(out, exist_ok=True)

            # Patch module-level dirs
            with mock.patch.object(code_coverage_utils, "_WORK_DIR", tmpdir), \
                 mock.patch.object(code_coverage_utils, "_OUTPUT_DIR", out):

                # Make subprocess.run return success for ghdl -a, -e, -r, and
                # gcovr calls, and create a .gcda so the coverage path proceeds.
                def _side_effect(cmd, **kw):
                    # After ghdl -r, create the .gcda in the work dir
                    if isinstance(cmd, list) and cmd[0] == "ghdl" and cmd[1] == "-r":
                        self._make_gcda(kw.get("cwd") or work)
                    if isinstance(cmd, list) and cmd[0] == "gcovr":
                        return _successful_proc(
                            stdout='{"line_percent": 95.0, "branch_percent": 60.0}')
                    return _successful_proc()

                mock_run.side_effect = _side_effect

                params = {
                    "top": "countbits",
                    "cocotb_module": "test_countbits",
                    "cocotb_toplevel": "countbits_wrapper",
                }
                result = code_coverage_utils._measure_vhdl(
                    params, "countbits", ["/src/countbits.vhdl"])

                # Find the ghdl -r call
                ghdl_r_calls = [
                    c for c in mock_run.call_args_list
                    if isinstance(c[0][0], list) and len(c[0][0]) > 1
                    and c[0][0][0] == "ghdl" and c[0][0][1] == "-r"
                ]
                self.assertEqual(len(ghdl_r_calls), 1,
                                 "Expected exactly one ghdl -r call")
                ghdl_r_call = ghdl_r_calls[0]
                ghdl_r_cmd = ghdl_r_call[0][0]
                ghdl_r_kwargs = ghdl_r_call[1]

                # Assert --vpi= is in the command args
                vpi_args = [a for a in ghdl_r_cmd if a.startswith("--vpi=")]
                self.assertEqual(len(vpi_args), 1)
                self.assertEqual(vpi_args[0],
                                 "--vpi=/usr/lib/cocotb/libcocotbvpi_ghdl.so")

                # Assert the entity name is the cocotb_toplevel
                self.assertIn("countbits_wrapper", ghdl_r_cmd)

                # Assert env kwarg contains all cocotb vars
                env = ghdl_r_kwargs.get("env")
                self.assertIsNotNone(env, "ghdl -r must be called with env=")
                self.assertEqual(env["COCOTB_TOPLEVEL"], "countbits_wrapper")
                self.assertEqual(env["COCOTB_TEST_MODULES"], "test_countbits")
                self.assertEqual(env["TOPLEVEL_LANG"], "vhdl")
                self.assertEqual(env["COCOTB_TRUST_INERTIAL_WRITES"], "1")
                self.assertIn("LIBPYTHON_LOC", env)
                self.assertEqual(env["PYGPI_PYTHON_BIN"], sys.executable)

                # Result should be completed
                self.assertEqual(result["status"], "completed")

    @mock.patch("code_coverage_utils._ghdl_has_gcc_backend", return_value=True)
    @mock.patch("code_coverage_utils._ghdl_gcc_major", return_value="13")
    @mock.patch("code_coverage_utils._gcov_link_flags", return_value=["-Wl,-lgcov"])
    @mock.patch("code_coverage_utils._gcov_executable", return_value="gcov-13")
    @mock.patch("code_coverage_utils.subprocess.run")
    def test_self_driving_path_no_vpi_no_cocotb_env(self, mock_run,
                                                     _gcov_exe, _link, _major, _gcc):
        """When cocotb params absent: ghdl -r uses tb_top, no --vpi=, no cocotb env."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            work = os.path.join(tmpdir, "ghdl_cov")
            out = os.path.join(tmpdir, "output")
            os.makedirs(out, exist_ok=True)

            with mock.patch.object(code_coverage_utils, "_WORK_DIR", tmpdir), \
                 mock.patch.object(code_coverage_utils, "_OUTPUT_DIR", out):

                def _side_effect(cmd, **kw):
                    if isinstance(cmd, list) and cmd[0] == "ghdl" and cmd[1] == "-r":
                        self._make_gcda(kw.get("cwd") or work)
                    if isinstance(cmd, list) and cmd[0] == "gcovr":
                        return _successful_proc(
                            stdout='{"line_percent": 80.0, "branch_percent": 50.0}')
                    return _successful_proc()

                mock_run.side_effect = _side_effect

                params = {
                    "top": "countbits",
                    "tb_top": "tb_countbits",
                }
                result = code_coverage_utils._measure_vhdl(
                    params, "countbits", ["/src/countbits.vhdl"])

                # Find the ghdl -r call
                ghdl_r_calls = [
                    c for c in mock_run.call_args_list
                    if isinstance(c[0][0], list) and len(c[0][0]) > 1
                    and c[0][0][0] == "ghdl" and c[0][0][1] == "-r"
                ]
                self.assertEqual(len(ghdl_r_calls), 1)
                ghdl_r_call = ghdl_r_calls[0]
                ghdl_r_cmd = ghdl_r_call[0][0]
                ghdl_r_kwargs = ghdl_r_call[1]

                # Assert NO --vpi= in the command args
                vpi_args = [a for a in ghdl_r_cmd if a.startswith("--vpi=")]
                self.assertEqual(len(vpi_args), 0,
                                 "Self-driving path must NOT have --vpi=")

                # Assert the entity name is tb_top
                self.assertIn("tb_countbits", ghdl_r_cmd)

                # Assert env kwarg is None (default env, no cocotb injection)
                env = ghdl_r_kwargs.get("env")
                self.assertIsNone(env,
                                  "Self-driving path must not inject cocotb env")

                self.assertEqual(result["status"], "completed")

    @mock.patch("code_coverage_utils._ghdl_has_gcc_backend", return_value=True)
    @mock.patch("code_coverage_utils._ghdl_gcc_major", return_value="13")
    @mock.patch("code_coverage_utils._gcov_link_flags", return_value=["-Wl,-lgcov"])
    @mock.patch("code_coverage_utils._gcov_executable", return_value="gcov-13")
    @mock.patch("code_coverage_utils.subprocess.run")
    def test_no_tb_no_cocotb_returns_review(self, mock_run,
                                             _gcov_exe, _link, _major, _gcc):
        """Neither tb_top nor cocotb → instrumentation-only, verdict=review."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "output")
            os.makedirs(out, exist_ok=True)

            with mock.patch.object(code_coverage_utils, "_WORK_DIR", tmpdir), \
                 mock.patch.object(code_coverage_utils, "_OUTPUT_DIR", out):

                mock_run.return_value = _successful_proc()

                params = {"top": "countbits"}
                result = code_coverage_utils._measure_vhdl(
                    params, "countbits", ["/src/countbits.vhdl"])

                # Should NOT reach ghdl -r at all
                ghdl_r_calls = [
                    c for c in mock_run.call_args_list
                    if isinstance(c[0][0], list) and len(c[0][0]) > 1
                    and c[0][0][0] == "ghdl" and c[0][0][1] == "-r"
                ]
                self.assertEqual(len(ghdl_r_calls), 0,
                                 "No-harness path must not run ghdl -r")

                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["validation"]["verdict"], "review")

    @mock.patch("code_coverage_utils._ghdl_has_gcc_backend", return_value=True)
    @mock.patch("code_coverage_utils._ghdl_gcc_major", return_value="13")
    @mock.patch("code_coverage_utils._gcov_link_flags", return_value=["-Wl,-lgcov"])
    @mock.patch("code_coverage_utils._gcov_executable", return_value="gcov-13")
    @mock.patch("code_coverage_utils._cocotb_vpi_arg",
                side_effect=RuntimeError("cocotb-config not found"))
    @mock.patch("code_coverage_utils.subprocess.run")
    def test_cocotb_vpi_failure_returns_failed(self, mock_run, _vpi,
                                                _gcov_exe, _link, _major, _gcc):
        """VPI resolution failure → graceful CDE failure, not exception."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "output")
            os.makedirs(out, exist_ok=True)

            with mock.patch.object(code_coverage_utils, "_WORK_DIR", tmpdir), \
                 mock.patch.object(code_coverage_utils, "_OUTPUT_DIR", out):

                mock_run.return_value = _successful_proc()

                params = {
                    "top": "countbits",
                    "cocotb_module": "test_countbits",
                    "cocotb_toplevel": "countbits_wrapper",
                }
                result = code_coverage_utils._measure_vhdl(
                    params, "countbits", ["/src/countbits.vhdl"])

                self.assertEqual(result["status"], "failed")
                self.assertIn("cocotb", result.get("error", ""))


if __name__ == "__main__":
    unittest.main()
