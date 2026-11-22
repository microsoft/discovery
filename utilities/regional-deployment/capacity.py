"""Read-only regional evidence; quota, offerings and physical capacity are distinct."""

from datetime import datetime, timezone
import json
import math
import re
from urllib.parse import urlsplit

from deploy import search_dedicated_skus


READ_PREFIXES = (
    ("account", "show"), ("provider", "show"),
    ("vm", "list-skus"), ("vm", "list-usage"), ("quota", "list"), ("quota", "usage", "list"),
    ("cognitiveservices", "model", "list"), ("cognitiveservices", "usage", "list"),
    ("network", "vnet", "show"), ("network", "private-dns", "record-set", "a", "show"),
    ("storage", "account", "show"),
    ("group", "show"),
)
QUOTA_CODES = {"insufficientquota", "quotaexceeded", "vmskuquota"}
CAPACITY_CODES = {"insufficientresourcesavailable", "akscapacityheavyusage", "allocationfailed", "zonalallocationfailed"}
BLOCKING_CODES = {
    "authorizationfailed", "authenticationfailed", "invalidauthenticationtoken", "forbidden",
    "requestdisallowedbypolicy", "invalidresourcetype", "noregisteredproviderfound",
    "missingsubscriptionregistration", "regionmismatch", "resourcenotfound", "resourcegroupnotfound",
    "linkedauthorizationfailed", "denyassignmentauthorizationfailed", "subscriptiondisabled", "scopelocked",
}


def read_query(runner, label, arguments, **kwargs):
    args = tuple(arguments)
    if args and args[0] == "rest":
        if args.count("--url") != 1 or args.count("--method") != 1:
            raise RuntimeError("Read-only REST requires one explicit method and URL.")
        uri = urlsplit(args[args.index("--url") + 1])
        method = args[args.index("--method") + 1].lower()
        if uri.scheme != "https" or uri.netloc.lower() != "management.azure.com":
            raise RuntimeError("Read-only evidence is restricted to the public Azure ARM host.")
        offerings = uri.path.lower() == "/providers/microsoft.search/fetchofferings"
        if method != "get" and not (method == "post" and offerings):
            raise RuntimeError("Regional recommendations cannot mutate Azure resources.")
    elif not any(args[:len(prefix)] == prefix for prefix in READ_PREFIXES):
        raise RuntimeError("Azure command is not in the regional read-only allowlist.")
    return runner.az(label, list(args), **kwargs)


def classify_failure(payload):
    codes, causes = set(), set()

    def visit(value):
        if isinstance(value, dict):
            code = str(value.get("code", "")).lower()
            if code:
                codes.add(code)
            if code == "operationnotallowed" and re.search(r"exceeding approved .+ quota|insufficient .+ quota", str(value.get("message", "")), re.I):
                causes.add("quota")
            # Native/readiness quota evidence must contain an actual numeric deficit.
            if (value.get("kind") == "quota" or value.get("id") in ("model-quota", "vcpu-quota")) and str(value.get("status", "")).upper() == "FAIL":
                data = value.get("data") or {}
                if finite_number(data.get("available")) and finite_number(data.get("required")) and data["available"] < data["required"]:
                    causes.add("quota")
            if value.get("kind") == "capacity" and value.get("status") == "FAIL":
                data = value.get("data") or {}
                if isinstance(data.get("offeredSkus"), list) and data.get("requiredSku") == "standard" and "standard" not in data["offeredSkus"]:
                    causes.add("capacity")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str) and value.startswith(("{", "[")):
            try:
                decoded = json.loads(value)
            except ValueError:
                return
            if isinstance(decoded, (dict, list)):
                visit(decoded)
    visit(payload)
    if codes & BLOCKING_CODES:
        return {"actionable": False, "kind": "blocked", "codes": sorted(codes),
                "detail": "Resolve access, policy, resource/API or topology errors; do not relocate to bypass them."}
    if codes & QUOTA_CODES:
        causes.add("quota")
    if codes & CAPACITY_CODES:
        causes.add("capacity")
    return {"actionable": bool(causes), "kind": "+".join(sorted(causes)) or "unverified", "codes": sorted(codes),
            "detail": "Quota is an allocation limit; capacity is physical availability. Neither is a reservation."}


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def short_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9]+", value):
        raise ValueError("Use canonical lowercase Azure region short names.")
    return value


