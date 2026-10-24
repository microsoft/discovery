#!/usr/bin/env python3
"""Opt-in Discovery regional recommendations and reviewed cross-region deployment."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

from capacity import RegionProbe, classify_failure, nearby_regions, read_query
from deploy import Workflow, digest, write_json
from inputs import full_inputs, save_bundle, workspace_inputs
from workspace import WorkspaceWorkflow


def discovery_get(runner, path, label):
    return read_query(runner, label, ["rest", "--method", "get", "--url",
        f"https://management.azure.com{runner.rg_id}/providers/Microsoft.Discovery/{path}?api-version={runner.config['apiVersion']}"],
        scoped=False, optional=True, not_found_only=True)


def compute_owners(runner):
    listing = discovery_get(runner, "workspaces", "recommend-ownership-list")
    if not listing or not isinstance(listing.get("value"), list) or listing.get("nextLink"):
        raise ValueError("Workspace ownership inventory is incomplete; do not propose compute reuse.")
    sc_id = (runner.rg_id+"/providers/Microsoft.Discovery/supercomputers/"+runner.values["supercomputerName"]).lower()
    owners = []
    for item in listing["value"]:
        name = item.get("name", "")
        if not re.fullmatch(r"[A-Za-z0-9-]{3,24}", name):
            raise ValueError("Workspace inventory contains an invalid name.")
        full = discovery_get(runner, "workspaces/"+name, "recommend-owner-"+name)
        links = full.get("properties", {}).get("supercomputerIds") if full else None
        if not isinstance(links, list) or not all(isinstance(x, str) for x in links):
            raise ValueError("A workspace's compute ownership is unverified.")
        if sc_id in {value.lower() for value in links}:
            owners.append({"name": name, "state": full.get("properties", {}).get("provisioningState")})
    if len(owners) > 1:
        raise ValueError("Compute ownership is ambiguous; resolve it without automatic deletion.")
    return owners


def recommendation(runner, args):
    supplied = json.loads(Path(args.failure_file).read_text()) if args.failure_file else None
    diagnosis = classify_failure(supplied) if supplied is not None else None
    report = {"time": datetime.now(timezone.utc).isoformat(), "sourceConfigHash": digest(runner.config_path),
              "sourceParametersHash": digest(runner.parameters_path), "codeHash": runner.code_hash(),
              "defaultRegion": runner.data_location, "candidates": [], "capacityReserved": False,
              "failureHash": digest(args.failure_file) if args.failure_file else None}
    if diagnosis is not None and not diagnosis["actionable"]:
        report["diagnosis"] = diagnosis
        return report
    if runner.config.get("deploymentMode") != "full":
        raise ValueError("Use the original full configuration for recommendations, not a previous workspace fallback.")
    runner.context()
    sc = discovery_get(runner, "supercomputers/"+runner.values["supercomputerName"], "recommend-source-compute")
    if sc and sc.get("properties", {}).get("provisioningState") not in ("Succeeded", "Failed", "Canceled"):
        raise ValueError("Source compute is in progress or unverified; wait for a terminal state before choosing a fallback.")
    source_ws = discovery_get(runner, "workspaces/"+runner.values["workspaceName"], "recommend-source-workspace")
    if source_ws and source_ws.get("properties", {}).get("provisioningState") != "Failed":
        report["diagnosis"] = {"actionable": False, "kind": "blocked", "codes": [],
                               "detail": "The source Workspace is healthy, in progress or unverified; this utility does not migrate it."}
        return report
    succeeded = bool(sc and sc.get("properties", {}).get("provisioningState") == "Succeeded")
    scope = args.scope if args.scope != "auto" else ("workspace" if succeeded else "fresh")
    if (scope == "workspace") != succeeded:
        raise ValueError("Reuse Succeeded compute with workspace scope; fresh scope is only for a source without Succeeded compute.")
    if succeeded:
        node = discovery_get(runner, "supercomputers/"+runner.values["supercomputerName"]+"/nodePools/"+runner.values["nodePoolName"], "recommend-retained-node")
        store = discovery_get(runner, "storageContainers/"+runner.values["storageContainerName"], "recommend-retained-store")
        if any(not value or value.get("properties", {}).get("provisioningState") != "Succeeded" for value in (node, store)):
            raise ValueError("Workspace reuse requires the node pool and StorageContainer to be Succeeded. Repair the retained unit or explicitly plan a separate new compute stack; moving only Workspace cannot fix compute quota.")
        codes = set((diagnosis or {}).get("codes", []))
        if codes & {"vmskuquota", "akscapacityheavyusage"} or (supplied and re.search(r"exceeding approved .+(cores|vcpu).+quota", json.dumps(supplied), re.I)):
            raise ValueError("The failure concerns retained compute, not the Workspace region. Request original-region quota or separately review a new compute stack.")
        owners = compute_owners(runner)
        report["computeOwners"] = owners
        if any(owner["state"] != "Failed" for owner in owners):
            report["diagnosis"] = {"actionable": False, "kind": "blocked", "codes": [],
                                   "detail": "Another healthy/in-progress workspace owns compute; refresh stale source inputs instead of relocating."}
            return report
    probe = RegionProbe(runner)
    primary = probe.probe(runner.data_location, scope == "fresh")
    report.update(scope=scope, primary=primary, sourceComputeSucceeded=succeeded)
    report["diagnosis"] = diagnosis or classify_failure(primary)
    if not report["diagnosis"]["actionable"]:
        return report
    location_response = read_query(runner, "subscription-locations", ["rest", "--method", "get", "--url",
        f"https://management.azure.com{runner.scope}/locations?api-version=2022-12-01"], scoped=False)
    if not isinstance(location_response.get("value"), list) or location_response.get("nextLink"):
        raise ValueError("Subscription-scoped location metadata is incomplete.")
    locations = location_response["value"]
    candidates = nearby_regions(locations, runner.data_location, args.candidates, args.allow_cross_geography)
    for candidate in candidates[:args.limit]:
        candidate.update(probe.probe(candidate["region"], scope == "fresh"))
        report["candidates"].append(candidate)
    report["allowCrossGeography"] = args.allow_cross_geography
    return report


def assert_recommendation(report, runner, region, mode, now=None):
    age = ((now or datetime.now(timezone.utc))-datetime.fromisoformat(report["time"])).total_seconds()
    if not 0 <= age <= 3600 or not report.get("diagnosis", {}).get("actionable"):
        raise ValueError("Recommendation must be recent and have a verified quota/capacity trigger.")
    for field, value in (("sourceConfigHash", digest(runner.config_path)),
                         ("sourceParametersHash", digest(runner.parameters_path)), ("codeHash", runner.code_hash())):
        if report.get(field) != value:
            raise ValueError("Recommendation inputs or utility code changed: " + field)
    if report.get("scope") != mode:
        raise ValueError("Selected mode differs from the diagnosed preservation boundary.")
    found = [x for x in report.get("candidates", []) if x.get("region") == region]
    if len(found) != 1 or found[0].get("eligibleForPreflight") is not True or not found[0].get("checks"):
        raise ValueError("Selected region lacks verified candidate evidence.")
    if any(check.get("status") != "PASS" for check in found[0]["checks"]):
        raise ValueError("Unknown or failed regional evidence cannot authorize a plan.")
    return found[0]


def select_inputs(runner, args):
    if not args.accept_cross_region:
        raise ValueError("Review residency, cost and private connectivity, then explicitly use --accept-cross-region.")
    report = json.loads(Path(args.recommendation).read_text())
    selected = assert_recommendation(report, runner, args.region, args.mode)
    runner.context()
    sc = discovery_get(runner, "supercomputers/"+runner.values["supercomputerName"], "select-source-compute")
    if sc and sc.get("properties", {}).get("provisioningState") not in ("Succeeded", "Failed", "Canceled"):
        raise ValueError("Source compute is now in progress; do not create an overlapping fallback stack.")
    sc_ready = bool(sc and sc.get("properties", {}).get("provisioningState") == "Succeeded")
    if args.mode == "fresh":
        if sc_ready:
            raise ValueError("Compute is now Succeeded; preserve it with a fresh workspace-scope recommendation.")
        if not args.target_resource_group or args.target_resource_group.lower() == runner.rg.lower():
            raise ValueError("Fresh fallback requires an explicitly named different target RG; the source group is preserved.")
        source_ws = discovery_get(runner, "workspaces/"+runner.values["workspaceName"], "select-source-workspace")
        if source_ws and source_ws.get("properties", {}).get("provisioningState") != "Failed":
            raise ValueError("Source Workspace is now healthy/in progress; refresh the recovery boundary.")
        config, values = full_inputs(runner.sub, runner.config["tenantId"], args.target_resource_group,
                                    args.name_prefix, runner.location, args.region, args.vnet_cidr)
        if values["workspaceName"].lower() == runner.values["workspaceName"].lower() or values["supercomputerName"].lower() == runner.values["supercomputerName"].lower():
            raise ValueError("A fresh fallback must use new compute/workspace names; choose a different prefix.")
        for key in ("systemSku", "nodePoolVmSize", "nodePoolMaxNodeCount", "nodePoolMinNodeCount", "nodePoolScaleSetPriority",
                    "storageAccountSku", "blobContainerName", "networkIsolation", "enableExtensions", "enableGhcpAiFeatures"):
            if key in runner.values:
                values[key] = runner.values[key]
    else:
        if not sc_ready:
            raise ValueError("Retained compute is no longer Succeeded; do not generate a reuse plan.")
        if args.target_resource_group and args.target_resource_group.lower() != runner.rg.lower():
            raise ValueError("Workspace reuse is currently limited to the same subscription and customer RG.")
        source_name = args.source_workspace or runner.values["workspaceName"]
        if not re.fullmatch(r"[A-Za-z0-9-]{3,24}", source_name):
            raise ValueError("Invalid source workspace name.")
        owners = compute_owners(runner)
        if owners and (owners[0]["state"] != "Failed" or owners[0]["name"].lower() != source_name.lower()):
            raise ValueError("The exact Failed compute owner must match --source-workspace; do not detach another or healthy workspace.")
        source = discovery_get(runner, "workspaces/"+source_name, "select-source-workspace")
        if source and source.get("properties", {}).get("provisioningState") != "Failed":
            raise ValueError("Source workspace is not confirmed Failed; healthy or in-progress workspaces must not be migrated.")
        vnet = read_query(runner, "select-retained-vnet", ["network", "vnet", "show", "--resource-group", runner.rg, "--name", runner.values["vnetName"]])
        if vnet["location"] != runner.data_location or sc.get("tags", {}).get("discovery.overridemrgregion") != runner.data_location:
            raise ValueError("Source compute/VNet region differs from the original configuration; refresh the inventory.")
        dns = read_query(runner, "select-retained-blob-dns", ["network", "private-dns", "record-set", "a", "show", "--resource-group", runner.rg,
                         "--zone-name", "privatelink.blob.core.windows.net", "--name", runner.values["storageAccountName"]])
        ips = {item["ipv4Address"] for item in dns.get("aRecords", [])}
        if len(ips) != 1:
            raise ValueError("This baseline requires one retained Blob A record; use a reviewed design for multi-IP/custom DNS.")
        config, values = workspace_inputs(runner.config, runner.values, args.name_prefix, args.region, args.vnet_cidr, ips.pop())
        config["sourceWorkspaceName"] = source_name
    config["regionalSelection"] = {"defaultRegion": runner.data_location, "selectedRegion": args.region,
        "recommendationHash": digest(args.recommendation), "crossRegionApproved": True,
        "distanceKm": selected["distanceKm"], "geographyGroup": selected["geographyGroup"],
        "capacityReserved": False}
    return save_bundle(args.output_dir, config, values)


def parser():
    top = argparse.ArgumentParser(description=__doc__)
    commands = top.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Generate local source inputs only; no Azure calls.")
    for flag in ("subscription", "tenant", "resource-group", "name-prefix", "workload-region", "output-dir"):
        init.add_argument("--"+flag, required=True)
    init.add_argument("--control-plane-region", default="eastus", choices=("eastus", "uksouth", "swedencentral"))
    init.add_argument("--vnet-cidr", default="10.20.0.0/16")
    recommend = commands.add_parser("recommend", help="Read-only quota/capacity checks and geographic recommendations.")
    recommend.add_argument("--scope", choices=("auto", "fresh", "workspace"), default="auto")
    recommend.add_argument("--failure-file", help="Optional fresh structured ARM failure; access/policy errors block fallback.")
    recommend.add_argument("--candidates", nargs="+", help="Optional operator-approved candidate allowlist; otherwise use same-geography locations.")
    recommend.add_argument("--allow-cross-geography", action="store_true")
    recommend.add_argument("--limit", type=int, default=3)
    recommend.add_argument("--report", required=True)
    select = commands.add_parser("select", help="Generate reviewed target inputs; no Azure writes.")
    select.add_argument("--recommendation", required=True)
    select.add_argument("--mode", choices=("fresh", "workspace"), required=True)
    select.add_argument("--region", required=True)
    select.add_argument("--name-prefix", required=True)
    select.add_argument("--target-resource-group")
    select.add_argument("--source-workspace")
    select.add_argument("--vnet-cidr", default="10.60.0.0/16")
    select.add_argument("--accept-cross-region", action="store_true")
    select.add_argument("--output-dir", required=True)
    for name in ("prepare", "preflight", "validate", "deploy", "status", "wait", "verify", "audit", "postconfigure", "release-link"):
        command = commands.add_parser(name)
        command.add_argument("--stage", choices=("full", "discovery", "workspace", "workspace-core"))
        command.add_argument("--apply", action="store_true")
        command.add_argument("--allow-modify", action="store_true")
        command.add_argument("--release-method", choices=("patch", "put"), default="put")
        command.add_argument("--timeout", type=int, default=7200)
        command.add_argument("--interval", type=int, default=60)
    for name, command in commands.choices.items():
        if name != "init":
            command.add_argument("--config", required=True)
            command.add_argument("--evidence-dir")
    return top


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    try:
        if args.command == "init":
            config, values = full_inputs(args.subscription, args.tenant, args.resource_group, args.name_prefix,
                                        args.control_plane_region, args.workload_region, args.vnet_cidr)
            print(save_bundle(args.output_dir, config, values))
            return 0
        config = json.loads(Path(args.config).read_text())
        workspace = config.get("deploymentMode") == "workspace"
        default_stage = "workspace-core" if workspace else "discovery"
        args.stage = getattr(args, "stage", None) or ("full" if args.command in ("recommend", "select") else default_stage)
        if workspace != args.stage.startswith("workspace"):
            raise ValueError("Stage does not match deploymentMode; do not mix full and workspace-only templates.")
        runner = (WorkspaceWorkflow if workspace else Workflow)(args)
        if args.command == "recommend":
            if not 1 <= args.limit <= 8:
                raise ValueError("Probe limit must be between 1 and 8 regions.")
            report = recommendation(runner, args)
            path = Path(args.report)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with path.open("x") as stream:
                json.dump(report, stream, indent=2)
                stream.write("\n")
            for row in report["candidates"]:
                print(row["region"], row["distanceKm"], "km", "eligible for preflight" if row["eligibleForPreflight"] else "NOT VERIFIED")
            print("No capacity reserved or Azure writes performed. Report:", path)
            return 0 if any(x["eligibleForPreflight"] for x in report["candidates"]) else 2
        if args.command == "select":
            print("Created target inputs:", select_inputs(runner, args))
            return 0
        if args.timeout < 1 or args.interval < 15:
            raise ValueError("Use a positive timeout and polling interval of at least 15 seconds.")
        if args.command == "release-link" and not workspace:
            raise ValueError("Association release requires an explicit workspace-reuse configuration.")
        getattr(runner, args.command.replace("-", "_"))()
        print("Evidence:", runner.out)
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        print("ERROR:", error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
