import copy
import tempfile
import unittest
from unittest.mock import Mock

from support import Backend, workflow
import capacity as c


class CapacityTests(unittest.TestCase):
    def test_quota_and_capacity_are_different(self):
        for code, kind in (("InsufficientQuota", "quota"), ("VmSkuQuota", "quota"),
                           ("QuotaExceeded", "quota"), ("InsufficientResourcesAvailable", "capacity"),
                           ("AKSCapacityHeavyUsage", "capacity")):
            with self.subTest(code=code):
                self.assertEqual(c.classify_failure({"error": {"code": code}})["kind"], kind)

    def test_policy_and_auth_failures_are_not_relocated(self):
        for code in c.BLOCKING_CODES:
            with self.subTest(code=code):
                report = c.classify_failure({"error": {"code": "DeploymentFailed", "details": [{"code": "InsufficientQuota"}, {"code": code}]}})
                self.assertFalse(report["actionable"])

    def test_generic_internal_error_and_free_text_are_unknown(self):
        for value in ({"error": {"code": "InternalServerError"}}, "Quota exceeded, maybe", {"status": "Failed"}):
            self.assertFalse(c.classify_failure(value)["actionable"])

    def test_canonical_compute_operation_not_allowed_quota_error_is_recognized(self):
        self.assertEqual(c.classify_failure({"error":{"code":"OperationNotAllowed","message":"Operation results in exceeding approved standardDSv6Family Cores quota."}})["kind"], "quota")
        self.assertFalse(c.classify_failure({"error":{"code":"OperationNotAllowed","message":"The operation is not allowed."}})["actionable"])

    def test_official_readiness_numeric_quota_evidence_is_accepted(self):
        self.assertTrue(c.classify_failure({"id":"model-quota","status":"Fail","data":{"available":10,"required":450}})["actionable"])

    def test_embedded_arm_status_message_is_parsed(self):
        result = c.classify_failure([{"properties": {"statusMessage": '{"error":{"code":"InsufficientResourcesAvailable"}}'}}])
        self.assertEqual(result["kind"], "capacity")

    def test_numeric_deficit_is_required_for_readiness_quota_trigger(self):
        row = {"kind": "quota", "status": "FAIL", "data": {"available": 100, "required": 450}}
        self.assertTrue(c.classify_failure(row)["actionable"])
        for available in (450, 1000, "0", None, False):
            row["data"]["available"] = available
            self.assertFalse(c.classify_failure(row)["actionable"])

    def test_read_only_allowlist_rejects_writes_and_tokens(self):
        runner = Mock()
        for arguments in (["group", "delete"], ["deployment", "group", "create"], ["account", "get-access-token"],
                          ["rest", "--method", "put", "--url", "https://management.azure.com/resource"],
                          ["rest", "--method", "post", "--url", "https://management.azure.com/resource"],
                          ["rest", "--method", "get", "--url", "https://attacker.example/resource"],
                          ["rest", "--method", "get", "--url", "https://management.azure.com@attacker.example/resource"]):
            with self.subTest(arguments=arguments), self.assertRaises(RuntimeError):
                c.read_query(runner, "test", arguments)
        runner.az.assert_not_called()

    def test_only_offerings_post_is_allowed(self):
        runner = Mock()
        c.read_query(runner, "test", ["rest", "--method", "post", "--url", "https://management.azure.com/providers/Microsoft.Search/fetchOfferings?api-version=test"])
        runner.az.assert_called_once()

    def test_nearest_same_geography_not_paired_region_assumption(self):
        rows = c.nearby_regions(Backend().locations, "eastus2")
        self.assertEqual([r["region"] for r in rows], ["centralus", "northcentralus"])
        self.assertAlmostEqual(rows[0]["distanceKm"], 111.2, places=1)

    def test_cross_geography_requires_explicit_option(self):
        rows = c.nearby_regions(Backend().locations, "eastus2", allow_cross_geography=True)
        self.assertEqual(rows[0]["region"], "japaneast")
        self.assertTrue(rows[0]["crossGeography"])

    def test_explicit_candidate_allowlist_and_unknown_location(self):
        self.assertEqual([r["region"] for r in c.nearby_regions(Backend().locations, "eastus2", ["northcentralus"])], ["northcentralus"])
        with self.assertRaises(ValueError):
            c.nearby_regions(Backend().locations, "eastus2", ["unknownregion"])
        malformed = copy.deepcopy(Backend().locations)
        malformed[0]["metadata"]["latitude"] = "NaN"
        with self.assertRaises(ValueError):
            c.nearby_regions(malformed, "eastus2")

    def test_model_unit_conversion_requires_matching_metadata(self):
        data = Backend().az("catalog", ["cognitiveservices", "model", "list"])
        self.assertEqual(c.model_quota_units(data, "gpt-5.4"), "OpenAI.GlobalStandard.gpt-5.4")
        data[0]["model"]["skus"][0]["rateLimits"][0]["unit"] = "Requests"
        with self.assertRaises(ValueError):
            c.model_quota_units(data, "gpt-5.4")

    def test_resume_counts_only_missing_model_allocations(self):
        self.assertEqual(c.remaining_model_tpm(None, None), 450000)
        self.assertEqual(c.remaining_model_tpm("Succeeded", None), 200000)
        self.assertEqual(c.remaining_model_tpm(None, "Succeeded"), 250000)
        self.assertEqual(c.remaining_model_tpm("Succeeded", "Succeeded"), 0)

    def probe(self, backend=None, compute=True, needed=450000):
        with tempfile.TemporaryDirectory() as directory:
            runner = workflow(directory)
            backend = backend or Backend()
            runner.az = backend.az
            return c.RegionProbe(runner).probe("centralus", compute, needed), backend

    def test_verified_candidate_never_claims_capacity_reservation(self):
        result, _ = self.probe()
        self.assertTrue(result["eligibleForPreflight"])
        self.assertFalse(result["capacityReserved"])
        self.assertTrue(result["policyAndNetworkApprovalRequired"])

    def test_search_capacity_failure_with_available_quota(self):
        backend = Backend(); backend.offered["centralus"] = []
        result, _ = self.probe(backend)
        self.assertFalse(result["eligibleForPreflight"])
        self.assertEqual(c.classify_failure(result)["kind"], "capacity")
        self.assertTrue(any(x["name"] == "Search Standard service count" and x["status"] == "PASS" for x in result["checks"]))

    def test_model_quota_deficit_is_not_capacity(self):
        backend = Backend(); backend.model_free = 200
        result, _ = self.probe(backend)
        self.assertEqual(c.classify_failure(result)["kind"], "quota")

    def test_unknown_or_blocked_model_status_never_passes(self):
        for status in ("Blocked", "InOverage", "Other"):
            backend = Backend(); backend.model_status = status
            result, _ = self.probe(backend)
            self.assertFalse(result["eligibleForPreflight"])
            self.assertFalse(c.classify_failure(result)["actionable"])

    def test_unknown_quota_units_never_pass(self):
        backend = Backend(); backend.model_rate = 20
        result, _ = self.probe(backend)
        self.assertFalse(result["eligibleForPreflight"])
        self.assertEqual(result["checks"][-1]["status"], "UNKNOWN")

    def test_denied_reads_are_unknown_not_zero_quota(self):
        backend = Backend(); backend.fail = True
        result, _ = self.probe(backend)
        self.assertFalse(result["eligibleForPreflight"])
        self.assertFalse(c.classify_failure(result)["actionable"])

    def test_workspace_probe_does_not_check_or_allocate_compute(self):
        result, backend = self.probe(compute=False)
        self.assertTrue(result["eligibleForPreflight"])
        self.assertFalse(any(args[0] == "vm" for _, args, _ in backend.calls))

    def test_compute_reserves_system_and_workload_nodes(self):
        result, backend = self.probe()
        family = next(x for x in result["checks"] if x["name"] == "Compute standarddsv6family")
        self.assertEqual(family["data"]["required"], 24)
        self.assertEqual(sum(args[:2]==["vm","list-skus"] for _,args,_ in backend.calls),1)

    def test_native_numeric_strings_are_normalized_but_unknown_is_not_unlimited(self):
        self.assertEqual(c.quota_values({"limit":"100","currentValue":"8"}),(100,8))
        for value in ("unknown","-1","NaN","Infinity",True):
            with self.assertRaises(ValueError):c.quota_values({"limit":value,"currentValue":"0"})

    def test_separate_compute_families_are_both_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = workflow(directory); runner.values["nodePoolVmSize"] = "Standard_E8s_v5"; runner.az = Backend().az
            result = c.RegionProbe(runner).probe("centralus")
            needs = {r["name"]: r["data"]["required"] for r in result["checks"] if r["name"].startswith("Compute ")}
            self.assertEqual(needs, {"Compute standarddsv6family": 12, "Compute standardesv5family": 24, "Compute cores": 36})

    def test_restricted_vm_and_insufficient_compute_quota_fail(self):
        backend = Backend(); backend.restricted = True; backend.compute_limit = 10
        result, _ = self.probe(backend)
        self.assertFalse(result["eligibleForPreflight"])
        self.assertEqual(c.classify_failure(result)["kind"], "quota")


if __name__ == "__main__":
    unittest.main()