def location_metadata(locations, name):
    matches = [item for item in locations if item.get("name") == name]
    if len(matches) != 1:
        raise ValueError("Region is missing or ambiguous in subscription location metadata: " + name)
    meta = matches[0].get("metadata") or {}
    try:
        lat, lon = float(meta["latitude"]), float(meta["longitude"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Missing region coordinates; proximity is unverified: " + name) from error
    if not -90 <= lat <= 90 or not -180 <= lon <= 180 or not meta.get("geographyGroup"):
        raise ValueError("Invalid coordinates/geography; proximity is unverified: " + name)
    return lat, lon, meta["geographyGroup"]


def nearby_regions(locations, origin, candidates=None, allow_cross_geography=False):
    lat, lon, geography = location_metadata(locations, short_name(origin))
    selected = candidates if candidates is not None else [x.get("name") for x in locations if x.get("name") != origin]
    result = []
    for name in dict.fromkeys(selected):
        short_name(name)
        if name == origin:
            continue
        try:
            other_lat, other_lon, other_geography = location_metadata(locations, name)
        except ValueError:
            if candidates is not None:
                raise
            continue
        if other_geography != geography and not allow_cross_geography:
            continue
        a, b = math.radians(lat), math.radians(other_lat)
        haversine = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(other_lon-lon)/2)**2
        distance = 6371 * 2 * math.asin(math.sqrt(min(1, max(0, haversine))))
        result.append({"region": name, "distanceKm": round(distance, 1), "geographyGroup": other_geography,
                       "crossGeography": other_geography != geography})
    return sorted(result, key=lambda row: (row["distanceKm"], row["region"]))


def quota_name(row):
    name = row.get("name", "")
    return str(name.get("value", "") if isinstance(name, dict) else name).lower()


def unique_row(rows, name):
    found = [row for row in rows if quota_name(row) == name.lower()]
    if len(found) != 1:
        raise ValueError("Quota row missing or ambiguous: " + name)
    return found[0]


def quota_values(row):
    limit, used = row.get("limit"), row.get("currentValue")
    def native_number(value):
        if isinstance(value, str) and re.fullmatch(r"\d+(?:\.\d+)?", value):
            return float(value)
        return value
    limit, used = native_number(limit), native_number(used)
    if not all(finite_number(value) for value in (limit, used)) or not 0 <= used <= limit:
        raise ValueError("Quota values are unknown, malformed or inconsistent.")
    return limit, used


def model_quota_units(catalog, name):
    matches = []
    for row in catalog:
        model = row.get("model") or {}
        if row.get("kind") not in ("OpenAI", "AIServices") or model.get("name") != name or model.get("format") != "OpenAI":
            continue
        if model.get("lifecycleStatus") != "GenerallyAvailable":
            continue
        for sku in model.get("skus", []):
            if sku.get("name") != "GlobalStandard" or sku.get("usageName") != "OpenAI.GlobalStandard." + name:
                continue
            for rate in sku.get("rateLimits", []):
                labels = " ".join(str(rate.get(key) or "") for key in ("key", "name", "metric", "type", "unit")).strip().lower()
                if labels and "token" not in labels:
                    continue
                try:
                    renewal, count = float(rate["renewalPeriod"]), float(rate["count"])
                except (KeyError, TypeError, ValueError):
                    continue
                if renewal == 60 and count == 1000:
                    matches.append(sku["usageName"])
    if not matches:
        raise ValueError("No compatible GA AIServices/OpenAI GlobalStandard offering with verified 1K TPM quota units.")
    return matches[0]


def remaining_model_tpm(workspace_state, chat_state, workspace_tpm=250000, chat_tpm=200000):
    return (0 if workspace_state == "Succeeded" else workspace_tpm) + (0 if chat_state == "Succeeded" else chat_tpm)


class RegionProbe:
    def __init__(self, runner):
        self.runner = runner
        self.offerings = None
        self.skus = {}

    def query(self, label, args, **kwargs):
        return read_query(self.runner, label, args, **kwargs)

    def probe(self, region, include_compute=True, required_model_tpm=450000, new_workspace=True):
        short_name(region)
        checks = []

        def add(name, condition, detail, kind="offering", data=None):
            checks.append({"name": name, "status": "PASS" if condition else "FAIL", "kind": kind,
                           "detail": detail, "data": data or {}})

        def check_quota(name, row, required, factor=1):
            limit, used = quota_values(row)
            available = (limit-used)*factor
            add(name, available >= required, f"limit={limit}; used={used}; required={required}; units factor={factor}",
                "quota", {"available": available, "required": required, "limit": limit, "used": used})

        try:
            if new_workspace:
                if self.offerings is None:
                    self.offerings = self.query("search-offerings", ["rest", "--method", "post", "--url",
                        "https://management.azure.com/providers/Microsoft.Search/fetchOfferings?api-version=2026-09-01-preview"], scoped=False)
                offered = search_dedicated_skus(self.offerings, region)
                add("Search Standard offering", "standard" in offered, ", ".join(sorted(offered)) or "No dedicated offering", "capacity",
                    {"offeredSkus": sorted(offered), "requiredSku": "standard"})
                usage = self.query(region+"-search-usage", ["rest", "--method", "get", "--url",
                    f"https://management.azure.com{self.runner.scope}/providers/Microsoft.Search/locations/{region}/usages?api-version=2025-05-01"], scoped=False)
                check_quota("Search Standard service count", unique_row(usage.get("value", []), "standard"), 1)
                scope = f"{self.runner.scope}/providers/Microsoft.App/locations/{region}"
                limits = self.query(region+"-aca-quota", ["quota", "list", "--scope", scope])
                usages = self.query(region+"-aca-usage", ["quota", "usage", "list", "--scope", scope])
                limit = unique_row(limits, "managedenvironmentcount")["properties"]["limit"]["value"]
                used = unique_row(usages, "managedenvironmentcount")["properties"]["usages"]["value"]
                check_quota("Container Apps environments", {"limit": limit, "currentValue": used}, 4)
            if required_model_tpm:
                catalog = self.query(region+"-model-catalog", ["cognitiveservices", "model", "list", "--location", region])
                usage_name = model_quota_units(catalog, self.runner.values["chatModelName"])
                usage = self.query(region+"-model-usage", ["cognitiveservices", "usage", "list", "--location", region])
                row = unique_row(usage, usage_name)
                quota_status = row.get("status") or row.get("quotaStatus")
                if quota_status not in (None, "Included"):
                    raise ValueError("Model quota allocation status is not verified as usable: " + str(quota_status))
                check_quota("Model TPM", row, required_model_tpm, 1000)
            if include_compute:
                needs = {}
                for sku_name, count in ((self.runner.values.get("systemSku", "Standard_D4s_v6"), 3), (self.runner.values["nodePoolVmSize"], self.runner.values["nodePoolMaxNodeCount"])):
                    if not re.fullmatch(r"Standard_[A-Za-z0-9_]+", sku_name) or not isinstance(count, int) or isinstance(count, bool) or count < 0:
                        raise ValueError("Invalid VM SKU or node-count input.")
                    key = (region, sku_name)
                    if key not in self.skus:
                        self.skus[key] = self.query(region+"-sku-"+sku_name, ["vm", "list-skus", "--location", region,
                            "--resource-type", "virtualMachines", "--size", sku_name, "--all"])
                    skus = self.skus[key]
                    matches = [sku for sku in skus if sku.get("name") == sku_name]
                    if len(matches) != 1:
                        raise ValueError("Required VM SKU is missing/ambiguous: " + sku_name)
                    sku = matches[0]
                    add("VM SKU "+sku_name, not sku.get("restrictions"), "Subscription restrictions: "+str(sku.get("restrictions", [])))
                    cpu = [x.get("value") for x in sku.get("capabilities", []) if x.get("name") == "vCPUs"]
                    if len(cpu) != 1 or not str(cpu[0]).isdigit() or int(cpu[0]) < 1 or not sku.get("family"):
                        raise ValueError("VM family/vCPU metadata is unverified.")
                    family = sku["family"].lower()
                    needs[family] = needs.get(family, 0) + int(cpu[0])*count
                usage = self.query(region+"-compute-usage", ["vm", "list-usage", "--location", region])
                for family, needed in dict(needs, cores=sum(needs.values())).items():
                    check_quota("Compute "+family, unique_row(usage, family), needed)
        except (RuntimeError, ValueError, KeyError, TypeError) as error:
            checks.append({"name": "Regional evidence", "status": "UNKNOWN", "kind": "unverified", "detail": str(error), "data": {}})
        return {"region": region, "eligibleForPreflight": bool(checks) and all(x["status"] == "PASS" for x in checks),
                "time": datetime.now(timezone.utc).isoformat(), "checks": checks,
                "capacityReserved": False, "policyAndNetworkApprovalRequired": True}
