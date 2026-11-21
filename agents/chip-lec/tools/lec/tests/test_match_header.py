"""Tests for the EQY [match *] header fix (DX-191).

The EQY config parser requires pattern_sections like [match] to carry a
module-pattern argument, e.g. ``[match *]``.  A bare ``[match]`` raises a
syntax error at config parse time.  These tests assert the emitted config
uses the correct header.
"""
import os
import re
import sys
import textwrap
import unittest
from unittest.mock import patch

# Allow importing lec_utils without the container environment.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestMatchHeader(unittest.TestCase):
    """Assert the emitted EQY config contains ``[match *]`` (not bare ``[match]``)."""

    # ---- helpers ----
    def _build_match_block(self, params):
        """Replicate the match-block logic from _equiv to test in isolation."""
        _match_lines = []
        _kpm = params.get("key_point_mapping_file")
        if _kpm and os.path.exists(str(_kpm)):
            _match_lines.append(f"script {_kpm}")
        _eqy_match = params.get("eqy_match")
        _eqy_match_directives = params.get("eqy_match_directives")
        if isinstance(_eqy_match, str) and _eqy_match.strip():
            _match_lines.extend(_eqy_match.strip().splitlines())
        if isinstance(_eqy_match_directives, (list, tuple)) and _eqy_match_directives:
            _match_lines.extend(str(d) for d in _eqy_match_directives if str(d).strip())
        _match_module = params.get("eqy_match_module", "*")
        _match_block = (
            f"\n[match {_match_module}]\n" + "\n".join(_match_lines) + "\n"
        ) if _match_lines else ""
        return _match_block

    # ---- core tests ----
    def test_match_header_uses_wildcard(self):
        """Match section MUST emit ``[match *]``, never bare ``[match]``."""
        block = self._build_match_block({
            "eqy_match_directives": ["gate-nomatch foo"],
        })
        self.assertIn("[match *]", block)
        self.assertNotRegex(block, r"\[match\]\s")

    def test_custom_module_pattern(self):
        """Caller-supplied eqy_match_module overrides the default ``*``."""
        block = self._build_match_block({
            "eqy_match_directives": ["gate-nomatch bar"],
            "eqy_match_module": "my_top",
        })
        self.assertIn("[match my_top]", block)
        self.assertNotIn("[match *]", block)

    def test_no_match_block_when_empty(self):
        """When no match directives are given, no [match] section should appear."""
        block = self._build_match_block({})
        self.assertEqual(block, "")

    def test_two_inverter_config_with_match_star(self):
        """A minimal 2-inverter EQY config with ``[match *]`` + a ``gate-nomatch``
        directive should produce a syntactically valid config string (i.e., the
        ``[match *]`` header is well-formed)."""
        eqy_text = textwrap.dedent("""\
            [options]
            depth 5

            [gold]
            read_verilog gold.v
            prep -top inv_top

            [gate]
            read_verilog gate.v
            prep -top inv_top

            [match *]
            gate-nomatch foo

            [strategy sat]
            use sat
            depth 5
        """)
        # Assert header form is valid (section + module-pattern).
        match_headers = re.findall(r"^\[match\b.*\]", eqy_text, re.MULTILINE)
        self.assertTrue(len(match_headers) >= 1, "Expected at least one [match …] header")
        for hdr in match_headers:
            self.assertRegex(hdr, r"\[match\s+\S+\]",
                             f"Header {hdr!r} is bare [match] -- must have a module-pattern")

    def test_directives_appear_under_header(self):
        """Match directives must appear AFTER the ``[match *]`` header."""
        block = self._build_match_block({
            "eqy_match": "gate-nomatch baz\nmatch quux",
        })
        lines = block.strip().splitlines()
        self.assertEqual(lines[0], "[match *]")
        self.assertIn("gate-nomatch baz", lines)
        self.assertIn("match quux", lines)


