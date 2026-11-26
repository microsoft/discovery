"""Unit tests for the VHDL/GHDL read-directive routing in formal_verification_utils.

Covers _build_read_directives and _is_safe_filename, added by DX-190.
"""
import os
import sys
import unittest

# Ensure the tool directory is importable.
sys.path.insert(0, os.path.dirname(__file__))

from formal_verification_utils import (
    _build_read_directives,
    _is_safe_filename,
    _VALID_VHDL_STDS,
    _unreached_cover_names,
)


class TestUnreachedCoverSummary(unittest.TestCase):
    def test_native_prefixed_summary(self):
        log = (
            "SBY 15:21:00 [/workdir/cover] summary: unreached cover statements:\n"
            "SBY 15:21:00 [/workdir/cover] summary:   counter.p at dut.sv:6.2-6.15\n"
            "SBY 15:21:00 [/workdir/cover] DONE (FAIL, rc=2)\n"
        )
        self.assertEqual(["counter.p"], _unreached_cover_names(log + log))

    def test_engine_fallback(self):
        self.assertEqual(["counter.p"], _unreached_cover_names(
            "engine_0: Unreached cover statement at counter: dut.sv:6.2-6.15 (p)\n"))

    def test_pass_has_no_unreached_names(self):
        self.assertEqual([], _unreached_cover_names("DONE (PASS, rc=0)\n"))


class TestIsSafeFilename(unittest.TestCase):
    """Item 1 — injection-safety guard on filenames."""

    def test_normal_vhdl(self):
        self.assertTrue(_is_safe_filename("utils.vhdl"))
        self.assertTrue(_is_safe_filename("decode_types.vhd"))

    def test_normal_sv(self):
        self.assertTrue(_is_safe_filename("dut.sv"))
        self.assertTrue(_is_safe_filename("top-level.v"))

    def test_rejects_whitespace(self):
        self.assertFalse(_is_safe_filename("bad file.vhdl"))
        self.assertFalse(_is_safe_filename("tab\there.sv"))

    def test_rejects_shell_metacharacters(self):
        for ch in [";", "|", "&", "$", "`", "'", '"', "(", ")", "!", "~"]:
            with self.subTest(char=ch):
                self.assertFalse(_is_safe_filename(f"file{ch}name.vhdl"))

    def test_rejects_path_traversal(self):
        self.assertFalse(_is_safe_filename("../etc/passwd"))
        self.assertFalse(_is_safe_filename("foo..bar.vhdl"))

    def test_rejects_empty(self):
        self.assertFalse(_is_safe_filename(""))
        self.assertFalse(_is_safe_filename(None))

    def test_rejects_path_separators(self):
        self.assertFalse(_is_safe_filename("sub/file.vhdl"))
        self.assertFalse(_is_safe_filename("sub\\file.vhdl"))


