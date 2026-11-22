#!/usr/bin/env python3
"""Auditable Azure CLI workflow for the Microsoft Discovery Bicep quickstart."""

import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parent
CONTROL_PLANE_APP = "92c174ac-8e41-4815-a1b7-d81b19ab03ce"
REQUIRED_PROVIDERS = (
    "Discovery Network Compute Storage ManagedIdentity AlertsManagement Authorization "
    "CognitiveServices ContainerInstance ContainerRegistry ContainerService DocumentDB "
    "Features KeyVault MachineLearningServices NetApp OperationalInsights ResourceGraph "
    "Search Web Insights Resources Sql App Bing"
).split()
DISCOVERY_TYPES = (
    "supercomputers", "supercomputers/nodepools", "workspaces",
    "workspaces/chatmodeldeployments", "storagecontainers", "workspaces/projects",
)
ROLES = {
    "Owner": "8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
    "Reader": "acdd72a7-3385-48ef-bd42-f606fba81ae7",
    "Foundry User": "53ca6127-db72-4b80-b1b0-d745d6d5456d",
    "Microsoft Discovery Platform Administrator": "7a2b6e6c-472e-4b39-8878-a26eb63d75c6",
    "Managed Identity Contributor": "e40ec5ca-96e0-45a2-b4ff-59039f2c2b59",
    "Managed Identity Operator": "f1a07417-d97a-45cb-824c-7a7467783830",
    "Storage Account Contributor": "17d1049b-9a84-46fb-8f53-869881c3d3ab",
    "Storage Blob Data Contributor": "ba92f5b4-2d11-453d-a403-e96b0029c9fe",
    "Network Contributor": "4d97b98b-1d4f-4787-a291-c67834d212e7",
    "AcrPush": "8311e382-0749-4cb8-b61a-304f252e45ec",
    "AcrPull": "7f951dda-4ed3-4680-a7ca-43fe172d538d",
    "Microsoft Discovery Platform Contributor": "01288891-85ee-45a7-b367-9db3b752fc65",
    "Microsoft Discovery Bookshelf Index Data Reader": "8ec773c5-7ce6-4b78-91d1-182f8faa536d",
}
PERSONA_ROLES = tuple(n for n in ROLES if n not in (
    "Owner", "Reader", "Foundry User", "AcrPull", "Microsoft Discovery Platform Contributor",
))
NSP_ACTIONS = {
    "Microsoft.Network/networkSecurityPerimeters/joinPerimeterRule/action",
    "Microsoft.Network/locations/networkSecurityPerimeterOperationStatuses/read",
}