class TestMatchHeaderIntegration(unittest.TestCase):
    """Import the real lec_utils module and exercise _equiv to confirm the
    emitted .eqy config contains ``[match *]``.  All I/O and subprocess calls
    are mocked so no container or EQY binary is needed."""

    @classmethod
    def setUpClass(cls):
        """Import lec_utils with a mock rtl_frontend to avoid container deps."""
        import types
        mock_frontend = types.ModuleType("rtl_frontend")
        mock_frontend.yosys_read_block = lambda files, top, params=None: (
            f"read_verilog {files[0]}"
        )
        sys.modules["rtl_frontend"] = mock_frontend
        # Now import lec_utils (it does `import rtl_frontend` at top level)
        import importlib
        cls.lec_utils = importlib.import_module("lec_utils")

    def test_equiv_emits_match_star_not_bare(self):
        """Run _equiv with mocked subprocess and verify the written .eqy file
        contains ``[match *]`` (not bare ``[match]``)."""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="dx191_test_")
        try:
            self.lec_utils._OUTPUT_DIR = tmpdir
            self.lec_utils._WORK_DIR = tmpdir

            fake_proc = type("FakeProc", (), {
                "stdout": "1 of 1 partitions proven\n"
                          "Successfully proved designs equivalent\n",
                "stderr": "",
                "returncode": 0,
            })()

            params = {
                "top": "inv_top",
                "reference": "module inv_top(input a, output y); assign y = ~a; endmodule",
                "revised": "module inv_top(input a, output y); assign y = ~a; endmodule",
                "eqy_match_directives": ["gate-nomatch foo"],
            }

            with patch("subprocess.run", return_value=fake_proc), \
                 patch.object(self.lec_utils, "_eqy_version", return_value="mock"), \
                 patch.object(self.lec_utils, "_yosys_version", return_value="mock"):
                result = self.lec_utils._equiv(params)

            # Read the emitted .eqy config
            eqy_path = os.path.join(tmpdir, "lec.eqy")
            self.assertTrue(os.path.exists(eqy_path), f"Expected {eqy_path} to exist")
            eqy_content = open(eqy_path).read()

            # Core assertion: [match *] present, bare [match] absent
            self.assertIn("[match *]", eqy_content,
                          "Emitted .eqy config must contain [match *]")
            bare_match = re.findall(r"^\[match\]", eqy_content, re.MULTILINE)
            self.assertEqual(bare_match, [],
                             f"Bare [match] found in emitted config: {bare_match}")
            self.assertIn("gate-nomatch foo", eqy_content)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_equiv_no_match_section_without_directives(self):
        """When no match directives are provided, the .eqy config should NOT
        contain any [match ...] section."""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="dx191_test_")
        try:
            self.lec_utils._OUTPUT_DIR = tmpdir
            self.lec_utils._WORK_DIR = tmpdir

            fake_proc = type("FakeProc", (), {
                "stdout": "1 of 1 partitions proven\n"
                          "Successfully proved designs equivalent\n",
                "stderr": "",
                "returncode": 0,
            })()

            params = {
                "top": "inv_top",
                "reference": "module inv_top(input a, output y); assign y = ~a; endmodule",
                "revised": "module inv_top(input a, output y); assign y = ~a; endmodule",
            }

            with patch("subprocess.run", return_value=fake_proc), \
                 patch.object(self.lec_utils, "_eqy_version", return_value="mock"), \
                 patch.object(self.lec_utils, "_yosys_version", return_value="mock"):
                result = self.lec_utils._equiv(params)

            eqy_path = os.path.join(tmpdir, "lec.eqy")
            eqy_content = open(eqy_path).read()
            match_headers = re.findall(r"^\[match\b", eqy_content, re.MULTILINE)
            self.assertEqual(match_headers, [],
                             "No [match] section should be emitted without directives")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_flat_fallback_lowers_both_sides_before_equiv_make(self):
        """The whole-design fallback must not feed processes to equiv_make."""
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="dx342_test_")
        try:
            self.lec_utils._OUTPUT_DIR = tmpdir
            self.lec_utils._WORK_DIR = tmpdir

            eqy_failure = type("FakeProc", (), {
                "stdout": "Failed to prove equivalence for 1/1 partitions:\n",
                "stderr": "",
                "returncode": 1,
            })()
            flat_failure = type("FakeProc", (), {
                "stdout": "ERROR: Gate module contains memories or processes.\n",
                "stderr": "",
                "returncode": 1,
            })()
            # DX-162: _equiv now measures each side's own flop/latch count
            # (two extra `yosys ... stat` subprocess.run calls) before the
            # eqy invocation, for the key-point-count plausibility gate.
            seq_stat = type("FakeProc", (), {
                "stdout": "",
                "stderr": "",
                "returncode": 0,
            })()
            params = {
                "top": "dut",
                "reference": "module dut(input a, output y); assign y = a; endmodule",
                "revised": (
                    "module dut(input a, output reg y); "
                    "always @* y = a; endmodule"
                ),
            }

            with patch("subprocess.run",
                       side_effect=[seq_stat, seq_stat, eqy_failure, flat_failure]), \
                 patch.object(self.lec_utils, "_eqy_version",
                              return_value="mock"), \
                 patch.object(self.lec_utils, "_yosys_version",
                              return_value="mock"):
                self.lec_utils._equiv(params)

            flat_path = os.path.join(tmpdir, "flat_equiv.ys")
            flat_script = open(flat_path).read()
            equiv_make = flat_script.index("equiv_make gold gate equiv")
            self.assertEqual(flat_script[:equiv_make].count("\nproc\n"), 2)
            self.assertEqual(flat_script[:equiv_make].count("\nmemory\n"), 2)
            self.assertEqual(
                flat_script[:equiv_make].count(
                    "\nrename -hide w:* c:*\n"),
                2)
            self.assertLess(
                flat_script.index(
                    "proc\nmemory\nasync2sync"),
                equiv_make)
            self.assertLess(
                flat_script.index(
                    "rename -hide w:* c:*\ndesign -stash gate"),
                equiv_make)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
