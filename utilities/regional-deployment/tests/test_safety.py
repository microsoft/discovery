from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from support import ROOT, SUB, TENANT, workflow
import deploy as d
from inputs import full_inputs, workspace_inputs
import workspace as w


class SafetyTests(unittest.TestCase):
    def test_preview_deletes_unknown_changes_and_foundation_modifies_are_blocked(self):
        for kind in ("Delete", "Unsupported", "Unexpected", "Deploy"):
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                d.inspect_changes({"status":"Succeeded", "changes":[{"changeType":kind,"resourceId":"/resource"}]},False)
        with self.assertRaises(RuntimeError):
            d.inspect_changes({"status":"Failed","changes":[]},False)

    def test_resume_cannot_touch_foundation(self):
        result = {"status":"Succeeded", "changes":[{"changeType":"Create","resourceId":"/providers/Microsoft.Network/virtualNetworks/new"}]}
        with self.assertRaises(RuntimeError):
            d.inspect_changes(result, True)

    def test_workspace_writes_are_exact_id_allowlisted(self):
        cfg, values = full_inputs(SUB, TENANT, "source-rg", "source", "eastus", "eastus2", "10.20.0.0/16")
        _, p = workspace_inputs(cfg, values, "fallback", "centralus", "10.60.0.0/16", "10.20.4.9")
        group = f"/subscriptions/{SUB}/resourceGroups/source-rg"
        allowed = w.workspace_write_ids(p, group)
        self.assertEqual(len(allowed), 14)
        self.assertNotIn((group+"/providers/Microsoft.Network/virtualNetworks/"+p["existingVnetName"]).lower(), allowed)
        self.assertEqual(len(w.workspace_write_ids(p, group, True)), 3)
        for resource in (group+"/providers/Microsoft.Discovery/supercomputers/"+p["supercomputerName"],
                         group+"/providers/Microsoft.Storage/storageAccounts/"+p["storageAccountName"],
                         group+"/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net/A/storage"):
            preview = {"status":"Succeeded","changes":[{"changeType":"Create","resourceId":resource}]}
            with self.subTest(resource=resource), self.assertRaises(RuntimeError):
                w.inspect_workspace_preview(preview,p,group)

    def test_workspace_initial_modify_is_blocked_even_with_approval_flag(self):
        cfg, values = full_inputs(SUB, TENANT, "source-rg", "source", "eastus", "eastus2", "10.20.0.0/16")
        _, p = workspace_inputs(cfg, values, "fallback", "centralus", "10.60.0.0/16", "10.20.4.9")
        group = f"/subscriptions/{SUB}/resourceGroups/source-rg"
        target = next(iter(w.workspace_write_ids(p, group)))
        with self.assertRaises(RuntimeError):
            w.inspect_workspace_preview({"status":"Succeeded","changes":[{"changeType":"Modify","resourceId":target}]},p,group,False,True)

    def test_compiled_core_and_resume_shapes_cannot_gain_other_writes(self):
        d.assert_resume_template({"resources":[{"type":"Microsoft.Discovery/"+x} for x in d.DISCOVERY_TYPES]})
        w.assert_workspace_template({"resources":[{"type":x} for x in w.CORE_TYPES]},True)
        with self.assertRaises(RuntimeError):
            w.assert_workspace_template({"resources":[{"type":x} for x in w.CORE_TYPES]+[{"type":"Microsoft.Discovery/supercomputers"}]},True)

    def test_failed_source_put_preserves_identity_network_tags_and_other_links(self):
        source = {"location":"eastus", "tags":{"version":"v2","discovery.overridemrgregion":"eastus2"},
                  "properties":{"provisioningState":"Failed","workspaceIdentity":{"id":"/identity","clientId":"readonly"},
                  "supercomputerIds":["/compute/a","/compute/b"],"agentSubnetId":"/agent","workspaceSubnetId":"/workspace",
                  "privateEndpointSubnetId":"/pe","workspaceApiUri":"https://readonly.example"}}
        payload = w.failed_workspace_detach_put_payload(source,"/compute/a")
        self.assertEqual(payload["tags"],source["tags"])
        self.assertEqual(payload["location"],source["location"])
        self.assertEqual(payload["properties"]["workspaceIdentity"],{"id":"/identity"})
        self.assertEqual(payload["properties"]["supercomputerIds"],["/compute/b"])
        for key in ("workspaceApiUri","provisioningState"):
            self.assertNotIn(key,payload["properties"])
        source["properties"]["provisioningState"]="Succeeded"
        with self.assertRaises(RuntimeError):
            w.failed_workspace_detach_put_payload(source,"/compute/a")

    def test_new_preflight_invalidates_old_success_even_before_failed_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=workflow(directory)
            d.write_json(runner.state_root/"latest-preflight.json",{"ok":True})
            runner.begin_preflight()
            report=json.loads((runner.state_root/"latest-preflight.json").read_text())
            self.assertFalse(report["ok"])
            with self.assertRaises(RuntimeError):
                d.assert_fresh_preflight(report,d.digest(runner.config_path),d.digest(runner.parameters_path))

    def test_deploy_requires_apply_and_postconfigure_requires_succeeded(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=workflow(directory,"deploy"); runner.context=Mock(); runner.az=Mock(side_effect=AssertionError("No writes"))
            with self.assertRaises(RuntimeError):runner.deploy()
            runner.az.assert_not_called()
            with self.assertRaises(RuntimeError):runner.postconfigure()
            runner.az.assert_not_called()

    def test_nonpublic_cloud_is_rejected_before_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=workflow(directory)
            runner.az=Mock(return_value={"id":SUB,"tenantId":TENANT,"environmentName":"AzureUSGovernment"})
            with self.assertRaises(RuntimeError):runner.context()
            self.assertEqual(runner.az.call_count,1)

    def test_failed_validation_invalidates_a_previous_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=workflow(directory)
            d.write_json(runner.state_root/"validated-deployment.json",{"valid":True})
            with self.assertRaises((RuntimeError,OSError)):runner.validate()
            self.assertFalse(json.loads((runner.state_root/"validated-deployment.json").read_text())["valid"])

    def test_receipts_bind_compiled_parameters_config_code_and_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            runner=workflow(directory,"deploy",apply=True); runner.context=Mock()
            template=ROOT/"templates/main.bicep"; compiled=Path(directory)/"compiled.json"; params=Path(directory)/"filtered.json"
            d.write_json(compiled,{});d.write_json(params,{})
            now=datetime.now(timezone.utc).isoformat()
            report={"ok":True,"time":now,"configHash":d.digest(runner.config_path),"parametersHash":d.digest(runner.parameters_path),"codeHash":runner.code_hash()}
            d.write_json(runner.state_root/"latest-preflight.json",report)
            receipt=dict(report,valid=True,stage="full",template=str(template),templateHash=d.digest(template),compiled=str(compiled),compiledHash=d.digest(compiled),
                         filteredParameters=str(params),filteredParametersHash=d.digest(params))
            d.write_json(runner.state_root/"validated-deployment.json",receipt)
            runner.az=Mock(return_value={"properties":{"provisioningState":"Running"}})
            with self.assertRaisesRegex(RuntimeError,"already running"):runner.deploy()
            self.assertEqual(runner.az.call_count,1)
            runner.az.reset_mock();compiled.write_text('{"changed":true}')
            with self.assertRaisesRegex(RuntimeError,"Validated input changed"):runner.deploy()
            runner.az.assert_not_called()

    def test_scope_boundaries_and_conditional_roles_are_not_trusted(self):
        self.assertFalse(d.scope_covers("/subscriptions/s/resourceGroups/r","/subscriptions/s/resourceGroups/rogue"))
        self.assertFalse(d.has_role([{"roleDefinitionId":"/roles/test","scope":"/","condition":"restricted"}],"test","/target"))

    def test_nsp_preparation_does_not_reuse_privileged_or_restricted_custom_roles(self):
        role={"permissions":[{"actions":sorted(d.NSP_ACTIONS)}]}
        self.assertTrue(d.is_minimal_nsp_role(role))
        role["permissions"][0]["actions"].append("Microsoft.Authorization/roleAssignments/write")
        self.assertFalse(d.is_minimal_nsp_role(role))
        role["permissions"][0]["actions"]=sorted(d.NSP_ACTIONS)
        role["permissions"][0]["notActions"]=[next(iter(d.NSP_ACTIONS))]
        self.assertFalse(d.is_minimal_nsp_role(role))

    def test_unsupported_preview_is_blocked_even_with_modify_approval(self):
        with self.assertRaises(RuntimeError):
            d.inspect_changes({"status":"Succeeded","changes":[{"changeType":"Unsupported","resourceId":"/resource"}]},False,True)

    def test_authenticated_api_rejects_unexpected_hosts_and_project_paths(self):
        for uri in ("https://attacker.example","http://test.workspace.discovery.azure.com","https://test.workspace.discovery.azure.com@attacker.example"):
            with self.assertRaises(RuntimeError):
                d.project_agents_url({"properties":{"workspaceApiUri":uri}},"test","project","2026-06-01")

    def test_workspace_template_never_adds_a_second_customer_blob_endpoint_or_skip_tags(self):
        text=(ROOT/"templates/workspace.bicep").read_text()
        self.assertNotIn("Microsoft.Network/privateEndpoints@",text)
        self.assertNotIn("SkipAssociate",text)
        for name in ("storageAccount","retainedVnet","blobDns","supercomputer","storageContainer"):
            self.assertRegex(text,r"resource "+name+r" .* existing =")


if __name__ == "__main__":
    unittest.main()
