#!/usr/bin/env python3
"""Generate new Discovery inputs locally, without login, Azure calls or overwrites."""

import argparse
import ipaddress
import json
from pathlib import Path
import re
import sys
import uuid

from deploy import ROOT, write_json


CONTROL_REGIONS = ("eastus", "uksouth", "swedencentral")


def region(value):
    if not re.fullmatch(r"[a-z][a-z0-9]+", value):
        raise ValueError("Use a lowercase Azure region short name, for example centralus.")
    return value


def prefixes(cidr):
    net = ipaddress.ip_network(cidr, strict=True)
    private_ranges = tuple(ipaddress.ip_network(x) for x in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
    if net.version != 4 or net.prefixlen != 16 or not any(net.subnet_of(x) for x in private_ranges):
        raise ValueError("This baseline requires a private IPv4 /16 VNet CIDR.")
    blocks = list(net.subnets(new_prefix=24))
    return {
        "vnetAddressPrefix": str(net),
        "supercomputerNodepoolSubnetPrefix": str(blocks[1]),
        "aksSubnetPrefix": str(blocks[2]),
        "workspaceSubnetPrefix": str(blocks[3]),
        "privateEndpointSubnetPrefix": str(blocks[4]),
        "agentSubnetPrefix": str(blocks[5]),
        "searchSubnetPrefix": str(blocks[6]),
        "managementSubnetPrefix": str(next(blocks[7].subnets(new_prefix=28))),
    }


def validate_prefix(value):
    if not re.fullmatch(r"[a-z][a-z0-9]{2,11}", value):
        raise ValueError("name-prefix must be 3-12 lowercase alphanumeric characters, starting with a letter.")
    return value


def portable(path):
    path = Path(path).resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def base_config(sub, tenant, group, control, workload, name):
    uuid.UUID(sub)
    uuid.UUID(tenant)
    if not re.fullmatch(r"[A-Za-z0-9_.()-]{1,90}", group) or group.endswith("."):
        raise ValueError("Use a 1-90 character Azure resource group name, without a trailing period.")
    if control not in CONTROL_REGIONS:
        raise ValueError("Select a documented Discovery control-plane region.")
    return {
        "subscriptionId": sub, "tenantId": tenant, "resourceGroup": group,
        "location": control, "dataPlaneLocation": region(workload),
        "deploymentMode": "full",
        "apiVersion": "2026-06-01", "deploymentName": name,
        "privateStorageRequired": True,
    }


def full_inputs(sub, tenant, group, name, control, workload, cidr):
    validate_prefix(name)
    cfg = base_config(sub, tenant, group, control, workload, "discovery-" + name)
    suffix = uuid.uuid5(uuid.NAMESPACE_URL, sub.lower() + "/" + group.lower() + "/" + name).hex[:8]
    values = {
        "location": control, "overridemrgregion": workload,
        "supercomputerName": name + "-sc", "workspaceName": name + "-ws",
        "nodePoolName": "nodepool1", "projectName": name[:8] + "-prj",
        "storageContainerName": name + "-outputs", "blobContainerName": "discoveryoutputs",
        "vnetName": "vnet-" + name, "managedIdentityName": "id-" + name,
        "natGatewayName": "nat-" + name, "natGatewayPublicIpName": "pip-" + name,
        "storageAccountName": "st" + name + suffix, "storageAccountSku": "Standard_GRS",
        "nodePoolVmSize": "Standard_D4s_v6", "nodePoolMinNodeCount": 0,
        "systemSku": "Standard_D4s_v6",
        "nodePoolMaxNodeCount": 3, "nodePoolScaleSetPriority": "Regular",
        "chatModelDeploymentName": "gpt-5-4", "chatModelFormat": "OpenAI",
        "chatModelName": "gpt-5.4", "enableGhcpAiFeatures": True,
        "enableExtensions": True, "networkIsolation": True,
        **prefixes(cidr),
    }
    return cfg, values


def workspace_inputs(source, values, name, workload, cidr, private_ip):
    validate_prefix(name)
    region(workload)
    if source["location"] not in CONTROL_REGIONS:
        raise ValueError("Use a documented Discovery control-plane region.")
    if source.get("deploymentMode") == "workspace":
        raise ValueError("Use a full-environment source config, not an earlier workspace-recovery config.")
    if values["location"] != source["location"] or values["overridemrgregion"] != source["dataPlaneLocation"]:
        raise ValueError("Source config and parameter regions differ.")
    network = prefixes(cidr)
    old_network = ipaddress.ip_network(values.get("vnetAddressPrefix", "10.0.0.0/16"))
    new_network = ipaddress.ip_network(cidr)
    if old_network.overlaps(new_network):
        raise ValueError("New workspace VNet must not overlap the retained VNet.")
    address = ipaddress.ip_address(private_ip)
    endpoint_net = ipaddress.ip_network(values.get("privateEndpointSubnetPrefix", "10.0.4.0/24"))
    if address not in endpoint_net:
        raise ValueError("Retained Blob private IP must be in the source private-endpoint subnet; read its actual DNS record first.")
    if workload == source["dataPlaneLocation"]:
        raise ValueError("Choose a different workspace workload region for a regional fallback.")
    cfg = base_config(source["subscriptionId"], source["tenantId"], source["resourceGroup"],
                      source["location"], workload, "discovery-" + name + "-workspace")
    cfg.update({"supercomputerDataPlaneLocation": source["dataPlaneLocation"],
                "storageDataPlaneLocation": source["dataPlaneLocation"],
                "deploymentMode": "workspace",
                "sourceWorkspaceName": values["workspaceName"], "retainedBlobPrivateIp": str(address)})
    output = {key: values[key] for key in ("supercomputerName", "nodePoolName", "storageContainerName",
                                          "storageAccountName", "chatModelDeploymentName", "chatModelName", "projectName")}
    output.update({"location": source["location"], "overridemrgregion": workload,
                   "existingVnetName": values["vnetName"], "workspaceName": name + "-ws",
                   "vnetName": "vnet-" + name, "managedIdentityName": "id-" + name,
                   "natGatewayName": "nat-" + name, "natGatewayPublicIpName": "pip-" + name,
                   **{k: network[k] for k in ("vnetAddressPrefix", "workspaceSubnetPrefix", "privateEndpointSubnetPrefix", "agentSubnetPrefix")}})
    for key in ("workspaceName", "vnetName", "managedIdentityName", "natGatewayName", "natGatewayPublicIpName"):
        if output[key].lower() == str(values.get(key, "")).lower():
            raise ValueError("Fallback names must be different from retained names: " + key)
    scope = f"/subscriptions/{cfg['subscriptionId']}/resourceGroups/{cfg['resourceGroup']}"
    vnet = scope + "/providers/Microsoft.Network/virtualNetworks/" + output["vnetName"]
    storage = scope + "/providers/Microsoft.Storage/storageAccounts/" + output["storageAccountName"]
    for key, target in (("platformRoleAssignmentName", scope), ("acrPullRoleAssignmentName", scope),
                        ("blobRoleAssignmentName", storage), ("networkRoleAssignmentName", vnet)):
        output[key] = str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join((target.lower(), output["managedIdentityName"], key))))
    return cfg, output


def save_bundle(directory, config, values):
    directory = Path(directory).resolve()
    # A new directory is mandatory: never overwrite current or historical inputs.
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    config = dict(config, parametersFile="parameters.json")
    write_json(directory / "deployment.config.json", config)
    write_json(directory / "parameters.json", {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0", "parameters": {k: {"value": v} for k, v in values.items()},
    })
    return directory / "deployment.config.json"
