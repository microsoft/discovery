import argparse
import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deploy import Workflow
from inputs import full_inputs, save_bundle

SUB = "11111111-1111-4111-8111-111111111111"
TENANT = "22222222-2222-4222-8222-222222222222"


def workflow(directory, command="recommend", stage="full", apply=False):
    config, values = full_inputs(SUB, TENANT, "source-rg", "source", "eastus", "eastus2", "10.20.0.0/16")
    path = save_bundle(Path(directory)/"inputs", config, values)
    args = argparse.Namespace(config=str(path), evidence_dir=str(Path(directory)/"evidence"), command=command,
                              stage=stage, apply=apply, allow_modify=False, timeout=30, interval=15)
    return Workflow(args)


class Backend:
    """Synthetic ARM/CLI metadata; no credentials or Azure calls."""
    def __init__(self):
        self.calls = []
        self.source_compute = None
        self.source_workspace = None
        self.offered = {"eastus2": ["standard"], "centralus": ["standard"], "northcentralus": ["standard"]}
        self.model_free = 1000
        self.model_status = "Included"
        self.model_rate = 1000
        self.fail = False
        self.restricted = False
        self.compute_limit = 100
        self.locations = [
            {"name": "eastus2", "metadata": {"latitude": "0", "longitude": "0", "geographyGroup": "US"}},
            {"name": "centralus", "metadata": {"latitude": "0", "longitude": "1", "geographyGroup": "US"}},
            {"name": "northcentralus", "metadata": {"latitude": "0", "longitude": "2", "geographyGroup": "US"}},
            {"name": "japaneast", "metadata": {"latitude": "0", "longitude": "0.1", "geographyGroup": "APAC"}},
        ]
        self.owners = []

    def az(self, label, arguments, **kwargs):
        self.calls.append((label, arguments, kwargs))
        if self.fail:
            raise RuntimeError("AuthorizationFailed: synthetic denied read")
        if label == "subscription-locations":
            return {"value":copy.deepcopy(self.locations)}
        if label == "recommend-ownership-list":
            return {"value":[{"name":x["name"]} for x in self.owners]}
        if label.startswith("recommend-owner-"):
            name=label.removeprefix("recommend-owner-")
            owner=next(x for x in self.owners if x["name"]==name)
            return {"properties":{"provisioningState":owner["state"],"supercomputerIds":[owner["computeId"]]}}
        if label.endswith("source-compute"):
            return copy.deepcopy(self.source_compute)
        if label.endswith("source-workspace"):
            return copy.deepcopy(self.source_workspace)
        if label in ("recommend-retained-node", "recommend-retained-store"):
            return {"properties":{"provisioningState":"Succeeded"}}
        if label == "select-retained-vnet":
            return {"location": "eastus2", "addressSpace": {"addressPrefixes": ["10.20.0.0/16"]}}
        if label == "select-retained-blob-dns":
            return {"aRecords": [{"ipv4Address": "10.20.4.9"}]}
        if arguments[:1] == ["rest"]:
            url = arguments[arguments.index("--url")+1]
            if "fetchOfferings" in url:
                return {"regions": [{"regionName": name, "skus": [{"name": sku} for sku in skus]} for name, skus in self.offered.items()]}
            if "Microsoft.Search/locations/" in url:
                return {"value": [{"name": {"value": "standard"}, "limit": 12, "currentValue": 0}]}
        if arguments[:2] == ["quota", "list"]:
            return [{"name": "managedenvironmentcount", "properties": {"limit": {"value": 50}}}]
        if arguments[:3] == ["quota", "usage", "list"]:
            return [{"name": "managedenvironmentcount", "properties": {"usages": {"value": 0}}}]
        if arguments[:3] == ["cognitiveservices", "model", "list"]:
            return [{"kind": "OpenAI", "model": {"name": "gpt-5.4", "format": "OpenAI", "version": "test-version",
                "isDefaultVersion": True, "lifecycleStatus": "GenerallyAvailable", "skus": [{"name": "GlobalStandard",
                "usageName": "OpenAI.GlobalStandard.gpt-5.4", "rateLimits": [{"count": self.model_rate, "renewalPeriod": 60}]}]}}]
        if arguments[:3] == ["cognitiveservices", "usage", "list"]:
            return [{"name": {"value": "OpenAI.GlobalStandard.gpt-5.4"}, "status": self.model_status, "limit": 1000, "currentValue": 1000-self.model_free}]
        if arguments[:2] == ["vm", "list-skus"]:
            sku = arguments[arguments.index("--size")+1]
            family, cpu = ("standardESv5Family", 8) if sku == "Standard_E8s_v5" else ("standardDSv6Family", 4)
            return [{"name": sku, "family": family, "restrictions": [{"reasonCode": "NotAvailableForSubscription"}] if self.restricted else [],
                     "capabilities": [{"name": "vCPUs", "value": str(cpu)}]}]
        if arguments[:2] == ["vm", "list-usage"]:
            return [{"name": {"value": name}, "limit": self.compute_limit, "currentValue": 0} for name in ("cores", "standardDSv6Family", "standardESv5Family")]
        raise AssertionError("Unexpected synthetic query: " + label + " " + str(arguments))
