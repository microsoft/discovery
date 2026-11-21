"""Every variable the CTS script assembly computes must reach the script.

A block that is computed and then not spliced in is indistinguishable from one
that was never written: the run completes, the envelope looks healthy, and the
evidence is simply absent. Measured twice in this repo -- `chip-lec` computed
`_shared_model_read` and used it everywhere except the proof that decides the
gate, and this module's own inserted-cell census was defined and left out of
the script on the first pass, so `unapproved_inserted_count` reported `None`
(not measured) on a run that otherwise looked clean.
"""
import os
import re
import unittest

_SOURCE = os.path.join(os.path.dirname(__file__), "..", "cts_utils.py")


def _source():
    with open(_SOURCE, encoding="utf-8") as handle:
        return handle.read()


def _script_template(text):
    """The `script = f\"\"\"...\"\"\"` body inside `_cts()`."""
    match = re.search(r'script = f"""(.*?)"""', text, re.S)
    assert match, "CTS script template not found"
    return match.group(1)


class TestScriptTemplateUsesWhatItComputes(unittest.TestCase):
    SPLICED = ("_dont_use_tcl", "_census_pre", "_census_post", "_pdn_in",
               "_pdn_out", "_reconnect", "_cts_opts", "clkbuf_tcl", "wire_rc")

    def setUp(self):
        self.text = _source()
        self.template = _script_template(self.text)

    def test_every_expected_block_is_spliced_into_the_script(self):
        for name in self.SPLICED:
            self.assertIn("{%s}" % name, self.template,
                          "%s is computed but never reaches the script" % name)

    def test_census_brackets_the_clock_tree_synthesis_call(self):
        pre = self.template.index("{_census_pre}")
        cts = self.template.index("clock_tree_synthesis")
        post = self.template.index("{_census_post}")
        self.assertLess(pre, cts, "pre-census must run before CTS")
        self.assertLess(cts, post, "post-census must run after CTS")

    def test_dont_use_is_applied_before_clock_tree_synthesis(self):
        self.assertLess(self.template.index("{_dont_use_tcl}"),
                        self.template.index("clock_tree_synthesis"))

    def test_declared_wire_rc_precedes_clock_characterization(self):
        self.assertLess(self.template.index("{wire_rc}"),
                        self.template.index("clock_tree_synthesis"))

    def test_buf_list_is_braced_exactly_once(self):
        self.assertIn("-buf_list {clkbuf_tcl}", self.template)
        self.assertNotIn("-buf_list {clkbuf}", self.template)

    def test_sink_clustering_is_no_longer_hardcoded_into_the_call(self):
        # It must come through `_cts_opts` so the caller has an off-switch.
        line = next(l for l in self.template.splitlines()
                    if "clock_tree_synthesis" in l)
        self.assertNotIn("-sink_clustering_enable", line)
        self.assertIn("sink_clustering_enable", self.text)

    def test_census_post_is_referenced_more_than_once(self):
        # Defined AND used. A single occurrence is the defect this file guards.
        self.assertGreaterEqual(self.text.count("_census_post"), 2)


if __name__ == "__main__":
    unittest.main()
