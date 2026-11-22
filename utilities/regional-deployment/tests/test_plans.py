import argparse
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from support import Backend, SUB, TENANT, workflow
from deploy import write_json
from inputs import full_inputs, save_bundle, workspace_inputs
import regional_deploy as cli


class PlanTests(unittest.TestCase):
    def setup_runner(self, directory, retained=False):
        runner = workflow(directory)
        runner.context = Mock()
        backend = Backend()
        backend.offered["eastus2"] = []
        if retained:
            backend.source_compute = {"properties": {"provisioningState": "Succeeded"}, "tags": {"discovery.overridemrgregion": "eastus2"}}
        runner.az = backend.az
        return runner, backend

    def recommendations(self, runner, **kwargs):
        args = dict(failure_file=None, scope="auto", candidates=["centralus", "northcentralus"], allow_cross_geography=False, limit=3)
        args.update(kwargs)
        return cli.recommendation(runner, argparse.Namespace(**args))

    def selection(self, directory, runner, report, **kwargs):
        report_path = Path(directory)/"recommendation.json"
        write_json(report_path, report)
        args = dict(recommendation=str(report_path), accept_cross_region=True, region="centralus", mode=report["scope"],
                    name_prefix="fallback", target_resource_group="new-rg" if report["scope"] == "fresh" else None,
                    source_workspace=None, vnet_cidr="10.60.0.0/16", output_dir=str(Path(directory)/"selected"))
        args.update(kwargs)
        return cli.select_inputs(runner, argparse.Namespace(**args))

    def test_init_is_local_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory, patch("subprocess.run", side_effect=AssertionError("No Azure commands allowed")):
            args = ["init", "--subscription", SUB, "--tenant", TENANT, "--resource-group", "example-rg", "--name-prefix", "example",
                    "--workload-region", "eastus2", "--output-dir", str(Path(directory)/"source")]
            self.assertEqual(cli.main(args), 0)
            self.assertEqual(cli.main(args), 1)

    def test_fresh_and_reuse_recommendations_are_scoped_from_actual_compute_state(self):
        for retained, expected in ((False, "fresh"), (True, "workspace")):
            with self.subTest(retained=retained), tempfile.TemporaryDirectory() as directory:
                runner, backend = self.setup_runner(directory, retained)
                report = self.recommendations(runner)
                self.assertEqual(report["scope"], expected)
                self.assertTrue(report["diagnosis"]["actionable"])
                self.assertEqual([r["region"] for r in report["candidates"]], ["centralus", "northcentralus"])
                self.assertTrue(all(r["eligibleForPreflight"] for r in report["candidates"]))
                self.assertFalse(any(args[:1] == ["vm"] for _, args, _ in backend.calls) if retained else False)

    def test_no_observed_blocker_does_not_automatically_relocate(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, backend = self.setup_runner(directory); backend.offered["eastus2"] = ["standard"]
            report = self.recommendations(runner)
            self.assertFalse(report["diagnosis"]["actionable"])
            self.assertEqual(report["candidates"], [])

    def test_explicit_allocation_failure_can_override_green_catalog_not_access_or_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, backend = self.setup_runner(directory); backend.offered["eastus2"] = ["standard"]
            error = Path(directory)/"failure.json"; write_json(error, {"error": {"code": "InsufficientResourcesAvailable"}})
            self.assertTrue(self.recommendations(runner, failure_file=str(error))["candidates"])
            backend.calls.clear(); write_json(error, {"error": {"code": "RequestDisallowedByPolicy"}})
            self.assertFalse(self.recommendations(runner, failure_file=str(error))["diagnosis"]["actionable"])
            self.assertEqual(backend.calls, [])

    def test_compute_quota_is_not_misrepresented_as_workspace_only_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, _ = self.setup_runner(directory, True)
            error=Path(directory)/"failure.json";write_json(error,{"error":{"code":"VmSkuQuota"}})
            with self.assertRaises(ValueError):
                self.recommendations(runner,failure_file=str(error))

    def test_cannot_silently_duplicate_succeeded_compute(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, _ = self.setup_runner(directory, True)
            with self.assertRaises(ValueError):
                self.recommendations(runner, scope="fresh")

    def test_in_progress_source_compute_blocks_recommendation(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, backend = self.setup_runner(directory)
            backend.source_compute = {"properties":{"provisioningState":"Accepted"}}
            with self.assertRaises(ValueError):
                self.recommendations(runner)

    def test_healthy_workspace_does_not_generate_false_quota_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, backend = self.setup_runner(directory, True)
            backend.source_workspace = {"properties":{"provisioningState":"Succeeded"}}
            backend.model_free = 0
            report = self.recommendations(runner)
            self.assertFalse(report["diagnosis"]["actionable"])
            self.assertEqual(report["candidates"], [])

    def test_stale_missing_source_does_not_hide_another_healthy_compute_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, backend = self.setup_runner(directory, True)
            backend.owners = [{"name":"active-workspace","state":"Succeeded","computeId":runner.rg_id+"/providers/Microsoft.Discovery/supercomputers/"+runner.values["supercomputerName"]}]
            report = self.recommendations(runner)
            self.assertFalse(report["diagnosis"]["actionable"])
            self.assertEqual(report["candidates"], [])

    def test_location_queries_use_explicit_subscription_scoped_rest_not_cli_default(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, backend = self.setup_runner(directory)
            self.recommendations(runner)
            rows=[(args,kw) for label,args,kw in backend.calls if label=="subscription-locations"]
            self.assertEqual(len(rows),1)
            self.assertIn("https://management.azure.com"+runner.scope+"/locations?api-version=2022-12-01",rows[0][0])
            self.assertFalse(rows[0][1]["scoped"])

    def test_selected_fresh_stack_uses_an_explicit_different_group(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, _ = self.setup_runner(directory)
            report = self.recommendations(runner)
            path = self.selection(directory, runner, report)
            config = json.loads(path.read_text())
            self.assertEqual(config["resourceGroup"], "new-rg")
            self.assertEqual(config["location"], "eastus")
            self.assertEqual(config["dataPlaneLocation"], "centralus")
            self.assertEqual(config["parametersFile"], "parameters.json")
            self.assertTrue(config["regionalSelection"]["crossRegionApproved"])

    def test_fresh_plan_rejects_source_group_and_absent_group_approval(self):
        for target in (None, "source-rg"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                runner, _ = self.setup_runner(directory); report = self.recommendations(runner)
                with self.assertRaises(ValueError):
                    self.selection(directory, runner, report, target_resource_group=target)

    def test_workspace_plan_keeps_compute_storage_and_original_network_names(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, _ = self.setup_runner(directory, True)
            path = self.selection(directory, runner, self.recommendations(runner))
            cfg = json.loads(path.read_text())
            values = {k:v["value"] for k,v in json.loads((path.parent/"parameters.json").read_text())["parameters"].items()}
            self.assertEqual(cfg["deploymentMode"], "workspace")
            self.assertEqual(cfg["supercomputerDataPlaneLocation"], "eastus2")
            self.assertEqual(cfg["storageDataPlaneLocation"], "eastus2")
            self.assertEqual(cfg["dataPlaneLocation"], "centralus")
            self.assertEqual(cfg["retainedBlobPrivateIp"], "10.20.4.9")
            for key in ("supercomputerName", "nodePoolName", "storageContainerName", "storageAccountName"):
                self.assertEqual(values[key], runner.values[key])
            self.assertEqual(values["existingVnetName"], runner.values["vnetName"])
            self.assertNotEqual(values["vnetName"], runner.values["vnetName"])
            self.assertNotEqual(values["managedIdentityName"], runner.values["managedIdentityName"])

    def test_healthy_or_in_progress_workspace_is_never_detached_by_planning(self):
        for state in ("Succeeded", "Accepted", "Running", "Creating", "Canceled"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                runner, backend = self.setup_runner(directory, True); report = self.recommendations(runner)
                backend.source_workspace = {"properties": {"provisioningState": state}}
                with self.assertRaises(ValueError):
                    self.selection(directory, runner, report)

    def test_selection_requires_explicit_cross_region_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, _ = self.setup_runner(directory); report = self.recommendations(runner)
            with self.assertRaises(ValueError):
                self.selection(directory, runner, report, accept_cross_region=False)

    def test_stale_changed_future_or_failed_evidence_cannot_authorize_a_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, _ = self.setup_runner(directory); report = self.recommendations(runner)
            for field in ("sourceConfigHash", "sourceParametersHash", "codeHash", "scope"):
                changed = copy.deepcopy(report); changed[field] = "changed"
                with self.subTest(field=field), self.assertRaises(ValueError):
                    cli.assert_recommendation(changed, runner, "centralus", "fresh")
            now = datetime.now(timezone.utc)
            for delta in (-1, 3601):
                changed = copy.deepcopy(report); changed["time"] = (now-timedelta(seconds=delta)).isoformat()
                with self.assertRaises(ValueError):
                    cli.assert_recommendation(changed, runner, "centralus", "fresh", now)
            changed = copy.deepcopy(report); changed["candidates"][0]["checks"][0]["status"] = "UNKNOWN"
            with self.assertRaises(ValueError):
                cli.assert_recommendation(changed, runner, "centralus", "fresh")

    def test_compute_state_change_requires_a_new_preservation_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, backend = self.setup_runner(directory); report = self.recommendations(runner)
            backend.source_compute = {"properties": {"provisioningState": "Succeeded"}}
            with self.assertRaises(ValueError):
                self.selection(directory, runner, report)

    def test_overlap_and_invalid_networks_are_rejected(self):
        cfg, values = full_inputs(SUB, TENANT, "source-rg", "source", "eastus", "eastus2", "10.20.0.0/16")
        for cidr in ("10.20.0.0/16", "8.8.0.0/16", "10.60.0.0/24", "127.0.0.0/16"):
            with self.subTest(cidr=cidr), self.assertRaises(ValueError):
                workspace_inputs(cfg, values, "fallback", "centralus", cidr, "10.20.4.9")


if __name__ == "__main__":
    unittest.main()
