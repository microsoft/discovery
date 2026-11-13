#!/usr/bin/env python3
"""Workspace-only regional recovery, preserving existing Discovery compute/storage."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import ipaddress
import json
import sys
import time
import uuid

from deploy import (DISCOVERY_TYPES, NSP_ACTIONS, PERSONA_ROLES,
                            REQUIRED_PROVIDERS, ROOT, ROLES, Workflow, digest,
                            filter_parameters, has_role, inspect_changes,
                            resolve_managed_group, write_json, is_minimal_nsp_role)


CORE_TYPES = (
    "microsoft.discovery/workspaces", "microsoft.discovery/workspaces/chatmodeldeployments",
    "microsoft.discovery/workspaces/projects",
)


def failed_workspace_detach_payload(workspace, supercomputer_id):
    if workspace.get("properties", {}).get("provisioningState") != "Failed":
        raise RuntimeError("Only a confirmed Failed source workspace may release its compute link.")
    links = workspace["properties"].get("supercomputerIds", [])
    if not isinstance(links, list) or not all(isinstance(x, str) for x in links):
        raise RuntimeError("Source workspace compute links are not a valid ID list.")
    if not any(x.lower() == supercomputer_id.lower() for x in links):
        raise RuntimeError("Source workspace does not own the exact retained compute link; no PATCH permitted.")
    return {"properties": {"supercomputerIds": [x for x in links if x.lower() != supercomputer_id.lower()]}}


def failed_workspace_detach_put_payload(workspace, supercomputer_id):
    patch = failed_workspace_detach_payload(workspace, supercomputer_id)
    old = workspace["properties"]
    props = {"workspaceIdentity": {"id": old["workspaceIdentity"]["id"]},
             "supercomputerIds": patch["properties"]["supercomputerIds"]}
    for key in ["agentSubnetId", "privateEndpointSubnetId", "workspaceSubnetId", "publicNetworkAccess",
                "customerManagedKeys", "keyVaultProperties", "logAnalyticsClusterId"]:
        if key in old:
            props[key] = old[key]
    return {"location": workspace["location"], "tags": workspace.get("tags", {}), "properties": props}


def assert_workspace_template(compiled, core_only=False):
    expected = Counter(CORE_TYPES)
    if not core_only:
        expected.update({"microsoft.network/publicipaddresses": 1,
                         "microsoft.network/natgateways": 1,
                         "microsoft.network/virtualnetworks": 1,
                         "microsoft.managedidentity/userassignedidentities": 1,
                         "microsoft.authorization/roleassignments": 4,
                         "microsoft.network/virtualnetworks/virtualnetworkpeerings": 2,
                         "microsoft.network/privatednszones/virtualnetworklinks": 1})
    actual = Counter(r.get("type", "").lower() for r in compiled.get("resources", []))
    if actual != expected:
        raise RuntimeError("Workspace template has unexpected writes; compute, storage, DNS records and existing foundation must be references only.")


def workspace_write_ids(values, group, core_only=False):
    p = values
    ws = group + "/providers/Microsoft.Discovery/workspaces/" + p["workspaceName"]
    result = {ws, ws + "/chatModelDeployments/" + p["chatModelDeploymentName"],
              ws + "/projects/" + p["projectName"]}
    if core_only:
        return {x.lower() for x in result}
    vnet = group + "/providers/Microsoft.Network/virtualNetworks/" + p["vnetName"]
    retained = group + "/providers/Microsoft.Network/virtualNetworks/" + p["existingVnetName"]
    storage = group + "/providers/Microsoft.Storage/storageAccounts/" + p["storageAccountName"]
    result.update({vnet,
                   group + "/providers/Microsoft.Network/natGateways/" + p["natGatewayName"],
                   group + "/providers/Microsoft.Network/publicIPAddresses/" + p["natGatewayPublicIpName"],
                   group + "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/" + p["managedIdentityName"],
                   vnet + "/virtualNetworkPeerings/peer-to-retained-discovery",
                   retained + "/virtualNetworkPeerings/peer-to-" + p["vnetName"],
                   group + "/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net/virtualNetworkLinks/link-" + p["vnetName"]})
    for key, scope in [("platformRoleAssignmentName", group), ("acrPullRoleAssignmentName", group),
                       ("blobRoleAssignmentName", storage), ("networkRoleAssignmentName", vnet)]:
        uuid.UUID(p[key])
        result.add(scope + "/providers/Microsoft.Authorization/roleAssignments/" + p[key])
    return {x.lower() for x in result}


def inspect_workspace_preview(result, values, group, core_only=False, allow_modify=False):
    counts = inspect_changes(result, False, allow_modify and core_only)
    allowed = workspace_write_ids(values, group, core_only)
    for change in result.get("changes", []):
        if change["changeType"] not in ("Ignore", "NoChange") and change["resourceId"].lower() not in allowed:
            raise RuntimeError("Workspace preview touches an unapproved resource: " + change["resourceId"])
    return counts


class WorkspaceWorkflow(Workflow):
    @property
    def core_only(self):
        return self.args.stage == "workspace-core"

    def preflight(self):
        self.begin_preflight()
        self.context()
        self.check("Discovery control plane", self.location in ("eastus", "uksouth", "swedencentral"), self.location)
        self.check("Distinct workspace data plane", self.data_location != self.config["supercomputerDataPlaneLocation"], self.data_location)
        provider = self.az("discovery-provider", ["provider", "show", "--namespace", "Microsoft.Discovery"])
        types = {x["resourceType"].lower(): x for x in provider["resourceTypes"]}
        for name in DISCOVERY_TYPES:
            self.check("Discovery API " + name, self.config["apiVersion"] in types.get(name, {}).get("apiVersions", []), self.config["apiVersion"])
        providers = self.az("providers", ["provider", "list"])
        registered = {x["namespace"].lower() for x in providers if x["registrationState"] == "Registered"}
        self.check("Required providers", all("microsoft." + n.lower() in registered for n in REQUIRED_PROVIDERS), "registration article/quickstart union")
        user, cp = self.principals()
        user_roles = self.assignments("user-roles", user, self.rg_id)
        for role in PERSONA_ROLES:
            self.check("User " + role, has_role(user_roles, ROLES[role], self.rg_id), "existing scoped or inherited assignment")
        cp_roles = self.assignments("control-plane-roles", cp, self.scope)
        self.check("Control-plane Reader", has_role(cp_roles, ROLES["Reader"], self.scope), self.scope)
        definitions = self.az("custom-role-definitions", ["role", "definition", "list", "--custom-role-only", "true", "--scope", self.scope])
        self.check("Control-plane NSP", any(has_role(cp_roles, d["name"], self.scope) and is_minimal_nsp_role(d)
                   for d in definitions), "existing minimal first-party perimeter permissions")
        self.check_retained_resources()
        self.check_capacity(include_compute=False)
        report = {"time": datetime.now(timezone.utc).isoformat(), "ok": not any(c["state"] == "FAIL" for c in self.checks),
                  "checks": self.checks, "configHash": digest(self.config_path),
                  "parametersHash": digest(self.parameters_path), "codeHash": self.code_hash(), "evidence": str(self.out)}
        write_json(self.out / "preflight.json", report)
        write_json(self.state_root / "latest-preflight.json", report)
        if not report["ok"]:
            raise RuntimeError("Workspace preflight failed; no deployment submitted.")

    def check_retained_resources(self):
        p = self.values
        for index in (0, 1, 4):
            path = self.resource_paths()[index]
            obj = self.rest("retained-discovery-" + str(index), f"{self.rg_id}/providers/Microsoft.Discovery/{path}?api-version={self.config['apiVersion']}")
            props = obj.get("properties", {})
            self.check("Retained " + path, props.get("provisioningState") == "Succeeded" and obj.get("location") == self.location,
                       str(props.get("provisioningState")) + "; existing resource, never PUT")
            if index == 0:
                self.check("Retained compute region", obj.get("tags", {}).get("discovery.overridemrgregion") == self.config["supercomputerDataPlaneLocation"],
                           "not compared to the workspace data-plane region")
            if index == 4:
                self.check("Retained output store", props.get("storageStore", {}).get("storageAccountId", "").lower() ==
                           (self.rg_id + "/providers/Microsoft.Storage/storageAccounts/" + p["storageAccountName"]).lower(), "unchanged backing account")
        old_vnet = self.az("retained-vnet", ["network", "vnet", "show", "--resource-group", self.rg, "--name", p["existingVnetName"]])
        planned = ipaddress.ip_network(p["vnetAddressPrefix"])
        self.check("Non-overlapping workspace VNet", not any(planned.overlaps(ipaddress.ip_network(c)) for c in old_vnet["addressSpace"]["addressPrefixes"]),
                   str(planned) + "; global peering to existing VNet")
        storage = self.az("retained-storage", ["storage", "account", "show", "--resource-group", self.rg, "--name", p["storageAccountName"]])
        self.check("Storage remains private", storage.get("publicNetworkAccess") == "Disabled" and storage["location"] == self.config["storageDataPlaneLocation"], "no storage PUT or public-access change")
        dns = self.az("retained-blob-dns", ["network", "private-dns", "record-set", "a", "show", "--resource-group", self.rg,
                      "--zone-name", "privatelink.blob.core.windows.net", "--name", p["storageAccountName"]])
        self.check("Blob DNS record retained", {a["ipv4Address"] for a in dns.get("aRecords", [])} == {self.config["retainedBlobPrivateIp"]}, "reuse existing endpoint; never overwrite A record")
        pe = self.az("retained-blob-pe", ["network", "private-endpoint", "show", "--resource-group", self.rg, "--name", "pe-" + p["storageAccountName"] + "-blob"])
        self.check("Retained Blob endpoint", pe.get("provisioningState") == "Succeeded" and any(
                   c.get("privateLinkServiceConnectionState", {}).get("status") == "Approved" for c in pe.get("privateLinkServiceConnections", [])), "Approved endpoint reused through peering")
        new_vnet = self.az("workspace-vnet", ["network", "vnet", "show", "--resource-group", self.rg, "--name", p["vnetName"]], optional=True, not_found_only=True)
        identity = self.az("workspace-identity", ["identity", "show", "--resource-group", self.rg, "--name", p["managedIdentityName"]], optional=True, not_found_only=True)
        for name, obj in [("workspace VNet", new_vnet), ("workspace UAMI", identity)]:
            self.check(name, bool(obj and obj["location"] == self.data_location) if self.core_only else obj is None or obj["location"] == self.data_location,
                       "existing in target region" if obj else "planned new; required before workspace-core")
        if self.core_only and new_vnet:
            subnets = {item["name"]: item for item in new_vnet.get("subnets", [])}
            for name, prefix in (("workspaceSubnet", "workspaceSubnetPrefix"), ("agentSubnet", "agentSubnetPrefix"),
                                 ("privateEndpointSubnet", "privateEndpointSubnetPrefix")):
                self.check("Workspace subnet "+name, subnets.get(name, {}).get("addressPrefix") == p[prefix], "exact reviewed subnet prefix")
                if name != "privateEndpointSubnet":
                    self.check("Workspace delegation "+name, any(x.get("serviceName") == "Microsoft.App/environments" for x in subnets.get(name, {}).get("delegations", [])), "Container Apps delegation")
            for i, (vnet_name, peer_name) in enumerate(((p["vnetName"], "peer-to-retained-discovery"), (p["existingVnetName"], "peer-to-"+p["vnetName"]))):
                peer = self.az("core-peering-"+str(i), ["network", "vnet", "peering", "show", "--resource-group", self.rg,
                               "--vnet-name", vnet_name, "--name", peer_name])
                self.check("Core peering "+peer_name, peer.get("peeringState") == "Connected" and peer.get("provisioningState") == "Succeeded", "bidirectional private routing")
            link = self.az("core-blob-dns-link", ["network", "private-dns", "link", "vnet", "show", "--resource-group", self.rg,
                           "--zone-name", "privatelink.blob.core.windows.net", "--name", "link-"+p["vnetName"]])
            self.check("Core Blob DNS link", link.get("virtualNetworkLinkState") == "Completed", "reuse original zone; do not replace its A record")
        if identity:
            roles = self.assignments("workspace-identity-roles", identity["principalId"])
            for role, scope in [("Microsoft Discovery Platform Contributor", self.rg_id), ("AcrPull", self.rg_id),
                                ("Storage Blob Data Contributor", storage["id"]),
                                ("Network Contributor", self.rg_id + "/providers/Microsoft.Network/virtualNetworks/" + p["vnetName"])]:
                self.check("Workspace UAMI " + role, has_role(roles, ROLES[role], scope), scope)
        target = self.az("target-workspace", ["rest", "--method", "get", "--url",
                         f"https://management.azure.com{self.rg_id}/providers/Microsoft.Discovery/workspaces/{p['workspaceName']}?api-version={self.config['apiVersion']}"],
                         scoped=False, optional=True, not_found_only=True)
        self.check("Workspace immutable-region consistency", target is None or (target["location"] == self.location and
                   target.get("tags", {}).get("discovery.overridemrgregion") == self.data_location), "never change region/tags of an existing workspace")
        source_name = self.config.get("sourceWorkspaceName")
        if source_name and source_name != p["workspaceName"]:
            source = self.az("source-workspace-link", ["rest", "--method", "get", "--url",
                             f"https://management.azure.com{self.rg_id}/providers/Microsoft.Discovery/workspaces/{source_name}?api-version={self.config['apiVersion']}"],
                             scoped=False, optional=True, not_found_only=True)
            sc_id = (self.rg_id + "/providers/Microsoft.Discovery/supercomputers/" + p["supercomputerName"]).lower()
            self.check("Retained compute ownership released", source is None or all(
                       x.lower() != sc_id for x in source.get("properties", {}).get("supercomputerIds", [])),
                       "old Failed workspace must not retain the exclusive association; use reviewed release_link, never delete compute")
        owners = self.rest("compute-owners", f"{self.rg_id}/providers/Microsoft.Discovery/workspaces?api-version={self.config['apiVersion']}")
        if not isinstance(owners.get("value"), list) or owners.get("nextLink"):
            raise RuntimeError("Workspace ownership inventory is incomplete; resolve it before attaching retained compute.")
        sc_id = (self.rg_id+"/providers/Microsoft.Discovery/supercomputers/"+p["supercomputerName"]).lower()
        conflicting = []
        for obj in owners["value"]:
            name = obj.get("name", "")
            if not name or "/" in name:
                raise RuntimeError("Workspace ownership metadata has an invalid name.")
            full = self.rest("owner-"+name, f"{self.rg_id}/providers/Microsoft.Discovery/workspaces/{name}?api-version={self.config['apiVersion']}")
            links = full.get("properties", {}).get("supercomputerIds")
            if not isinstance(links, list) or not all(isinstance(value, str) for value in links):
                raise RuntimeError("Workspace compute ownership is unverified: " + name)
            if name.lower() != p["workspaceName"].lower() and sc_id in {value.lower() for value in links}:
                conflicting.append(name)
        self.check("No conflicting compute owner", not conflicting, ", ".join(conflicting) or "no other workspace in the customer RG owns the retained compute")

    def build(self):
        self.template = ROOT / "templates" / ("workspace-core.bicep" if self.core_only else "workspace.bicep")
        self.compiled_path = self.out / "template.json"
        self.az("bicep-build", ["bicep", "build", "--file", str(self.template), "--outfile", str(self.compiled_path)], scoped=False, output_json=False)
        compiled = json.loads(self.compiled_path.read_text())
        assert_workspace_template(compiled, self.core_only)
        self.filtered_path = self.out / "parameters.json"
        write_json(self.filtered_path, filter_parameters(self.parameters, compiled))
        write_json(self.out / "workspace-source-manifest.json", {"scriptHash": digest(__file__), "allowedWriteIds": sorted(workspace_write_ids(self.values, self.rg_id, self.core_only))})

    def inspect_preview(self, result):
        return inspect_workspace_preview(result, self.values, self.rg_id, self.core_only, self.args.allow_modify)

    def audit(self):
        self.verify()
        p = self.values
        workspace = json.loads((self.out / "resource-2.json").read_text())
        model = json.loads((self.out / "resource-3.json").read_text())
        project = json.loads((self.out / "resource-5.json").read_text())
        sc_id = self.rg_id + "/providers/Microsoft.Discovery/supercomputers/" + p["supercomputerName"]
        storage_id = self.rg_id + "/providers/Microsoft.Discovery/storageContainers/" + p["storageContainerName"]
        self.check("Workspace compute relationship", {x.lower() for x in workspace["properties"].get("supercomputerIds", [])} == {sc_id.lower()}, "exact original Supercomputer")
        self.check("Project storage relationship", storage_id.lower() in {x.lower() for x in project["properties"].get("storageContainerIds", [])}, "original Discovery StorageContainer")
        self.check("Workspace managed-region override", workspace.get("tags", {}).get("discovery.overridemrgregion") == self.data_location, self.data_location)
        self.check("Chat model configuration", model["properties"].get("modelName") == p["chatModelName"] and
                   model["properties"].get("modelFormat") == "OpenAI", "gpt-5-4 resolves to OpenAI GPT-5.4")
        groups = self.az("resource-groups", ["group", "list"])
        mrg = resolve_managed_group(workspace, groups, self.scope)
        inventory = self.az("managed-inventory", ["resource", "list", "--resource-group", mrg.split("/")[-1]])
        required = {"microsoft.search/searchservices", "microsoft.cognitiveservices/accounts", "microsoft.documentdb/databaseaccounts"}
        found = set()
        backing = []
        for i, obj in enumerate(inventory):
            kind = obj["type"].lower()
            if kind not in required:
                continue
            found.add(kind)
            meta = self.az("backing-" + str(i), ["resource", "show", "--ids", obj["id"], "--query",
                           "{id:id,name:name,type:type,location:location,provisioningState:properties.provisioningState,status:properties.status,sku:sku}"])
            backing.append(meta)
            ready = (meta.get("provisioningState") or "").lower() == "succeeded"
            if kind == "microsoft.search/searchservices":
                ready = ready and (meta.get("status") or "").lower() == "running"
            self.check("Backing " + obj["name"], ready and meta["location"].replace(" ", "").lower() == self.data_location,
                       f"{meta.get('provisioningState')}; {meta['location']}")
        self.check("Required backing services", required.issubset(found), "Search, Cosmos DB and Foundry")
        pe = self.az("managed-private-endpoints", ["network", "private-endpoint", "list", "--resource-group", mrg.split("/")[-1]])
        approved = bool(pe) and all(x.get("provisioningState") == "Succeeded" and any(
            c.get("privateLinkServiceConnectionState", {}).get("status") == "Approved" for c in x.get("privateLinkServiceConnections", [])) for x in pe)
        self.check("Managed private endpoints", approved, str(len(pe)) + " endpoints; metadata approval only")
        for i, (vnet, name) in enumerate([(p["vnetName"], "peer-to-retained-discovery"),
                                         (p["existingVnetName"], "peer-to-" + p["vnetName"])]):
            peer = self.az("peering-" + str(i), ["network", "vnet", "peering", "show", "--resource-group", self.rg,
                           "--vnet-name", vnet, "--name", name])
            self.check("Peering " + name, peer.get("peeringState") == "Connected" and peer.get("provisioningState") == "Succeeded", "Connected / Succeeded")
        self.check_retained_resources()
        user, _ = self.principals()
        roles = self.assignments("managed-rg-user-roles", user, mrg)
        self.check("Foundry User on managed group", has_role(roles, ROLES["Foundry User"], mrg), "scoped or inherited")
        uri = workspace["properties"].get("workspaceApiUri", "").rstrip("/")
        if uri.lower() != "https://" + p["workspaceName"].lower() + ".workspace.discovery.azure.com":
            raise RuntimeError("Workspace API URI is not the expected HTTPS Discovery host; no authenticated request sent.")
        agents = self.az("project-agents-read", ["rest", "--method", "get", "--resource", "https://discovery.azure.com",
                         "--url", uri + "/projects/" + p["projectName"] + "/agents?api-version=" + self.config["apiVersion"]],
                         scoped=False, optional=True)
        reachable = isinstance(agents, (dict, list))
        self.check("Read-only authenticated project API", reachable, "GET agents only; no agent creation/inference", required=False)
        report = {"ok": not any(x["state"] == "FAIL" for x in self.checks), "checks": self.checks,
                  "managedResourceGroupId": mrg, "backing": backing, "workspaceApiUri": uri,
                  "workspaceUiUri": workspace["properties"].get("workspaceUiUri"),
                  "authenticatedProjectReadSucceeded": reachable, "paidInferenceTested": False}
        write_json(self.out / "audit.json", report)
        if not report["ok"]:
            raise RuntimeError("Workspace post-deployment audit has failures; inspect audit.json.")
        print("Workspace relationship/backing/network/RBAC audit passed. No inference performed.")

    def release_link(self):
        self.context()
        if not self.args.apply:
            raise RuntimeError("Releasing a Failed workspace association requires --apply.")
        source = self.config["sourceWorkspaceName"]
        if source.lower() == self.values["workspaceName"].lower():
            raise RuntimeError("Source and target workspaces must differ.")
        source_path = f"{self.rg_id}/providers/Microsoft.Discovery/workspaces/{source}?api-version={self.config['apiVersion']}"
        before = self.rest("source-workspace-before", source_path)
        sc_path = f"{self.rg_id}/providers/Microsoft.Discovery/supercomputers/{self.values['supercomputerName']}"
        sc = self.rest("supercomputer-before", sc_path + "?api-version=" + self.config["apiVersion"])
        if sc.get("properties", {}).get("provisioningState") != "Succeeded":
            raise RuntimeError("Retained Supercomputer is not Succeeded; do not change its workspace association.")
        method = self.args.release_method
        payload = (failed_workspace_detach_put_payload(before, sc_path) if method == "put"
                   else failed_workspace_detach_payload(before, sc_path))
        payload_path = self.out / "detach-payload.json"
        write_json(payload_path, payload)
        self.az("source-workspace-detach-" + method, ["rest", "--method", method, "--url",
                "https://management.azure.com" + source_path, "--body", "@" + str(payload_path)], scoped=False)
        deadline = time.monotonic() + 300
        while True:
            after = self.rest("source-workspace-readback", source_path)
            links = after.get("properties", {}).get("supercomputerIds", [])
            if not any(x.lower() == sc_path.lower() for x in links):
                for key in ["location", "tags"]:
                    if before.get(key) != after.get(key):
                        raise RuntimeError("Source workspace immutable field changed unexpectedly: " + key)
                for key in ["agentSubnetId", "privateEndpointSubnetId", "workspaceSubnetId"]:
                    if before["properties"].get(key) != after["properties"].get(key):
                        raise RuntimeError("Source workspace field changed unexpectedly: " + key)
                if before["properties"]["workspaceIdentity"]["id"].lower() != after["properties"]["workspaceIdentity"]["id"].lower():
                    raise RuntimeError("Source workspace identity changed unexpectedly.")
                check = self.rest("supercomputer-readback", sc_path + "?api-version=" + self.config["apiVersion"])
                if check["properties"].get("provisioningState") != "Succeeded":
                    raise RuntimeError("Retained compute state changed; inspect evidence before proceeding.")
                write_json(self.out / "link-release.json", {"sourceWorkspaceId": before["id"],
                           "supercomputerId": sc_path, "linkReleased": True, "computePreserved": True,
                           "remainingLinks": links, "sourceWorkspaceState": after["properties"].get("provisioningState")})
                print("Failed workspace compute association released; Supercomputer remains Succeeded.")
                return
            if time.monotonic() >= deadline:
                raise RuntimeError("Association release not confirmed; do not replay the PATCH blindly.")
            time.sleep(15)