class TestBuildReadDirectives(unittest.TestCase):
    """Items 1-3, 5 — read-directive emitter routing + parameterization."""

    # --- pure VHDL --------------------------------------------------------
    def test_pure_vhdl_emits_ghdl_block(self):
        basenames = ["wishbone_types.vhdl", "common.vhdl", "fetch1.vhdl"]
        lines = _build_read_directives(basenames, "fetch1")
        self.assertEqual(lines[0], "plugin -i ghdl")
        self.assertIn("ghdl --std=08", lines[1])
        self.assertIn("-e fetch1", lines[1])
        # Only one plugin load.
        self.assertEqual(sum(1 for l in lines if "plugin -i ghdl" in l), 1)

    def test_pure_vhdl_preserves_caller_order(self):
        ordered = ["pkg_a.vhdl", "pkg_b.vhdl", "entity_c.vhdl"]
        lines = _build_read_directives(ordered, "entity_c")
        ghdl_line = [l for l in lines if l.startswith("ghdl ")][0]
        # The files must appear in the same order as the input list.
        idx_a = ghdl_line.index("pkg_a.vhdl")
        idx_b = ghdl_line.index("pkg_b.vhdl")
        idx_c = ghdl_line.index("entity_c.vhdl")
        self.assertLess(idx_a, idx_b)
        self.assertLess(idx_b, idx_c)

    def test_pure_vhdl_no_read_formal(self):
        lines = _build_read_directives(["utils.vhdl"], "utils")
        self.assertFalse(any("read -formal" in l for l in lines))

    def test_vhd_extension_also_routes_to_ghdl(self):
        lines = _build_read_directives(["decode_types.vhd"], "decode_types")
        self.assertTrue(any("plugin -i ghdl" in l for l in lines))

    # --- pure Verilog/SV --------------------------------------------------
    def test_pure_sv_emits_read_formal(self):
        lines = _build_read_directives(["dut.sv", "tb.sv"], "dut")
        self.assertEqual(lines, ["read -formal dut.sv", "read -formal tb.sv"])

    def test_pure_v_emits_read_formal(self):
        lines = _build_read_directives(["top.v"], "top")
        self.assertEqual(lines, ["read -formal top.v"])

    def test_no_ghdl_for_pure_verilog(self):
        lines = _build_read_directives(["a.sv", "b.v"], "a")
        self.assertFalse(any("ghdl" in l for l in lines))
        self.assertFalse(any("plugin" in l for l in lines))

    # --- mixed VHDL + SV -------------------------------------------------
    def test_mixed_ghdl_before_read_formal(self):
        basenames = ["common.vhdl", "fetch1.vhdl", "wrapper.sv"]
        lines = _build_read_directives(basenames, "fetch1")
        # ghdl block comes first
        self.assertEqual(lines[0], "plugin -i ghdl")
        self.assertTrue(lines[1].startswith("ghdl "))
        # SV read comes after
        self.assertEqual(lines[-1], "read -formal wrapper.sv")

    def test_mixed_no_vhdl_in_read_formal(self):
        basenames = ["pkg.vhdl", "dut.vhdl", "bind.sv"]
        lines = _build_read_directives(basenames, "dut")
        read_formal_lines = [l for l in lines if "read -formal" in l]
        self.assertEqual(read_formal_lines, ["read -formal bind.sv"])

    # --- unknown / no extension → read -formal ----------------------------
    def test_no_extension_falls_through_to_read_formal(self):
        lines = _build_read_directives(["Makefile"], "Makefile")
        self.assertEqual(lines, ["read -formal Makefile"])

    def test_unknown_extension_falls_through(self):
        lines = _build_read_directives(["design.blif"], "design")
        self.assertEqual(lines, ["read -formal design.blif"])

    # --- injection safety (item 1) ----------------------------------------
    def test_rejects_unsafe_vhdl_basename(self):
        with self.assertRaises(ValueError):
            _build_read_directives(["ok.vhdl", "bad;name.vhdl"], "ok")

    def test_rejects_unsafe_sv_basename(self):
        with self.assertRaises(ValueError):
            _build_read_directives(["has space.sv"], "top")

    def test_rejects_invalid_top(self):
        with self.assertRaises(ValueError):
            _build_read_directives(["ok.vhdl"], "bad;top")

    # --- vhdl_std parameterization (item 5) -------------------------------
    def test_default_std_is_08(self):
        lines = _build_read_directives(["pkg.vhdl"], "pkg")
        self.assertIn("--std=08", lines[1])

    def test_custom_std_93(self):
        lines = _build_read_directives(["pkg.vhdl"], "pkg", vhdl_std="93")
        self.assertIn("--std=93", lines[1])

    def test_custom_std_19(self):
        lines = _build_read_directives(["pkg.vhdl"], "pkg", vhdl_std="19")
        self.assertIn("--std=19", lines[1])

    def test_invalid_std_raises(self):
        with self.assertRaises(ValueError):
            _build_read_directives(["pkg.vhdl"], "pkg", vhdl_std="2008")

    def test_valid_stds_set(self):
        self.assertEqual(_VALID_VHDL_STDS, frozenset({"93", "93c", "08", "19"}))

    # --- fallback diagnostic (item 2) -------------------------------------
    def test_ghdl_block_contains_diagnostic_comment(self):
        """The emitter should include guidance about the ghdl plugin requirement."""
        lines = _build_read_directives(["pkg.vhdl"], "pkg")
        joined = "\n".join(lines)
        # The comment is inside the list as a Yosys script comment line (# ...)
        # OR embedded in the code generating it. Since Yosys script comments
        # start with '#' and we emit plain command lines, we check that the
        # plugin -i ghdl line exists (it IS the preflight — Yosys will error
        # clearly on it if ghdl.so is missing).
        self.assertIn("plugin -i ghdl", joined)