def is_minimal_nsp_role(definition):
    permissions = definition.get("permissions", [])
    return len(permissions) == 1 and set(permissions[0].get("actions", [])) == NSP_ACTIONS and not any(
        permissions[0].get(key) for key in ("notActions", "dataActions", "notDataActions"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assert_fresh_preflight(report, config_hash, parameters_hash, now=None):
    now = now or datetime.now(timezone.utc)
    age = (now - datetime.fromisoformat(report["time"])).total_seconds()
    if report.get("ok") is not True or not 0 <= age <= 3600 or report.get("configHash") != config_hash or report.get("parametersHash") != parameters_hash:
        raise RuntimeError("Run a fresh successful preflight for this configuration first; a later failed preflight invalidates an older validation receipt.")


def scope_covers(parent, child):
    if not parent or not child:
        return False
    if parent == "/":
        return child.startswith("/")
    parent, child = parent.lower().rstrip("/"), child.lower().rstrip("/")
    return child == parent or child.startswith(parent + "/")


def has_role(assignments, role_id, target):
    return any(
        a.get("roleDefinitionId", "").split("/")[-1].lower() == role_id.lower()
        and scope_covers(a.get("scope", ""), target)
        and not a.get("condition")
        for a in assignments
    )


def is_not_found_error(message):
    return bool(re.search(r"\b(ResourceGroupNotFound|DeploymentNotFound|ResourceNotFound)\b", message))


def resolve_managed_group(resource, groups, subscription_scope):
    props = resource.get("properties", {})
    explicit = props.get("managedResourceGroupId") or props.get("managedResourceGroup") or props.get("managedResourceGroupName")
    if isinstance(explicit, dict):
        explicit = explicit.get("id")
    candidates = []
    if explicit:
        candidates.append(explicit if explicit.startswith("/") else subscription_scope + "/resourceGroups/" + explicit)
    resource_id = resource.get("id", "").lower().rstrip("/")
    if resource_id:
        candidates += [g["id"] for g in groups
                       if (g.get("managedBy") or "").lower().rstrip("/") == resource_id]
    unique = {candidate.lower(): candidate for candidate in candidates}
    if len(unique) != 1:
        raise RuntimeError("Managed resource group missing or ambiguous; inspect resource/group evidence, do not guess its name.")
    group_id = next(iter(unique.values()))
    pattern = re.escape(subscription_scope) + r"/resourceGroups/[^/]+"
    if not re.fullmatch(pattern, group_id, flags=re.IGNORECASE):
        raise RuntimeError("Managed resource group is outside the approved subscription or is not a group ID.")
    return group_id


def filter_parameters(source, compiled):
    declared = compiled.get("parameters", {})
    return {
        "$schema": source.get("$schema"),
        "contentVersion": "1.0.0.0",
        "parameters": {k: v for k, v in source["parameters"].items() if k in declared},
    }


def search_dedicated_skus(offerings, location):
    regions = offerings.get("regions")
    if not isinstance(regions, list):
        raise RuntimeError("Search offerings response has no regions list; availability is unknown.")
    normalize = lambda value: re.sub(r"[^a-z0-9]", "", value.lower())
    matches = [r for r in regions if normalize(r.get("regionName", "")) == normalize(location)]
    if len(matches) != 1 or not isinstance(matches[0].get("skus"), list):
        raise RuntimeError("Search offerings region missing or ambiguous; availability is unknown.")
    names = set()
    for item in matches[0]["skus"]:
        name = item.get("name") or item.get("sku", {}).get("name")
        if not isinstance(name, str):
            raise RuntimeError("Search offering has no SKU name; availability is unknown.")
        if name.lower() not in ("free", "serverless"):
            names.add(name.lower())
    return names


def project_agents_url(workspace, workspace_name, project_name, api_version):
    uri = workspace.get("properties", {}).get("workspaceApiUri", "").rstrip("/")
    if uri.lower() != "https://" + workspace_name.lower() + ".workspace.discovery.azure.com":
        raise RuntimeError("Unexpected workspace API host; no authenticated request sent.")
    if not re.fullmatch(r"[a-zA-Z0-9-]{3,24}", project_name):
        raise RuntimeError("Unexpected project name; no authenticated request sent.")
    return uri + "/projects/" + project_name + "/agents?api-version=" + api_version


def assert_resume_template(compiled):
    expected = {"microsoft.discovery/" + name for name in DISCOVERY_TYPES}
    actual = [r.get("type", "").lower() for r in compiled.get("resources", [])]
    if len(actual) != len(expected) or set(actual) != expected:
        raise RuntimeError("Resume template must contain exactly the six approved Discovery types and no foundation writes.")


def inspect_changes(result, discovery_only, allow_modify=False):
    if result.get("status") != "Succeeded" or result.get("error"):
        raise RuntimeError("What-if did not succeed; inspect the saved response.")
    counts = {}
    for change in result.get("changes", []):
        kind = change["changeType"]
        if kind not in ("Create", "Modify", "Delete", "Ignore", "NoChange", "Deploy", "Unsupported"):
            raise RuntimeError("Unknown what-if change type; no deployment authorized: " + kind)
        counts[kind] = counts.get(kind, 0) + 1
        if kind in ("Delete", "Deploy", "Unsupported") or (kind == "Modify" and not allow_modify):
            raise RuntimeError(f"Unapproved what-if change: {kind} {change['resourceId']}")
        if discovery_only and kind in ("Create", "Modify"):
            if "/providers/microsoft.discovery/" not in change["resourceId"].lower():
                raise RuntimeError("Resume deployment would modify a non-Discovery resource.")
    return counts


class Workflow:
    def __init__(self, args):
        self.args = args
        self.config_path = Path(args.config).resolve()
        self.config = json.loads(self.config_path.read_text())
        self.sub = self.config["subscriptionId"]
        uuid.UUID(self.sub)
        uuid.UUID(self.config["tenantId"])
        if self.config.get("apiVersion") != "2026-06-01":
            raise ValueError("This utility's templates require Discovery API 2026-06-01.")
        self.rg = self.config["resourceGroup"]
        self.location = self.config["location"]
        self.data_location = self.config.get("dataPlaneLocation", self.location)
        self.scope = f"/subscriptions/{self.sub}"
        self.rg_id = self.scope + "/resourceGroups/" + self.rg
        self.parameters_path = self.config_path.parent / self.config["parametersFile"]
        self.state_root = self.config_path.parent / ".state"
        self.state_root.mkdir(exist_ok=True, mode=0o700)
        self.parameters = json.loads(self.parameters_path.read_text())
        self.values = {k: v["value"] for k, v in self.parameters["parameters"].items()}
        if not re.fullmatch(r"[A-Za-z0-9_.()-]{1,90}", self.rg) or self.rg.endswith("."):
            raise ValueError("Invalid resource group name.")
        for key in ("supercomputerName", "workspaceName", "storageContainerName", "projectName", "chatModelDeploymentName"):
            if not re.fullmatch(r"[A-Za-z0-9-]{3,24}", self.values[key]):
                raise ValueError("Invalid Discovery resource name: " + key)
        source_name = self.config.get("sourceWorkspaceName")
        if source_name and not re.fullmatch(r"[A-Za-z0-9-]{3,24}", source_name):
            raise ValueError("Invalid source workspace name.")
        if self.values.get("chatModelName") != "gpt-5.4" or self.values.get("chatModelFormat", "OpenAI") != "OpenAI":
            raise ValueError("This baseline budgets the required OpenAI GPT-5.4 service deployments only.")
        if self.values["location"] != self.location:
            raise RuntimeError("Configuration and Bicep parameter regions differ.")
        if self.values.get("overridemrgregion", self.location) != self.data_location:
            raise RuntimeError("Configuration and Bicep data-plane override regions differ.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.out = Path(args.evidence_dir).resolve() if args.evidence_dir else (
            self.config_path.parent / "evidence" / f"{args.command}-{stamp}"
        )
        self.out.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.ledger = []
        self.checks = []
        write_json(self.out / "source-manifest.json", {
            "scriptHash": digest(__file__), "configHash": digest(self.config_path),
            "parametersHash": digest(self.parameters_path),
            "templates": {str(p.relative_to(ROOT)): digest(p) for p in (ROOT / "templates").rglob("*.bicep")},
        })

    def az(self, label, arguments, *, scoped=True, optional=False, output_json=True, not_found_only=False):
        command = ["az", *arguments]
        if scoped:
            command += ["--subscription", self.sub]
        command += ["--only-show-errors"]
        if output_json:
            command += ["-o", "json"]
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {label}", flush=True)
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                                env=dict(os.environ, AZURE_EXTENSION_USE_DYNAMIC_INSTALL="no"))
        suffix = ".json" if output_json else ".stdout"
        (self.out / (label + suffix)).write_text(result.stdout)
        (self.out / (label + ".stderr")).write_text(result.stderr)
        self.ledger.append({"command": command, "exitCode": result.returncode,
                            "time": datetime.now(timezone.utc).isoformat()})
        write_json(self.out / "commands.json", self.ledger)
        if result.returncode:
            if optional:
                if not_found_only and not is_not_found_error(result.stderr):
                    raise RuntimeError(f"{label}: lookup failed, not a confirmed missing resource; no mutation permitted. {result.stderr[-3000:]}")
                return None
            raise RuntimeError(f"{label}: {result.stderr[-5000:]}")
        return json.loads(result.stdout) if output_json and result.stdout.strip() else result.stdout

    def rest(self, label, resource, optional=False):
        return self.az(label, ["rest", "--method", "get", "--url",
                              "https://management.azure.com" + resource],
                       scoped=False, optional=optional)

    def check(self, name, condition, detail, required=True):
        state = "PASS" if condition else ("FAIL" if required else "WARN")
        self.checks.append({"name": name, "state": state, "detail": detail})
        print(f"  {state}: {name}: {detail}", flush=True)

    def context(self):
        account = self.az("account", ["account", "show"])
        if account.get("environmentName") != "AzureCloud":
            raise RuntimeError("This utility supports Azure public cloud only; no preparation/deployment permitted.")
        if account["id"] != self.sub or account["tenantId"] != self.config["tenantId"]:
            raise RuntimeError("Azure subscription/tenant differs from the approved configuration.")
        default = self.az("default-account", ["account", "show"], scoped=False)
        if default["tenantId"] != self.config["tenantId"]:
            raise RuntimeError("Select the approved tenant before directory/REST operations.")
        return account

    def principals(self):
        user = self.az("signed-in-user", ["ad", "signed-in-user", "show"], scoped=False)
        cp = self.az("control-plane-principal", ["ad", "sp", "show", "--id", CONTROL_PLANE_APP], scoped=False)
        return user["id"], cp["id"]

    def assignments(self, label, principal, scope=None):
        args = ["role", "assignment", "list", "--assignee", principal]
        args += ["--scope", scope, "--include-inherited"] if scope else ["--all"]
        return self.az(label, args)

    def prepare(self):
        self.context()
        if not self.args.apply:
            raise RuntimeError("Provider/IAM preparation requires --apply.")
        providers = self.az("providers", ["provider", "list"])
        states = {x["namespace"].lower(): x["registrationState"] for x in providers}
        for name in REQUIRED_PROVIDERS:
            namespace = "Microsoft." + name
            if states.get(namespace.lower()) != "Registered":
                self.az("register-" + name.lower(), ["provider", "register", "--namespace", namespace, "--wait"])
        group = self.az("resource-group", ["group", "show", "--name", self.rg], optional=True, not_found_only=True)
        if group is None:
            self.az("create-resource-group", ["group", "create", "--name", self.rg, "--location", self.data_location])
        user, cp = self.principals()
        cp_roles = self.assignments("control-plane-roles", cp, self.scope)
        definitions = self.az("custom-role-definitions", ["role", "definition", "list", "--custom-role-only", "true", "--scope", self.scope])
        nsp = next((d for d in definitions if is_minimal_nsp_role(d)), None)
        if nsp is None:
            body = {"Name": "Discovery NSP Perimeter Joiner - " + self.sub[:8],
                    "Description": "Discovery control-plane NSP join permissions.",
                    "Actions": sorted(NSP_ACTIONS), "NotActions": [], "DataActions": [],
                    "NotDataActions": [], "AssignableScopes": [self.scope]}
            file = self.out / "nsp-role-definition.json"
            write_json(file, body)
            nsp = self.az("create-nsp-role", ["role", "definition", "create", "--role-definition", str(file)])
        self.assign(cp, "ServicePrincipal", nsp["name"], self.scope, cp_roles)
        self.assign(cp, "ServicePrincipal", ROLES["Reader"], self.scope, cp_roles)
        user_roles = self.assignments("user-roles", user, self.rg_id)
        for name in PERSONA_ROLES:
            self.assign(user, "User", ROLES[name], self.rg_id, user_roles)
        print("Providers and persona/NSP prerequisites prepared. Run preflight next.")

    def assign(self, principal, principal_type, role, scope, current):
        if has_role(current, role, scope):
            return
        name = str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join((scope.lower(), principal.lower(), role.lower()))))
        self.az("assign-" + name, ["role", "assignment", "create", "--name", name,
                "--assignee-object-id", principal, "--assignee-principal-type", principal_type,
                "--role", role, "--scope", scope])

    def quota(self, provider):
        scope = f"{self.scope}/providers/{provider}/locations/{self.data_location}"
        limits = self.az(provider + "-quota", ["quota", "list", "--scope", scope])
        usages = self.az(provider + "-usage", ["quota", "usage", "list", "--scope", scope])
        used = {x["name"].lower(): x.get("properties", {}).get("usages", {}).get("value") for x in usages}
        return {x["name"].lower(): (x.get("properties", {}).get("limit", {}).get("value"),
                                  used.get(x["name"].lower())) for x in limits}

    def preflight(self):
        self.begin_preflight()
        self.context()
        self.check("Documented production region", self.location in ("eastus", "uksouth", "swedencentral"),
                   "creation support is stricter than the provider catalog; data-plane override=" + self.data_location)
        provider = self.az("discovery-provider", ["provider", "show", "--namespace", "Microsoft.Discovery"])
        types = {x["resourceType"].lower(): x for x in provider["resourceTypes"]}
        for name in DISCOVERY_TYPES:
            info = types.get(name, {})
            locations = ["".join(c for c in s.lower() if c.isalnum()) for s in info.get("locations", [])]
            self.check("Discovery " + name, self.location in locations and self.config["apiVersion"] in info.get("apiVersions", []),
                       "region/API advertised by the subscription-scoped catalog")
        read = self.rest("supercomputer-read", f"{self.scope}/providers/Microsoft.Discovery/supercomputers?api-version={self.config['apiVersion']}", optional=True)
        self.check("Authenticated Discovery read", isinstance(read, dict) and "value" in read, "real ARM GET, not only template validation")
        feature = self.az("default-feature", ["feature", "show", "--namespace", "Microsoft.Discovery", "--name", "DefaultFeature"], optional=True)
        self.check("DefaultFeature informational", bool(feature and feature.get("properties", {}).get("state") == "Registered"),
                   "not an access gate when core resource types and authenticated reads are available", required=False)
        providers = self.az("providers", ["provider", "list"])
        states = {x["namespace"].lower(): x["registrationState"] for x in providers}
        missing = ["Microsoft." + n for n in REQUIRED_PROVIDERS if states.get("microsoft." + n.lower()) != "Registered"]
        self.check("Required providers", not missing, "missing: " + ", ".join(missing) if missing else "all registered")
        user, cp = self.principals()
        user_roles = self.assignments("user-roles", user, self.rg_id)
        for name in PERSONA_ROLES:
            self.check("User " + name, has_role(user_roles, ROLES[name], self.rg_id), "resource group or inherited scope")
        cp_roles = self.assignments("control-plane-roles", cp, self.scope)
        self.check("Control-plane Reader", has_role(cp_roles, ROLES["Reader"], self.scope), "subscription scope")
        definitions = self.az("custom-role-definitions", ["role", "definition", "list", "--custom-role-only", "true", "--scope", self.scope])
        self.check("Control-plane NSP", any(has_role(cp_roles, d["name"], self.scope) and is_minimal_nsp_role(d)
                   for d in definitions), "minimal NSP role assigned at subscription scope without conditions")
        inventory = self.az("foundation-inventory", ["resource", "list", "--resource-group", self.rg])
        existing = {(x["type"].lower(), x["name"].lower()) for x in inventory}
        wanted = {("microsoft.managedidentity/userassignedidentities", self.values["managedIdentityName"].lower()),
                  ("microsoft.network/virtualnetworks", self.values["vnetName"].lower()),
                  ("microsoft.storage/storageaccounts", self.values["storageAccountName"].lower())}
        present = len(wanted & existing)
        if self.args.stage == "full" and present == 0:
            self.check("New foundation", True, "all three foundation resources will be created by the full template; verify after deployment")
        elif present != 3:
            self.check("Foundation completeness", False, "partial/missing foundation; do not resume Discovery against missing dependencies")
        else:
            self.check_foundation()
        self.check_capacity(include_compute=True)
        report = {"ok": not any(c["state"] == "FAIL" for c in self.checks), "checks": self.checks,
                  "time": datetime.now(timezone.utc).isoformat(), "configHash": digest(self.config_path),
                  "parametersHash": digest(self.parameters_path), "codeHash": self.code_hash(), "evidence": str(self.out)}
        write_json(self.out / "preflight.json", report)
        write_json(self.state_root / "latest-preflight.json", report)
        if not report["ok"]:
            raise RuntimeError("Preflight failed; see preflight.json. No deployment submitted.")

    def begin_preflight(self):
        write_json(self.state_root / "latest-preflight.json", {
            "ok": False, "time": datetime.now(timezone.utc).isoformat(),
            "configHash": digest(self.config_path), "parametersHash": digest(self.parameters_path),
            "codeHash": self.code_hash(), "reason": "Preflight started; prior evidence invalidated.",
        })

    def code_hash(self):
        paths = sorted(list(ROOT.glob("*.py")) + list((ROOT / "templates").rglob("*.bicep")))
        return hashlib.sha256("\n".join(str(p.relative_to(ROOT))+":"+digest(p) for p in paths).encode()).hexdigest()

    def check_capacity(self, include_compute):
        from capacity import RegionProbe, remaining_model_tpm, read_query
        base = f"https://management.azure.com{self.rg_id}/providers/Microsoft.Discovery/"
        def state(path, label):
            obj = read_query(self, label, ["rest", "--method", "get", "--url", base+path+"?api-version="+self.config["apiVersion"]],
                             scoped=False, optional=True, not_found_only=True)
            return obj.get("properties", {}).get("provisioningState") if obj else None
        workspace = "workspaces/"+self.values["workspaceName"]
        ws_state = state(workspace, "capacity-workspace")
        chat_state = state(workspace+"/chatModelDeployments/"+self.values["chatModelDeploymentName"], "capacity-chat") if ws_state is not None else None
        needed = remaining_model_tpm(ws_state, chat_state)
        if include_compute:
            sc = "supercomputers/"+self.values["supercomputerName"]
            include_compute = state(sc, "capacity-compute") != "Succeeded" or state(sc+"/nodePools/"+self.values["nodePoolName"], "capacity-nodepool") != "Succeeded"
        result = RegionProbe(self).probe(self.data_location, include_compute, needed, ws_state != "Succeeded")
        for check in result["checks"]:
            self.check(check["name"], check["status"] == "PASS", check["detail"])
            self.checks[-1].update(kind=check["kind"], data=check["data"], status=check["status"])
        write_json(self.out / "regional-capacity.json", result)

    def check_foundation(self):
        identity = self.az("identity", ["identity", "show", "--name", self.values["managedIdentityName"], "--resource-group", self.rg])
        roles = self.assignments("identity-roles", identity["principalId"])
        vnet = self.az("vnet", ["network", "vnet", "show", "--name", self.values["vnetName"], "--resource-group", self.rg])
        storage = self.az("storage", ["storage", "account", "show", "--name", self.values["storageAccountName"], "--resource-group", self.rg])
        for obj in [identity, vnet, storage]:
            self.check(obj["name"] + " region", obj["location"] == self.data_location, obj["location"])
        for name, scope in [("Microsoft Discovery Platform Contributor", self.rg_id), ("AcrPull", self.rg_id),
                            ("Storage Blob Data Contributor", storage["id"]), ("Network Contributor", vnet["id"])]:
            self.check("UAMI " + name, has_role(roles, ROLES[name], scope), scope)
        subnets = {s["name"]: s for s in vnet["subnets"]}
        expected = ["aksSubnet", "sc-mgmt", "supercomputerNodepoolSubnet", "workspaceSubnet", "agentSubnet", "searchSubnet", "privateEndpointSubnet"]
        for name in expected:
            self.check("Subnet " + name, name in subnets, "existing subnet; never overwrite governance NSGs")
        for name in ["workspaceSubnet", "agentSubnet", "searchSubnet", "sc-mgmt"]:
            target = "Microsoft.ContainerService/managedClusters" if name == "sc-mgmt" else "Microsoft.App/environments"
            self.check("Delegation " + name, any(d.get("serviceName") == target for d in subnets.get(name, {}).get("delegations", [])), target)
        self.check("Private Blob governance", storage.get("publicNetworkAccess") == "Disabled", "public access remains disabled", self.config.get("privateStorageRequired", True))
        pe_name = "pe-" + self.values["storageAccountName"] + "-blob"
        pe = self.az("blob-private-endpoint", ["network", "private-endpoint", "show", "--name", pe_name, "--resource-group", self.rg], optional=True)
        self.check("Blob Private Endpoint", bool(pe and pe.get("provisioningState") == "Succeeded" and any(
            c.get("privateLinkServiceConnectionState", {}).get("status") == "Approved" for c in pe.get("privateLinkServiceConnections", [])
        )), "Succeeded and Approved; data-plane reachability is a separate check")
        for name in ["aksSubnet", "supercomputerNodepoolSubnet", "workspaceSubnet", "agentSubnet"]:
            endpoints = subnets.get(name, {}).get("serviceEndpoints", [])
            self.check("Storage service endpoint " + name, any(
                e.get("service") in ("Microsoft.Storage", "Microsoft.Storage.Global") for e in endpoints
            ), "required by the quickstart")
        blob = self.rest("blob-service", storage["id"] + "/blobServices/default?api-version=2023-05-01")
        needed = {"https://studio.discovery.microsoft.com", "https://vscode.dev", "https://*.vscode-cdn.net"}
        cors = blob.get("properties", {}).get("cors", {}).get("corsRules", [])
        origins = {o for rule in cors if {"GET", "HEAD", "PUT", "DELETE"}.issubset(set(rule.get("allowedMethods", [])))
                   for o in rule.get("allowedOrigins", [])}
        self.check("Blob CORS", needed.issubset(origins), "Studio and VS Code origins/methods")
        container = self.values.get("blobContainerName", "discoveryoutputs")
        result = self.rest("blob-container", storage["id"] + f"/blobServices/default/containers/{container}?api-version=2023-05-01", optional=True)
        self.check("Output blob container", bool(result), "ARM metadata read, not a data-plane test")
        zone = "privatelink.blob.core.windows.net"
        dns = self.az("blob-dns", ["network", "private-dns", "record-set", "a", "show", "--name",
                      self.values["storageAccountName"], "--zone-name", zone, "--resource-group", self.rg], optional=True)
        link = self.az("blob-dns-link", ["network", "private-dns", "link", "vnet", "show", "--name",
                       "link-" + self.values["vnetName"], "--zone-name", zone, "--resource-group", self.rg], optional=True)
        prefix = subnets.get("privateEndpointSubnet", {}).get("addressPrefix")
        records = dns.get("aRecords", []) if dns else []
        valid_ips = bool(prefix and records) and all(
            ipaddress.ip_address(a["ipv4Address"]) in ipaddress.ip_network(prefix) for a in records
        )
        self.check("Blob private DNS", valid_ips and bool(link and link.get("virtualNetworkLinkState") == "Completed"),
                   "private address in the endpoint subnet and completed VNet link")

    def build(self):
        self.template = ROOT / "templates" / ("discovery.bicep" if self.args.stage == "discovery" else "main.bicep")
        self.compiled_path = self.out / "template.json"
        self.az("bicep-build", ["bicep", "build", "--file", str(self.template), "--outfile", str(self.compiled_path)], scoped=False, output_json=False)
        compiled = json.loads(self.compiled_path.read_text())
        if self.args.stage == "discovery":
            assert_resume_template(compiled)
        self.filtered_path = self.out / "parameters.json"
        write_json(self.filtered_path, filter_parameters(self.parameters, compiled))

    def deployment_args(self):
        return ["--resource-group", self.rg, "--name", self.config["deploymentName"],
                "--template-file", str(self.compiled_path), "--parameters", "@" + str(self.filtered_path),
                "--mode", "Incremental", "--validation-level", "Provider"]

    def validate(self):
        write_json(self.state_root / "validated-deployment.json", {"valid": False, "reason": "Validation started; previous receipt invalidated."})
        report = json.loads((self.state_root / "latest-preflight.json").read_text())
        assert_fresh_preflight(report, digest(self.config_path), digest(self.parameters_path))
        if report.get("codeHash") != self.code_hash():
            raise RuntimeError("Utility code changed after preflight; rerun it.")
        self.build()
        self.az("arm-validation", ["deployment", "group", "validate", *self.deployment_args(), "--no-prompt", "true"])
        result = self.az("what-if", ["deployment", "group", "what-if", *self.deployment_args(), "--no-pretty-print"])
        counts = self.inspect_preview(result)
        receipt = {"valid": True, "time": datetime.now(timezone.utc).isoformat(), "configHash": digest(self.config_path),
                   "template": str(self.template), "templateHash": digest(self.template),
                   "parametersHash": digest(self.parameters_path), "compiled": str(self.compiled_path),
                   "compiledHash": digest(self.compiled_path), "filteredParameters": str(self.filtered_path),
                   "filteredParametersHash": digest(self.filtered_path), "stage": self.args.stage,
                   "counts": counts, "codeHash": self.code_hash(), "evidence": str(self.out)}
        write_json(self.state_root / "validated-deployment.json", receipt)
        print("Validated what-if:", counts)

    def inspect_preview(self, result):
        return inspect_changes(result, self.args.stage == "discovery", self.args.allow_modify)

    def deploy(self):
        self.context()
        if not self.args.apply:
            raise RuntimeError("Actual deployment requires --apply after reviewing what-if.")
        report = json.loads((self.state_root / "latest-preflight.json").read_text())
        assert_fresh_preflight(report, digest(self.config_path), digest(self.parameters_path))
        receipt = json.loads((self.state_root / "validated-deployment.json").read_text())
        if receipt.get("valid") is not True:
            raise RuntimeError("Run a fresh successful validation; previous receipt is invalid.")
        if receipt.get("codeHash") != self.code_hash() or report.get("codeHash") != self.code_hash():
            raise RuntimeError("Utility code changed; run fresh preflight and validation.")
        for field, path in [("configHash", self.config_path), ("parametersHash", self.parameters_path),
                            ("templateHash", receipt["template"]), ("compiledHash", receipt["compiled"]),
                            ("filteredParametersHash", receipt["filteredParameters"])]:
            if receipt[field] != digest(path):
                raise RuntimeError("Validated input changed: " + field)
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(receipt["time"])).total_seconds()
        if not 0 <= age <= 3600 or receipt["stage"] != self.args.stage:
            raise RuntimeError("Validation receipt is stale or belongs to another stage.")
        existing = self.az("existing-deployment", ["deployment", "group", "show", "--resource-group", self.rg,
                          "--name", self.config["deploymentName"]], optional=True, not_found_only=True)
        if existing and existing.get("properties", {}).get("provisioningState") in ("Running", "Accepted"):
            raise RuntimeError("This deployment is already running. Use status/wait; do not resubmit.")
        self.compiled_path = Path(receipt["compiled"])
        self.filtered_path = Path(receipt["filteredParameters"])
        self.az("deployment-submit", ["deployment", "group", "create", *self.deployment_args(), "--no-prompt", "true", "--no-wait"])
        self.status()

    def status(self):
        d = self.az("deployment-status", ["deployment", "group", "show", "--resource-group", self.rg, "--name", self.config["deploymentName"]])
        operations = self.az("deployment-operations", ["deployment", "operation", "group", "list", "--resource-group", self.rg, "--name", self.config["deploymentName"]])
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        write_json(self.out / ("status-" + stamp + ".json"), {"deployment": d, "operations": operations})
        print("Deployment:", d["properties"]["provisioningState"], "correlation:", d["properties"].get("correlationId"))
        for op in operations:
            p = op.get("properties") or {}
            target = p.get("targetResource") or {}
            print(" ", p.get("provisioningState"), target.get("resourceType"), target.get("resourceName"))
            if p.get("provisioningState") == "Failed":
                print(json.dumps(p.get("statusMessage"), indent=2))
        return d["properties"]["provisioningState"]

    def wait(self):
        deadline = time.monotonic() + self.args.timeout
        while True:
            state = self.status()
            if state == "Succeeded":
                return
            if state in ("Failed", "Canceled"):
                raise RuntimeError("Deployment reached terminal state " + state + "; no automatic replay.")
            if time.monotonic() >= deadline:
                raise RuntimeError("Wait timed out; cloud deployment was not canceled. Use status/wait to continue.")
            time.sleep(self.args.interval)

    def resource_paths(self):
        p = self.values
        sc = "supercomputers/" + p["supercomputerName"]
        ws = "workspaces/" + p["workspaceName"]
        return [sc, sc + "/nodePools/" + p["nodePoolName"], ws,
                ws + "/chatModelDeployments/" + p["chatModelDeploymentName"],
                "storageContainers/" + p["storageContainerName"], ws + "/projects/" + p["projectName"]]

    def verify(self):
        self.context()
        results = []
        for i, path in enumerate(self.resource_paths()):
            obj = self.rest("resource-" + str(i), f"{self.rg_id}/providers/Microsoft.Discovery/{path}?api-version={self.config['apiVersion']}", optional=True)
            state = obj.get("properties", {}).get("provisioningState") if obj else None
            results.append({"path": path, "state": state, "id": obj.get("id") if obj else None})
            self.check(path, state == "Succeeded", str(state))
        write_json(self.out / "verification.json", {"resources": results, "paidInferenceTested": False})
        if any(r["state"] != "Succeeded" for r in results):
            raise RuntimeError("Not all six Discovery resources are Succeeded.")
        print("Resource verification passed. No paid inference was run. Check managed-RG roles and Studio access next.")

    def postconfigure(self):
        self.context()
        if not self.args.apply:
            raise RuntimeError("Foundry User assignment requires --apply.")
        user, _ = self.principals()
        path = f"{self.rg_id}/providers/Microsoft.Discovery/workspaces/{self.values['workspaceName']}?api-version={self.config['apiVersion']}"
        workspace = self.rest("workspace", path)
        if workspace.get("properties", {}).get("provisioningState") != "Succeeded":
            raise RuntimeError("Workspace is not Succeeded; wait for provisioning before postconfiguration.")
        groups = self.az("resource-groups", ["group", "list"])
        mrg = resolve_managed_group(workspace, groups, self.scope)
        current = self.assignments("managed-rg-user-roles", user, mrg)
        self.assign(user, "User", ROLES["Foundry User"], mrg, current)
        confirmed = self.assignments("managed-rg-user-roles-readback", user, mrg)
        if not has_role(confirmed, ROLES["Foundry User"], mrg):
            raise RuntimeError("Foundry User not visible on readback; inspect propagation before retrying any assignment.")
        write_json(self.out / "postconfiguration.json", {"workspaceId": workspace["id"],
                   "managedResourceGroupId": mrg, "foundryUserVerified": True,
                   "inheritedRoleReused": has_role(current, ROLES["Foundry User"], mrg)})
        print("Foundry User verified on the workspace managed resource group:", mrg)

    def audit(self):
        self.verify()
        self.check_foundation()
        p = self.values
        workspace = json.loads((self.out / "resource-2.json").read_text())
        model = json.loads((self.out / "resource-3.json").read_text())
        project = json.loads((self.out / "resource-5.json").read_text())
        compute = json.loads((self.out / "resource-0.json").read_text())
        store = json.loads((self.out / "resource-4.json").read_text())
        sc_id = self.rg_id + "/providers/Microsoft.Discovery/supercomputers/" + p["supercomputerName"]
        store_id = self.rg_id + "/providers/Microsoft.Discovery/storageContainers/" + p["storageContainerName"]
        self.check("Workspace compute relationship", {x.lower() for x in workspace["properties"].get("supercomputerIds", [])} == {sc_id.lower()}, "expected Supercomputer ID")
        self.check("Project storage relationship", store_id.lower() in {x.lower() for x in project["properties"].get("storageContainerIds", [])}, "expected Discovery StorageContainer ID")
        account_id = self.rg_id + "/providers/Microsoft.Storage/storageAccounts/" + p["storageAccountName"]
        self.check("Project backing storage", store["properties"].get("storageStore", {}).get("storageAccountId", "").lower() == account_id.lower(), "expected customer storage account")
        self.check("Supercomputer managed region", compute.get("tags", {}).get("discovery.overridemrgregion") == self.data_location, self.data_location)
        self.check("Workspace managed region", workspace.get("tags", {}).get("discovery.overridemrgregion") == self.data_location, self.data_location)
        self.check("Chat model configuration", model["properties"].get("modelName") == p["chatModelName"] and
                   model["properties"].get("modelFormat") == p["chatModelFormat"], p["chatModelName"])
        groups = self.az("resource-groups", ["group", "list"])
        mrg = resolve_managed_group(workspace, groups, self.scope)
        inventory = self.az("managed-inventory", ["resource", "list", "--resource-group", mrg.split("/")[-1]])
        required = {"microsoft.search/searchservices", "microsoft.cognitiveservices/accounts", "microsoft.documentdb/databaseaccounts"}
        found, backing = set(), []
        for index, item in enumerate(inventory):
            kind = item["type"].lower()
            if kind not in required:
                continue
            found.add(kind)
            meta = self.az("backing-" + str(index), ["resource", "show", "--ids", item["id"], "--query",
                           "{id:id,name:name,type:type,location:location,provisioningState:properties.provisioningState,status:properties.status}"])
            backing.append(meta)
            ready = (meta.get("provisioningState") or "").lower() == "succeeded"
            if kind == "microsoft.search/searchservices":
                ready = ready and (meta.get("status") or "").lower() == "running"
            self.check("Backing " + item["name"], ready and meta["location"].replace(" ", "").lower() == self.data_location,
                       str(meta.get("provisioningState")) + "; " + meta["location"])
        self.check("Required backing services", required.issubset(found), "Search, Foundry and Cosmos DB")
        endpoints = self.az("managed-private-endpoints", ["network", "private-endpoint", "list", "--resource-group", mrg.split("/")[-1]])
        self.check("Managed private endpoints", bool(endpoints) and all(x.get("provisioningState") == "Succeeded" and any(
                   c.get("privateLinkServiceConnectionState", {}).get("status") == "Approved" for c in x.get("privateLinkServiceConnections", [])) for x in endpoints),
                   str(len(endpoints)) + " endpoints; configuration evidence, not packet reachability")
        user, _ = self.principals()
        roles = self.assignments("managed-rg-user-roles", user, mrg)
        self.check("Foundry User on managed group", has_role(roles, ROLES["Foundry User"], mrg), "scoped or inherited")
        url = project_agents_url(workspace, p["workspaceName"], p["projectName"], self.config["apiVersion"])
        agents = self.az("project-agents-read", ["rest", "--method", "get", "--resource", "https://discovery.azure.com", "--url", url],
                         scoped=False, optional=True)
        reachable = isinstance(agents, (dict, list))
        self.check("Read-only authenticated project API", reachable, "GET agents only; use a privately connected runner when required", required=False)
        report = {"ok": not any(c["state"] == "FAIL" for c in self.checks), "checks": self.checks,
                  "managedResourceGroupId": mrg, "backing": backing, "workspaceApiUri": workspace["properties"]["workspaceApiUri"],
                  "authenticatedProjectReadSucceeded": reachable, "paidInferenceTested": False}
        write_json(self.out / "audit.json", report)
        if not report["ok"]:
            raise RuntimeError("Post-deployment audit failed; inspect audit.json before use.")
