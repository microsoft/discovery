"""Differential tests for DX-162's reference-authenticity gate.

Origin defect: `lec-post-synth.5` accepted a reference resolving to
`campaigns/mytop4-hiersoc/environment-smoke/retry-3/functional/cdc/input/
bsum16.v` -- a 951-byte environment-smoke-test fixture, not bsum16's
registered `rtl.N` output -- then compared the netlist synthesized FROM that
stub against the stub itself: internally consistent, therefore green,
therefore worthless. These tests cover both layers of the fix:
  1. CATEGORICAL: any reference/revised path with a fixture/scratch path
     SEGMENT (environment-smoke, scratch, fixtures, fixture) is refused
     outright, for every scenario, regardless of content.
  2. IDENTITY: for rtl_vs_netlist scenarios, when `revised` resolves to a
     recognizable `campaigns/<slug>/<design>/<design>.<N>/...` stage path,
     `reference`'s content hash must match the design's currently
     registered `rtl` stage output per that campaign's `versions.json`.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lec_utils import (
    _fixture_path_hit,
    _check_reference_authenticity,
    _parse_campaign_stage_path,
    _resolve_registered_rtl_file,
)


class TestFixturePathHit(unittest.TestCase):
    def test_environment_smoke_segment_is_flagged(self):
        self.assertEqual(
            _fixture_path_hit(
                "/x/campaigns/mytop4-hiersoc/environment-smoke/retry-3/"
                "functional/cdc/input/bsum16.v"),
            "environment-smoke")

    def test_scratch_and_fixtures_segments_are_flagged(self):
        self.assertEqual(_fixture_path_hit("/tmp/scratch/foo.v"), "scratch")
        self.assertEqual(_fixture_path_hit("/x/fixtures/foo.v"), "fixtures")
        self.assertEqual(_fixture_path_hit("/x/fixture/foo.v"), "fixture")

    def test_registered_stage_path_is_not_flagged(self):
        self.assertIsNone(_fixture_path_hit(
            "/x/campaigns/mytop4-hiersoc/bsum16/bsum16.1/rtl/rtl.2/results/"
            "bsum16.v"))

    def test_substring_is_not_a_false_positive(self):
        # A design or directory legitimately named e.g. `fixturebus` must not
        # be flagged just because it CONTAINS the substring "fixture".
        self.assertIsNone(_fixture_path_hit(
            "/x/campaigns/mytop4-hiersoc/fixturebus/fixturebus.1/rtl/rtl.1/"
            "results/fixturebus.v"))


class TestParseCampaignStagePath(unittest.TestCase):
    def test_parses_design_and_design_version(self):
        parsed = _parse_campaign_stage_path(
            "/x/campaigns/mytop4-hiersoc/bsum16/bsum16.1/synthesis/"
            "synthesis.5/results/netlist_mapped.v")
        self.assertEqual(parsed["design"], "bsum16")
        self.assertEqual(parsed["design_version"], "bsum16.1")
        self.assertTrue(parsed["campaign_root"].endswith(
            "campaigns/mytop4-hiersoc"))

    def test_non_campaign_path_returns_none(self):
        self.assertIsNone(_parse_campaign_stage_path("/tmp/scratch/foo.v"))


class TestReferenceAuthenticity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        # Build a synthetic campaign tree:
        #   campaigns/demo-campaign/mydes/mydes.1/rtl/rtl.1/results/mydes.v
        #   campaigns/demo-campaign/mydes/mydes.1/synthesis/synthesis.1/...
        #   campaigns/demo-campaign/versions.json
        self.campaign_root = os.path.join(self.root, "campaigns", "demo-campaign")
        rtl_results = os.path.join(
            self.campaign_root, "mydes", "mydes.1", "rtl", "rtl.1", "results")
        os.makedirs(rtl_results)
        self.registered_rtl = os.path.join(rtl_results, "mydes.v")
        with open(self.registered_rtl, "w") as f:
            f.write("module mydes(); endmodule\n")

        synth_results = os.path.join(
            self.campaign_root, "mydes", "mydes.1", "synthesis",
            "synthesis.1", "results")
        os.makedirs(synth_results)
        self.netlist = os.path.join(synth_results, "netlist_mapped.v")
        with open(self.netlist, "w") as f:
            f.write("module mydes(); endmodule\n")

        versions = {
            "designs": {
                "mydes": {
                    "design_versions": {
                        "mydes.1": {
                            "stages": {
                                "rtl": {"status": "completed",
                                        "dir": "rtl.1",
                                        "results": os.path.relpath(
                                            rtl_results, self.root)}
                            }
                        }
                    }
                }
            }
        }
        with open(os.path.join(self.campaign_root, "versions.json"), "w") as f:
            json.dump(versions, f)

        # A fixture-tree file with DIFFERENT content from the registered RTL.
        fixture_dir = os.path.join(
            self.campaign_root, "environment-smoke", "retry-1", "input")
        os.makedirs(fixture_dir)
        self.fixture_file = os.path.join(fixture_dir, "mydes.v")
        with open(self.fixture_file, "w") as f:
            f.write("module mydes(); assign scan_out = 1'b0; endmodule\n")

        # cwd matters for os.path.relpath resolution against repo root; run
        # authenticity checks with paths relative to self.root so
        # _resolve_registered_rtl_file's repo_root splice lines up.
        self._old_cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self._old_cwd)

    def test_fixture_reference_is_refused_categorically(self):
        params = {"scenario": "rtl_vs_netlist", "reference": self.fixture_file,
                  "revised": self.netlist}
        err = _check_reference_authenticity(params, "mydes")
        self.assertIsNotNone(err)
        self.assertIn("environment-smoke", err)
        self.assertIn("categorically refused", err)

    def test_reference_matching_registered_rtl_is_accepted(self):
        params = {"scenario": "rtl_vs_netlist", "reference": self.registered_rtl,
                  "revised": self.netlist}
        self.assertIsNone(_check_reference_authenticity(params, "mydes"))

    def test_reference_diverging_from_registered_rtl_is_refused(self):
        # A stale or wrong-design RTL file living INSIDE the design's own
        # rtl tree structurally, but whose content does not match the
        # registered rtl.1/results/mydes.v -- must still be refused.
        stale = os.path.join(os.path.dirname(self.registered_rtl), "stale.v")
        with open(stale, "w") as f:
            f.write("module mydes(); assign scan_out = 1'b1; endmodule\n")
        params = {"scenario": "rtl_vs_netlist", "reference": stale,
                  "revised": self.netlist}
        err = _check_reference_authenticity(params, "mydes")
        self.assertIsNotNone(err)
        self.assertIn("does not match the sha256", err)

    def test_non_campaign_context_is_not_assessed_not_a_pass(self):
        # No recognizable campaign stage path in `revised` -> the identity
        # check is skipped (unit-test/bare-invocation shape), but this must
        # not be conflated with a verified pass; the categorical check still
        # runs unconditionally regardless.
        params = {"scenario": "rtl_vs_netlist", "reference": self.fixture_file,
                  "revised": "/tmp/not_a_campaign_path.v"}
        err = _check_reference_authenticity(params, "mydes")
        self.assertIsNotNone(err)  # categorical fixture check still fires

    def test_netlist_vs_netlist_scenario_skips_identity_check(self):
        # Identity check only applies when `reference` is asserted to be
        # RTL; other scenarios still get the categorical fixture check.
        params = {"scenario": "netlist_vs_netlist", "reference": self.netlist,
                  "revised": self.netlist}
        self.assertIsNone(_check_reference_authenticity(params, "mydes"))


if __name__ == "__main__":
    unittest.main()