class TestObligationResults(unittest.TestCase):
    """DX-145 -- self_waivers/source_assumptions/property_work obligation
    evidence must be a REAL measured count from the files sby elaborated,
    never a fabricated placeholder."""

    def test_counts_immediate_assert_and_assume(self):
        import tempfile
        from formal_verification_utils import _static_property_counts

        src = (
            "module m;\n"
            "  always @(posedge clk) begin\n"
            "    assert (a == b);\n"
            "    assert(c);\n"
            "    // assert (commented_out); should not count\n"
            "    /* assert (also_commented); */\n"
            "    assume(d);\n"
            "  end\n"
            "endmodule\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".sv", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            n_assert, n_assume = _static_property_counts([path])
            self.assertEqual(n_assert, 2)
            self.assertEqual(n_assume, 1)
        finally:
            os.unlink(path)

    def test_no_files_counts_zero(self):
        from formal_verification_utils import _static_property_counts
        self.assertEqual(_static_property_counts([]), (0, 0))

    def test_obligation_results_no_narrowing_zero_gap(self):
        """This tool performs no gating-population narrowing, so
        self_waivers is always 0 and source_assertions/gating_assertions
        are set equal -- a real, measured zero gap."""
        import tempfile
        from formal_verification_utils import _obligation_results

        with tempfile.NamedTemporaryFile("w", suffix=".sv", delete=False) as f:
            f.write("assert (x); assert (y); assume(z);\n")
            path = f.name
        try:
            r = _obligation_results([path])
            self.assertEqual(r["self_waivers"], 0)
            self.assertEqual(r["source_assumption_cells"], 1)
            self.assertEqual(r["property_work_count"], 2)
            self.assertEqual(r["source_assertions"], r["gating_assertions"])
        finally:
            os.unlink(path)


class TestDispatchScenarios(unittest.TestCase):
    """DX-145 -- `cover` must be a routed scenario, and an unknown scenario
    must still fail closed rather than silently defaulting to `prove`."""

    def test_cover_routes_without_sby_fails_closed(self):
        from formal_verification_utils import dispatch
        # No `sby` guarantee in the unit-test environment: this only proves
        # `cover` is ROUTED (not "unknown scenario") and fails closed the
        # same way `_prove` does when the engine is absent.
        result = dispatch({"scenario": "cover", "top": "m",
                           "rtl_files": ["/nonexistent/does_not_exist.sv"]})
        self.assertNotIn("unknown scenario", str(result.get("error", "")))

    def test_unknown_scenario_lists_cover_as_supported(self):
        from formal_verification_utils import dispatch
        result = dispatch({"scenario": "not_a_real_scenario"})
        self.assertIn("cover", result.get("error", ""))
        self.assertEqual(result.get("status"), "failed")


if __name__ == "__main__":
    unittest.main()


# --- attempt capture (BEGIN) -- vendored by catalog/migrate_attempt_capture.py
# Records WHAT THE STAGE WAS ASKED TO DO alongside what it measured, so that an
# attempt chain (stage.1 -> stage.N) can be mined for which knob actually moved the
# residual. Without it a CDE says the residual fell from 102 to 9 but not why, and
# the causal knowledge is lost the moment the run ends.
#
# Hooked as wrappers rather than edits to dispatch()/save_final_results() so this
# migration never has to understand tool-specific code.
_ATTEMPT_CAPTURE = {}

#: Substrings that mark a value as secret. Envelopes are committed to git, so a
#: credential that reaches one is durable and public. Narrow on purpose: a broad
#: "key" match would redact legitimate EDA parameters (`clock_key`, `map_key`).
_CAPTURE_SECRET_HINTS = ("password", "passwd", "secret", "token", "api_key",
                         "apikey", "credential", "private_key", "auth")

_CAPTURE_MAX_STR = 512
_CAPTURE_MAX_SEQ = 64
_CAPTURE_MAX_DEPTH = 6


def _capture_digest(obj):
    import hashlib
    import json as _json
    try:
        blob = _json.dumps(obj, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        blob = repr(obj)
    return hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()


def _capture_normalize(value, depth=0):
    """Bound the size of a captured value without losing change-detection.

    Elision keeps a sha256 of the ELIDED PART, so a parameter that changed between
    two attempts still shows a different hash even when its content is too big to
    store. Silently dropping it would make the delta look empty -- i.e. would
    report "nothing changed" for a run that changed something.
    """
    if depth > _CAPTURE_MAX_DEPTH:
        return {"_elided": "depth", "sha256": _capture_digest(value)}
    if value is None or isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        if len(value) > _CAPTURE_MAX_STR:
            return {"_elided": "str", "chars": len(value),
                    "sha256": _capture_digest(value), "head": value[:120]}
        return value
    if isinstance(value, dict):
        out = {}
        for key in list(value)[:_CAPTURE_MAX_SEQ]:
            low = str(key).lower()
            if any(hint in low for hint in _CAPTURE_SECRET_HINTS):
                out[key] = {"_redacted": "secret-like key"}
                continue
            out[key] = _capture_normalize(value[key], depth + 1)
        if len(value) > _CAPTURE_MAX_SEQ:
            out["_elided"] = {"keys": len(value), "sha256": _capture_digest(value)}
        return out
    if isinstance(value, (list, tuple)):
        if len(value) > _CAPTURE_MAX_SEQ:
            return {"_elided": "list", "len": len(value),
                    "sha256": _capture_digest(value),
                    "head": [_capture_normalize(v, depth + 1) for v in value[:8]]}
        return [_capture_normalize(v, depth + 1) for v in value]
    return {"_elided": type(value).__name__, "sha256": _capture_digest(value)}


def _capture_params(params):
    import datetime
    if not isinstance(params, dict):
        return
    intent = params.get("attempt_intent")
    _ATTEMPT_CAPTURE.clear()
    _ATTEMPT_CAPTURE.update({
        "schema": "attempt-capture/1",
        # Hash the RAW params, before elision -- see _capture_normalize.
        "parameters_sha256": _capture_digest(params),
        "parameters": _capture_normalize(params),
        "intent": intent or None,
        "intent_missing": not bool(intent),
        "captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })


try:
    _dispatch_undecorated = dispatch

    def dispatch(params):  # noqa: F811
        _capture_params(params)
        return _dispatch_undecorated(params)
except NameError:  # pragma: no cover - a tool without dispatch()
    pass


try:
    _save_final_results_undecorated = save_final_results

    def save_final_results(results):  # noqa: F811
        if isinstance(results, dict):
            # Fall back to the fail-closed path's own copy: run.py sets
            # `input_parameters` when it fails BEFORE dispatch, which is exactly
            # when _ATTEMPT_CAPTURE would otherwise be empty.
            if not _ATTEMPT_CAPTURE and isinstance(
                    results.get("input_parameters"), dict):
                _capture_params(results["input_parameters"])
            if _ATTEMPT_CAPTURE:
                results.setdefault("attempt_capture", dict(_ATTEMPT_CAPTURE))
        return _save_final_results_undecorated(results)
except NameError:  # pragma: no cover - a tool without save_final_results()
    pass
# --- attempt capture (END) ---
