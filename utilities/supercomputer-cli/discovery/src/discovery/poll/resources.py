"""Resource lookup helpers separated from CLI.

Encapsulates Azure CLI based discovery for workspaces, projects, and
workspace -> resource id mapping so the CLI file stays focused on
interaction / flow control.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING

from discovery.common.logging import debug, error  # lightweight import (no cycle)

from .azcli import run_az


if TYPE_CHECKING:  # pragma: no cover
    from .models.config import EnvConfig

__all__ = [
    "check_blob_container_permissions",
    "derive_workspace_id_from_project_id",
    "extract_resource_group",
    "extract_vnet_id",
    "fetch_workspace_url_from_resource_id",
    "get_all_nodepool_details",
    "get_blob_uri_from_datacontainer",
    "get_datacontainer_datastore",
    "get_datacontainer_storage_details",
    "get_nodepool_details",
    "get_resource_group_and_location",
    "get_storagecontainer_storage_details",
    "get_storagecontainer_storagestore",
    "get_workspace_ids",
    "is_nodepool_of_supercomputer",
    "list_all_nodepools_with_details",
    "list_anf_volumes",
    "list_containers_with_kind",
    "list_datacontainers",
    "list_resources",
    "list_storage_accounts",
    "list_storagecontainers",
    "list_storages",
    "resolve_supercomputer_region",
    "resolve_supercomputer_vnet",
]


def extract_resource_group(resource_id: str) -> str:
    """Extract resource group name from an Azure resource ID.

    Args:
        resource_id: Full Azure resource ID

    Returns:
        Resource group name or empty string if not found
    """
    parts = resource_id.split("/")
    for i, part in enumerate(parts):
        if part.lower() == "resourcegroups" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def is_nodepool_of_supercomputer(nodepool_id: str, supercomputer_id: str) -> bool:
    """Check if a nodepool belongs to a supercomputer.

    Uses case-insensitive comparison since Azure resource IDs can have
    different casing between API responses.

    Args:
        nodepool_id: Full Azure resource ID of the nodepool
        supercomputer_id: Full Azure resource ID of the supercomputer

    Returns:
        True if the nodepool belongs to the supercomputer
    """
    # Normalize: ensure supercomputer_id ends with / for proper prefix matching
    # This prevents matching /supercomputers/foo with /supercomputers/foobar
    sc_prefix = supercomputer_id.rstrip("/").lower() + "/"
    np_lower = nodepool_id.lower()
    return np_lower.startswith(sc_prefix) or np_lower == supercomputer_id.lower()


def list_resources(
    resource_type: str, properties: Iterable[str] = ("id",), assert_present: bool = True
) -> list[str]:
    """List all resources matching type. Return properties (default id)."""
    cmd = [
        "az",
        "resource",
        "list",
        "--resource-type",
        resource_type,
        "-o",
        "json",
    ]
    debug(f"List Resources: executing {' '.join(cmd)}")
    res = run_az(cmd)
    if res.returncode != 0:
        error(
            f"List Resources: az returned non-zero exit code={res.returncode} "
            f"stderr={res.stderr.strip()[:300]}"
        )
        msg = "Failed to list resources"
        raise RuntimeError(msg)
    data = json.loads(res.stdout)
    if len(data) == 0 and assert_present:
        error("list_resources(): no resources found")
        msg = "No resources found"
        raise RuntimeError(msg)
    debug(f"list_resources(): returned {len(data)} resource objects")
    result = []
    for d in data:
        result.append("\t".join(d[p] for p in properties))
    return result


def get_workspace_ids(workspace_resource_id: str, property_name: str) -> list[str]:
    res = run_az(
        [
            "az",
            "resource",
            "show",
            "--ids",
            workspace_resource_id,
            "-o",
            "json",
        ],
    )
    if res.returncode != 0:
        msg = f"az CLI failed with exit code {res.returncode} while fetching workspace resource"
        raise RuntimeError(msg)
    try:
        data = json.loads(res.stdout)
    except Exception as exc:  # pragma: no cover - malformed JSON
        msg = "Failed to parse JSON"
        raise ValueError(msg) from exc
    props = data.get("properties", {})
    return props.get(property_name, [])


def derive_workspace_id_from_project_id(project_id: str, env_cfg: EnvConfig) -> str | None:  # type: ignore[name-defined]
    """Derive workspace resource id from a project id.

    Pattern:
      /subscriptions/.../providers/Microsoft.Discovery/workspaces/<workspace>/projects/<project>

    If env_cfg provided, mutates env_cfg.workspace_resource_id with the derived value (or empty
    string if not matched).
    Returns the derived workspace resource id or None.
    """
    if "/providers/Microsoft.Discovery/workspaces/" not in project_id:
        return None
    marker = "/projects/"
    if marker not in project_id:
        return None
    idx = project_id.find(marker)
    derived = project_id[:idx].rstrip("/")
    env_cfg.workspace_resource_id = derived
    return derived


def fetch_workspace_url_from_resource_id(workspace_resource_id: str, env_cfg: EnvConfig) -> str:  # type: ignore[name-defined]
    """Lookup workspace URL (endpoint) from workspace resource id.

    Raises RuntimeError on any failure (az not found, non-zero exit, parse error,
    or when no URL-like property can be determined). On success returns the
    normalized URL (no trailing slash) and mutates env_cfg.workspace_url.
    """
    cmd = ["az", "resource", "show", "--ids", workspace_resource_id, "-o", "json"]
    debug(f"fetch_workspace_url_from_resource_id(): executing {' '.join(cmd)}")
    try:
        res = run_az(cmd)
    except OSError as exc:  # pragma: no cover
        msg = "Azure CLI 'az' not found while fetching workspace resource"
        raise RuntimeError(msg) from exc
    if res.returncode != 0:
        msg = f"az CLI failed with exit code {res.returncode} while fetching workspace resource"
        raise RuntimeError(msg)
    try:
        data = json.loads(res.stdout)
    except Exception as exc:  # pragma: no cover
        # Provide truncated stdout for debugging parse issues
        msg = "Failed to parse JSON from az workspace resource show output"
        raise RuntimeError(msg) from exc
    props = data.get("properties") or {}
    # Retrieve workspaceApiUri (expected property) and validate
    val = props.get("workspaceApiUri")
    if isinstance(val, str) and val.startswith("http"):
        val_norm = val.rstrip("/")
        env_cfg.workspace_url = val_norm
        return val_norm
    msg = "workspaceApiUri not found or invalid in workspace resource properties"
    raise RuntimeError(msg)


def get_acr_location(acr_name: str) -> str:
    """Return the Azure region for the specified container registry."""
    cmd = [
        "az",
        "acr",
        "show",
        "--name",
        acr_name,
        "--query",
        "location",
        "-o",
        "tsv",
    ]
    debug(f"get_acr_location(): executing {' '.join(cmd)}")
    try:
        res = run_az(cmd)
    except OSError as exc:  # pragma: no cover
        msg = "Azure CLI 'az' not found while fetching ACR location"
        raise RuntimeError(msg) from exc
    if res.returncode != 0:
        stderr = res.stderr.strip()
        msg = f"az CLI failed with exit code {res.returncode} while fetching ACR location: {stderr}"
        raise RuntimeError(msg) from None
    location = res.stdout.strip()
    if not location:
        msg = f"No location found for ACR '{acr_name}'"
        raise RuntimeError(msg)
    debug(f"get_acr_location(): ACR '{acr_name}' is in location '{location}'")
    return location


def get_resource_group_and_location(resource_id: str) -> tuple[str, str]:
    """Extract resource group and location from any Azure resource ID.

    Args:
        resource_id: Full Azure resource ID

    Returns:
        Tuple of (resource_group_name, location)

    Raises:
        RuntimeError: If az CLI fails or resource properties cannot be retrieved
    """
    cmd = ["az", "resource", "show", "--ids", resource_id, "-o", "json"]
    debug(f"get_resource_group_and_location(): executing {' '.join(cmd)}")

    try:
        res = run_az(cmd)
    except OSError as exc:
        msg = "Azure CLI 'az' not found while fetching resource details"
        raise RuntimeError(msg) from exc

    if res.returncode != 0:
        stderr = res.stderr.strip()
        msg = f"az CLI failed with exit code {res.returncode} while fetching resource: {stderr}"
        raise RuntimeError(msg)

    try:
        data = json.loads(res.stdout)
    except Exception as exc:
        msg = "Failed to parse JSON from az resource show output"
        raise RuntimeError(msg) from exc

    # Extract resource group from resourceGroup field
    resource_group = data.get("resourceGroup")
    if not resource_group:
        msg = f"resourceGroup field missing in resource data for {resource_id}"
        raise RuntimeError(msg)

    # Extract location from location field
    location = data.get("location")
    if not location:
        msg = f"location field missing in resource data for {resource_id}"
        raise RuntimeError(msg)

    debug(
        f"get_resource_group_and_location(): resource_group={resource_group}, location={location}"
    )
    return resource_group, location


def list_datacontainers(subscription: str = "") -> list[dict]:
    """List all ``Microsoft.Discovery/datacontainers`` resources, with kind.

    Returns a list of ``{"name", "id", "location", "resourceGroup", "kind"}``
    dicts. ``kind`` is the discriminator on ``properties.dataStore.kind``
    (one of ``AzureStorageBlob``, ``AzureStorageFile``, ``DiscoveryStorage``)
    or empty when it could not be determined.
    """
    return list_containers_with_kind(
        "Microsoft.Discovery/datacontainers",
        "properties.dataStore.kind",
        subscription=subscription,
    )


def list_storagecontainers(subscription: str = "") -> list[dict]:
    """List all ``Microsoft.Discovery/storagecontainers`` resources, with kind.

    Returns a list of ``{"name", "id", "location", "resourceGroup", "kind"}``
    dicts. ``kind`` is the discriminator on ``properties.storageStore.kind``
    (one of ``AzureStorageBlob``, ``AzureNetAppFiles``) or empty when it could
    not be determined.
    """
    return list_containers_with_kind(
        "Microsoft.Discovery/storagecontainers",
        "properties.storageStore.kind",
        subscription=subscription,
    )


def list_anf_volumes(subscription: str = "") -> list[dict]:
    """List all ``Microsoft.NetApp/netAppAccounts/capacityPools/volumes`` resources.

    Used by the V2 scratch-storageContainer creation flow to let users pick an
    existing ANF volume to wrap.

    Returns:
        List of ``{"name", "id", "location", "resourceGroup"}`` dicts. The
        ``name`` is the full ``account/pool/volume`` triple as Azure CLI
        returns it.
    """
    cmd = [
        "az", "resource", "list",
        "--resource-type", "Microsoft.NetApp/netAppAccounts/capacityPools/volumes",
        "-o", "json",
    ]
    if subscription:
        cmd.extend(["--subscription", subscription])
    debug(f"list_anf_volumes(): {' '.join(cmd)}")
    res = run_az(cmd)
    if res.returncode != 0:
        error(
            f"list_anf_volumes(): az returned exit={res.returncode} "
            f"stderr={res.stderr.strip()[:300]}"
        )
        return []
    data = json.loads(res.stdout) if res.stdout.strip() else []
    return [
        {
            "name": d.get("name", ""),
            "id": d.get("id", ""),
            "location": d.get("location", ""),
            "resourceGroup": d.get("resourceGroup", ""),
        }
        for d in data
    ]


def list_storage_accounts(subscription: str = "") -> list[dict]:
    """List all ``Microsoft.Storage/storageAccounts`` resources in a subscription.

    Used by the Archive blob-container creation flow to let users pick an
    existing storage account to wrap.

    Returns:
        List of ``{"name", "id", "location", "resourceGroup"}`` dicts.
    """
    cmd = [
        "az", "resource", "list",
        "--resource-type", "Microsoft.Storage/storageAccounts",
        "-o", "json",
    ]
    if subscription:
        cmd.extend(["--subscription", subscription])
    debug(f"list_storage_accounts(): {' '.join(cmd)}")
    res = run_az(cmd)
    if res.returncode != 0:
        error(
            f"list_storage_accounts(): az returned exit={res.returncode} "
            f"stderr={res.stderr.strip()[:300]}"
        )
        return []
    data = json.loads(res.stdout) if res.stdout.strip() else []
    return [
        {
            "name": d.get("name", ""),
            "id": d.get("id", ""),
            "location": d.get("location", ""),
            "resourceGroup": d.get("resourceGroup", ""),
        }
        for d in data
    ]


def list_containers_with_kind(
    resource_type: str,
    kind_property_path: str,
    subscription: str = "",
) -> list[dict]:
    """List Discovery container resources annotated with their ``kind`` discriminator.

    Uses ``az graph query`` to fetch the kind in a single round-trip. Falls
    back to a per-resource ``az resource show`` enrichment loop when the graph
    query fails (e.g. tenant without ARG access, or freshness lag for newly
    created resources). Resources that cannot be enriched are still returned
    with ``kind=""``.

    Args:
        resource_type: Full ARM type, e.g. ``Microsoft.Discovery/datacontainers``.
        kind_property_path: Dotted JSON path under the ARM resource where the
            kind discriminator lives, e.g. ``properties.dataStore.kind`` for
            V1 dataContainers or ``properties.storageStore.kind`` for V2
            storageContainers.
        subscription: Optional explicit subscription ID. When empty, uses the
            active ``az`` subscription.

    Returns:
        ``[{"name", "id", "location", "resourceGroup", "kind"}, ...]``.
    """
    # KQL field access doesn't use dotted notation; build a chain of
    # bracket-indexed lookups for each segment under the root.
    segments = kind_property_path.split(".")
    if len(segments) < 2 or segments[0] != "properties":
        msg = f"kind_property_path must start with 'properties.': {kind_property_path}"
        raise ValueError(msg)
    kql_path = "properties" + "".join(f"['{s}']" for s in segments[1:])
    kql_type = resource_type.lower()
    kql = (
        f"Resources | where type =~ '{kql_type}' "
        f"| extend kind_ = tostring({kql_path}) "
        f"| project name, id, location, resourceGroup, kind_"
    )
    cmd = ["az", "graph", "query", "-q", kql, "-o", "json"]
    if subscription:
        cmd.extend(["--subscriptions", subscription])
    debug(f"list_containers_with_kind(): graph query for {resource_type}")
    res = run_az(cmd)
    if res.returncode == 0 and res.stdout.strip():
        try:
            payload = json.loads(res.stdout)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return [
                {
                    "name": d.get("name", ""),
                    "id": d.get("id", ""),
                    "location": d.get("location", ""),
                    "resourceGroup": d.get("resourceGroup", ""),
                    "kind": d.get("kind_", "") or "",
                }
                for d in payload["data"]
            ]
        debug("list_containers_with_kind(): graph payload missing 'data'; falling back")
    else:
        debug(
            f"list_containers_with_kind(): graph query exit={res.returncode} "
            f"stderr={res.stderr.strip()[:200]}; falling back to per-resource"
        )

    # Fallback: list resources, enrich each with its kind via per-resource fetch.
    base_cmd = ["az", "resource", "list", "--resource-type", resource_type, "-o", "json"]
    if subscription:
        base_cmd.extend(["--subscription", subscription])
    base_res = run_az(base_cmd)
    if base_res.returncode != 0:
        debug(
            f"list_containers_with_kind(): fallback list failed exit={base_res.returncode} "
            f"stderr={base_res.stderr.strip()[:200]}"
        )
        return []
    base_data = json.loads(base_res.stdout) if base_res.stdout.strip() else []
    out: list[dict] = []
    for d in base_data:
        rid = d.get("id", "")
        kind = ""
        if rid:
            try:
                if resource_type.lower().endswith("/datacontainers"):
                    kind = (get_datacontainer_datastore(rid) or {}).get("kind", "") or ""
                else:
                    kind = (get_storagecontainer_storagestore(rid) or {}).get("kind", "") or ""
            except RuntimeError:
                kind = ""
        out.append({
            "name": d.get("name", ""),
            "id": rid,
            "location": d.get("location", ""),
            "resourceGroup": d.get("resourceGroup", ""),
            "kind": kind,
        })
    return out


def list_storages(subscription: str = "") -> list[dict]:
    """List all ``Microsoft.Discovery/storages`` resources in a subscription.

    Args:
        subscription: Optional subscription ID. When empty, uses the active
            ``az`` subscription. When provided, the call is scoped explicitly
            so users with multi-sub setups get the workspace's subscription.

    Returns:
        List of ``{"name", "id", "location", "resourceGroup"}`` dicts. Empty
        list (without raising) when no storages are present.
    """
    cmd = ["az", "resource", "list", "--resource-type", "Microsoft.Discovery/storages", "-o", "json"]
    if subscription:
        cmd.extend(["--subscription", subscription])
    debug(f"list_storages(): executing {' '.join(cmd)}")
    res = run_az(cmd)
    if res.returncode != 0:
        error(
            f"list_storages(): az returned non-zero exit code={res.returncode} "
            f"stderr={res.stderr.strip()[:300]}"
        )
        msg = "Failed to list Microsoft.Discovery/storages"
        raise RuntimeError(msg)
    data = json.loads(res.stdout) if res.stdout.strip() else []
    debug(f"list_storages(): returned {len(data)} storages")
    return [
        {
            "name": d.get("name", ""),
            "id": d.get("id", ""),
            "location": d.get("location", ""),
            "resourceGroup": d.get("resourceGroup", ""),
        }
        for d in data
    ]


def extract_vnet_id(subnet_id: str) -> str:
    """Return the parent VNet resource ID from a subnet resource ID, or "".

    Subnet IDs look like
    ``/subscriptions/<s>/resourceGroups/<rg>/providers/Microsoft.Network/virtualNetworks/<vnet>/subnets/<name>``.
    """
    if not subnet_id or "/subnets/" not in subnet_id:
        return ""
    return subnet_id.split("/subnets/")[0]


def resolve_supercomputer_vnet(supercomputer_id: str, subscription: str = "") -> str:
    """Return the supercomputer's VNet resource ID, or "" when not resolvable.

    Same lookup as :func:`resolve_supercomputer_region` but returning the
    VNet ARM ID instead of its location. Used by the Scratch picker to
    enforce that selected/created ANF wrappers live on the same VNet (a
    stricter requirement than same region).
    """
    if not supercomputer_id:
        return ""
    sub = subscription or (
        supercomputer_id.split("/")[2] if "/subscriptions/" in supercomputer_id else ""
    )
    cmd = [
        "az", "resource", "show", "--ids", supercomputer_id,
        "--query", "properties.subnetId", "-o", "tsv",
    ]
    if sub:
        cmd.extend(["--subscription", sub])
    debug(f"resolve_supercomputer_vnet(): fetching subnetId for {supercomputer_id}")
    res = run_az(cmd)
    if res.returncode != 0:
        debug(
            f"resolve_supercomputer_vnet(): az show failed exit={res.returncode} "
            f"stderr={res.stderr.strip()[:200]}"
        )
        return ""
    return extract_vnet_id((res.stdout or "").strip())


def resolve_supercomputer_region(supercomputer_id: str, subscription: str = "") -> tuple[str, str]:
    """Determine the underlying region of a supercomputer.

    The supercomputer's effective region is the region of its backing AKS
    cluster. Discovery exposes this via ``properties.subnetId`` on the
    supercomputer ARM resource — the VNet that subnet belongs to is
    co-located with the AKS cluster, so its ``location`` is the
    authoritative region. Falls back to the supercomputer's own
    ``location`` field when the subnet cannot be resolved (e.g. permission
    issues).

    Args:
        supercomputer_id: Full Azure resource ID of the supercomputer.
        subscription: Optional subscription ID for ``az`` calls.

    Returns:
        Tuple of ``(region, source)`` where ``source`` is one of
        ``"vnet"`` (high confidence — extracted from ``subnetId``'s VNet),
        ``"supercomputer"`` (fallback — used the SC ARM ``location``)
        or ``""`` (could not determine).
    """
    if not supercomputer_id:
        return ("", "")

    sub = subscription or (supercomputer_id.split("/")[2] if "/subscriptions/" in supercomputer_id else "")

    # Fetch the supercomputer once; we need both subnetId and location.
    cmd = ["az", "resource", "show", "--ids", supercomputer_id, "-o", "json"]
    if sub:
        cmd.extend(["--subscription", sub])
    debug(f"resolve_supercomputer_region(): fetching {supercomputer_id}")
    res = run_az(cmd)
    if res.returncode != 0:
        debug(
            f"resolve_supercomputer_region(): az show failed exit={res.returncode} "
            f"stderr={res.stderr.strip()[:200]}"
        )
        return ("", "")
    try:
        sc = json.loads(res.stdout)
    except json.JSONDecodeError:
        return ("", "")

    sc_location = sc.get("location", "") or ""
    subnet_id = (sc.get("properties") or {}).get("subnetId", "") or ""

    # 1. Authoritative: derive VNet ID from subnetId, look up its region.
    # subnetId format: /subscriptions/<s>/resourceGroups/<rg>/providers/
    #   Microsoft.Network/virtualNetworks/<vnet>/subnets/<subnet>
    if subnet_id and "/subnets/" in subnet_id:
        vnet_id = subnet_id.split("/subnets/")[0]
        vnet_sub = subnet_id.split("/")[2] if "/subscriptions/" in subnet_id else sub
        vcmd = ["az", "resource", "show", "--ids", vnet_id, "--query", "location", "-o", "tsv"]
        if vnet_sub:
            vcmd.extend(["--subscription", vnet_sub])
        debug(f"resolve_supercomputer_region(): probing VNet {vnet_id}")
        vres = run_az(vcmd)
        if vres.returncode == 0:
            loc = (vres.stdout or "").strip()
            if loc:
                debug(f"resolve_supercomputer_region(): VNet region={loc}")
                return (loc, "vnet")

    # 2. Fall back to the supercomputer ARM resource location
    if sc_location:
        debug(f"resolve_supercomputer_region(): SC fallback region={sc_location}")
        return (sc_location, "supercomputer")

    debug("resolve_supercomputer_region(): could not determine region")
    return ("", "")


def get_datacontainer_datastore(datacontainer_id: str) -> dict:
    """Return the ``properties.dataStore`` dict for a data container resource.

    The dataStore shape depends on ``kind``:
      - ``AzureStorageBlob``: contains ``storageAccountId``
      - ``DiscoveryStorage``: contains ``discoveryStorageId``
    """
    cmd = ["az", "resource", "show", "--ids", datacontainer_id, "-o", "json"]
    debug(f"get_datacontainer_datastore(): executing {' '.join(cmd)}")

    try:
        res = run_az(cmd)
    except OSError as exc:
        msg = "Azure CLI 'az' not found while fetching data container resource"
        raise RuntimeError(msg) from exc

    if res.returncode != 0:
        stderr = res.stderr.strip()
        msg = (
            f"az CLI failed with exit code {res.returncode} while fetching data container: {stderr}"
        )
        raise RuntimeError(msg)

    try:
        data = json.loads(res.stdout)
    except Exception as exc:
        msg = "Failed to parse JSON from az data container resource show output"
        raise RuntimeError(msg) from exc

    return data.get("properties", {}).get("dataStore", {}) or {}


def get_datacontainer_storage_details(datacontainer_id: str) -> str:
    """Return storage_account_id for an ``AzureStorageBlob`` data container.

    Note: The dataStore schema only contains storageAccountId and kind,
    not a specific container name. Blob containers are created separately.

    Raises RuntimeError if the data container is not backed by an Azure Storage
    blob account (e.g. kind=DiscoveryStorage) or if storageAccountId is missing.
    """
    data_store = get_datacontainer_datastore(datacontainer_id)
    kind = data_store.get("kind")
    storage_account_id = data_store.get("storageAccountId")

    if not storage_account_id:
        if kind and kind != "AzureStorageBlob":
            msg = (
                f"data container dataStore.kind is '{kind}', which is not backed by "
                "an Azure Storage blob account (expected 'AzureStorageBlob')"
            )
        else:
            msg = "storageAccountId missing in data container properties.dataStore"
        raise RuntimeError(msg)

    return storage_account_id


def get_storagecontainer_storagestore(storagecontainer_id: str) -> dict:
    """Return the ``properties.storageStore`` dict for a storage container resource.

    Storage containers are the v2 equivalent of data containers and use the
    ``2026-02-01-preview`` API version. The ``storageStore`` shape mirrors the
    data container ``dataStore`` shape:
      - ``AzureStorageBlob``: contains ``storageAccountId``
      - ``DiscoveryStorage``: contains ``discoveryStorageId``
    """
    cmd = [
        "az",
        "resource",
        "show",
        "--ids",
        storagecontainer_id,
        "--api-version",
        "2026-02-01-preview",
        "-o",
        "json",
    ]
    debug(f"get_storagecontainer_storagestore(): executing {' '.join(cmd)}")

    try:
        res = run_az(cmd)
    except OSError as exc:
        msg = "Azure CLI 'az' not found while fetching storage container resource"
        raise RuntimeError(msg) from exc

    if res.returncode != 0:
        stderr = res.stderr.strip()
        msg = (
            f"az CLI failed with exit code {res.returncode} while fetching storage "
            f"container: {stderr}"
        )
        raise RuntimeError(msg)

    try:
        data = json.loads(res.stdout)
    except Exception as exc:
        msg = "Failed to parse JSON from az storage container resource show output"
        raise RuntimeError(msg) from exc

    return data.get("properties", {}).get("storageStore", {}) or {}


def get_storagecontainer_storage_details(storagecontainer_id: str) -> str:
    """Return storage_account_id for an ``AzureStorageBlob`` storage container.

    Raises RuntimeError if the storage container is not backed by an Azure
    Storage blob account (e.g. kind=DiscoveryStorage) or if storageAccountId
    is missing.
    """
    storage_store = get_storagecontainer_storagestore(storagecontainer_id)
    kind = storage_store.get("kind")
    storage_account_id = storage_store.get("storageAccountId")

    if not storage_account_id:
        if kind and kind != "AzureStorageBlob":
            msg = (
                f"storage container storageStore.kind is '{kind}', which is not backed "
                "by an Azure Storage blob account (expected 'AzureStorageBlob')"
            )
        else:
            msg = "storageAccountId missing in storage container properties.storageStore"
        raise RuntimeError(msg)

    return storage_account_id


def get_blob_uri_from_datacontainer(datacontainer_id: str, container_name: str) -> str:
    """Get blob URI root for a data container and specific blob container.

    Args:
        datacontainer_id: The data container resource ID
        container_name: The blob container name within the storage account

    Returns:
        Full blob URI including container name
    """
    storage_account_id = get_datacontainer_storage_details(datacontainer_id)
    storage_account_name = storage_account_id.split("/")[-1]
    uri = f"https://{storage_account_name}.blob.core.windows.net/{container_name}/"
    debug(f"get_blob_uri_from_datacontainer(): constructed URI {uri} for {storage_account_name}")
    return uri


def check_blob_container_permissions(container_resource_id: str) -> dict[str, bool]:
    """Check if the current user has necessary permissions on a blob container.

    Args:
        container_resource_id: The full resource ID of the blob container

    Returns:
        Dictionary with permission check results:
        {
            "has_required_permission": bool,  # True if user has Contributor or Owner
            "role_assignments": list[str],    # List of role names assigned to user
        }

    Raises:
        RuntimeError: If az CLI fails to check permissions
    """
    # Required roles for blob data access
    required_roles = {
        "Storage Blob Data Contributor",
        "Storage Blob Data Owner",
    }

    # First, get the current user's object ID
    user_cmd = ["az", "ad", "signed-in-user", "show", "--query", "id", "-o", "tsv"]
    debug(f"check_blob_container_permissions(): getting user ID with {' '.join(user_cmd)}")

    try:
        user_res = run_az(user_cmd)
    except OSError as exc:
        msg = "Azure CLI 'az' not found while getting current user"
        raise RuntimeError(msg) from exc

    if user_res.returncode != 0:
        stderr = user_res.stderr.strip()
        msg = (
            f"az CLI failed with exit code {user_res.returncode} "
            f"while getting current user: {stderr}"
        )
        raise RuntimeError(msg)

    user_object_id = user_res.stdout.strip()
    if not user_object_id:
        msg = "Could not determine current user object ID"
        raise RuntimeError(msg)

    debug(f"check_blob_container_permissions(): user object ID: {user_object_id}")

    # Now check role assignments for this user
    cmd = [
        "az",
        "role",
        "assignment",
        "list",
        "--scope",
        container_resource_id,
        "--include-inherited",
        "--assignee",
        user_object_id,
        "--query",
        "[].roleDefinitionName",
        "-o",
        "json",
    ]
    debug(f"check_blob_container_permissions(): executing {' '.join(cmd)}")

    try:
        res = run_az(cmd)
    except OSError as exc:
        msg = "Azure CLI 'az' not found while checking blob container permissions"
        raise RuntimeError(msg) from exc

    if res.returncode != 0:
        stderr = res.stderr.strip()
        msg = f"az CLI failed with exit code {res.returncode} while checking permissions: {stderr}"
        raise RuntimeError(msg)

    try:
        role_assignments = json.loads(res.stdout)
    except Exception as exc:
        msg = "Failed to parse JSON from az role assignment list output"
        raise RuntimeError(msg) from exc

    debug(f"check_blob_container_permissions(): found {len(role_assignments)} role assignments")

    # Check if user has any of the required roles
    has_required = any(role in required_roles for role in role_assignments)

    return {
        "has_required_permission": has_required,
        "role_assignments": role_assignments,
    }


def get_nodepool_details(nodepool_id: str) -> dict:
    """Fetch detailed information about a nodepool from Azure.

    Args:
        nodepool_id: Full Azure resource ID of the nodepool

    Returns:
        Dictionary with nodepool properties including sku information

    Raises:
        RuntimeError: If az CLI fails or resource not found
    """
    cmd = ["az", "resource", "show", "--ids", nodepool_id, "-o", "json"]
    debug(f"get_nodepool_details(): executing {' '.join(cmd)}")

    try:
        res = run_az(cmd)
    except OSError as exc:
        msg = "Azure CLI 'az' not found while fetching nodepool details"
        raise RuntimeError(msg) from exc

    if res.returncode != 0:
        stderr = res.stderr.strip()
        msg = f"az CLI failed with exit code {res.returncode} while fetching nodepool: {stderr}"
        raise RuntimeError(msg)

    try:
        return json.loads(res.stdout)
    except Exception as exc:
        msg = "Failed to parse JSON from az nodepool show output"
        raise RuntimeError(msg) from exc


async def _fetch_nodepool_details_async(
    client,  # httpx.AsyncClient
    nodepool_id: str,
    token: str,
) -> tuple[str, dict]:
    """Async fetch of a single nodepool's details using ARM API."""
    from discovery.poll.dataplane_api import http_get_async, AuthHeaders

    url = f"https://management.azure.com{nodepool_id}"
    params = {"api-version": "2025-07-01-preview"}
    headers = AuthHeaders(Authorization=f"Bearer {token}")

    try:
        data = await http_get_async(client=client, url=url, headers=headers, params=params)
        return (nodepool_id, data)
    except Exception as e:
        debug(f"Async fetch failed for nodepool {nodepool_id}: {e}")
        return (nodepool_id, {})


async def _fetch_all_nodepools_async(
    nodepool_ids: list[str],
    token: str,
) -> dict[str, dict]:
    """Fetch details for multiple nodepools concurrently using async."""
    from discovery.poll.dataplane_api import create_async_client

    if not nodepool_ids:
        return {}

    start = time.perf_counter()
    results: dict[str, dict] = {}

    async with create_async_client() as client:
        tasks = [
            _fetch_nodepool_details_async(client, np_id, token)
            for np_id in nodepool_ids
        ]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for item in completed:
            if isinstance(item, BaseException):
                debug(f"Async nodepool task failed: {item}")
                continue
            np_id, details = item
            results[np_id] = details

    elapsed = time.perf_counter() - start
    debug(f"Async fetched {len(results)} nodepools in {elapsed:.2f}s")
    return results


def get_all_nodepool_details(nodepool_ids: list[str]) -> dict[str, dict]:
    """Fetch details for multiple nodepools in parallel using async HTTP.

    Args:
        nodepool_ids: List of full Azure resource IDs for nodepools

    Returns:
        Dictionary mapping nodepool ID to its details dict
    """
    if not nodepool_ids:
        return {}

    token = _get_access_token_for_arm()
    if not token:
        debug("Could not get token for nodepool fetch")
        return {}

    return asyncio.run(_fetch_all_nodepools_async(nodepool_ids, token))


# ---------------------------------------------------------------------------
# VM SKU cache with async fetching
# ---------------------------------------------------------------------------

# In-memory cache for VM SKU details by location
_vm_sku_cache: dict[str, dict[str, dict[str, str]]] = {}


def _get_access_token_for_arm() -> str | None:
    """Get Azure access token for ARM API."""
    cmd = [
        "az", "account", "get-access-token",
        "--resource", "https://management.azure.com",
        "--query", "accessToken",
        "-o", "tsv",
    ]
    try:
        result = run_az(cmd)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except OSError:
        pass
    return None


def _get_subscription_id() -> str | None:
    """Get the current Azure subscription ID."""
    cmd = ["az", "account", "show", "--query", "id", "-o", "tsv"]
    try:
        result = run_az(cmd)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except OSError:
        pass
    return None


def _parse_sku_response(data: dict) -> dict[str, dict[str, str]]:
    """Parse SKU API response into a dict mapping VM size name to details."""
    result: dict[str, dict[str, str]] = {}
    for sku in data.get("value", []):
        # Only process virtualMachines
        if sku.get("resourceType") != "virtualMachines":
            continue

        name = sku.get("name", "")
        if not name:
            continue

        capabilities = sku.get("capabilities", [])
        caps = {c["name"]: c["value"] for c in capabilities}

        result[name] = {
            "cpus": caps.get("vCPUs", ""),
            "memory": caps.get("MemoryGB", ""),
            "gpus": caps.get("GPUs", "0"),
        }
    return result


async def _fetch_skus_for_location_async(
    client,  # httpx.AsyncClient - avoid import at module level
    location: str,
    subscription_id: str,
    token: str,
) -> tuple[str, dict[str, dict[str, str]]]:
    """Async fetch of SKUs for a single location using shared client."""
    from discovery.poll.dataplane_api import http_get_async, AuthHeaders

    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/providers/Microsoft.Compute/skus"
    )
    params = {
        "api-version": "2021-07-01",
        "$filter": f"location eq '{location}'",
    }
    headers = AuthHeaders(Authorization=f"Bearer {token}")

    try:
        data = await http_get_async(client=client, url=url, headers=headers, params=params)
        result = _parse_sku_response(data)
        debug(f"Async fetched {len(result)} SKUs for {location}")
        return (location, result)
    except Exception as e:
        debug(f"Async fetch failed for {location}: {e}")
        return (location, {})


async def _fetch_all_locations_async(
    locations: list[str],
    subscription_id: str,
    token: str,
) -> dict[str, dict[str, dict[str, str]]]:
    """Fetch SKUs for multiple locations concurrently using async."""
    from discovery.poll.dataplane_api import create_async_client

    start = time.perf_counter()
    results: dict[str, dict[str, dict[str, str]]] = {}

    async with create_async_client() as client:
        tasks = [
            _fetch_skus_for_location_async(client, loc, subscription_id, token)
            for loc in locations
        ]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for item in completed:
            if isinstance(item, BaseException):
                debug(f"Async task failed: {item}")
                continue
            loc, skus = item
            results[loc] = skus

    elapsed = time.perf_counter() - start
    debug(f"Async fetched SKUs for {len(locations)} locations in {elapsed:.2f}s")
    return results


def _fetch_vm_skus_for_location(location: str, vm_sizes: set[str]) -> dict[str, dict[str, str]]:
    """Fetch VM SKUs for specific sizes in a location and return as a dict keyed by VM size name.

    Uses in-memory cache, then async HTTP API.

    Args:
        location: Azure region (e.g., 'eastus')
        vm_sizes: Set of VM size names to look up

    Returns:
        Dictionary mapping VM size name to {'cpus', 'memory', 'gpus'}
    """
    if not vm_sizes:
        return {}

    # Check in-memory cache
    if location not in _vm_sku_cache:
        _vm_sku_cache[location] = {}

    cached = _vm_sku_cache[location]
    needed = vm_sizes - set(cached.keys())

    if not needed:
        return cached

    # Fetch ALL SKUs for this location using async
    debug(f"_fetch_vm_skus_for_location({location}): need {len(needed)} SKUs, fetching all")

    token = _get_access_token_for_arm()
    subscription_id = _get_subscription_id()

    new_skus: dict[str, dict[str, str]] = {}
    if token and subscription_id:
        try:
            results = asyncio.run(
                _fetch_all_locations_async([location], subscription_id, token)
            )
            new_skus = results.get(location, {})
        except Exception as e:
            debug(f"Async fetch failed for {location}: {e}")

    # Merge new data into cache
    cached.update(new_skus)
    _vm_sku_cache[location] = cached

    return cached


def prefetch_vm_skus(location_to_sizes: dict[str, set[str]]) -> None:
    """Prefetch VM SKU details for multiple locations concurrently using async.

    Args:
        location_to_sizes: Dict mapping location to set of VM sizes needed
    """
    if not location_to_sizes:
        return

    start = time.perf_counter()

    # Check which locations need fetching
    locations_to_fetch: list[str] = []
    for location, sizes in location_to_sizes.items():
        if location not in _vm_sku_cache:
            _vm_sku_cache[location] = {}

        cached = _vm_sku_cache[location]
        needed = sizes - set(cached.keys())
        if needed:
            locations_to_fetch.append(location)

    if not locations_to_fetch:
        debug("All SKUs already cached, no fetch needed")
        return

    # Get auth credentials once (shared across all requests)
    token = _get_access_token_for_arm()
    subscription_id = _get_subscription_id()

    if not token or not subscription_id:
        debug("Could not get token/subscription for SKU fetch")
        return

    # Use async to fetch all locations concurrently
    try:
        results = asyncio.run(
            _fetch_all_locations_async(locations_to_fetch, subscription_id, token)
        )

        # Update caches with results
        for location, skus in results.items():
            if skus:
                if location not in _vm_sku_cache:
                    _vm_sku_cache[location] = {}
                _vm_sku_cache[location].update(skus)
                debug(f"Prefetched {len(skus)} SKUs for {location}")

    except Exception as e:
        debug(f"Async prefetch failed: {e}")

    elapsed = time.perf_counter() - start
    debug(f"prefetch_vm_skus completed in {elapsed:.2f}s")


def get_vm_sku_details(vm_size: str, location: str) -> dict[str, str]:
    """Fetch VM SKU details (vCPUs, memory, GPUs) from Azure.

    Args:
        vm_size: The VM size name (e.g., 'Standard_NC96ads_A100_v4')
        location: Azure region (e.g., 'eastus')

    Returns:
        Dictionary with 'cpus', 'memory', 'gpus' as strings
    """
    # Fetch just this size (will be cached for future calls)
    skus = _fetch_vm_skus_for_location(location, {vm_size})
    return skus.get(vm_size, {"cpus": "", "memory": "", "gpus": "0"})


def list_all_nodepools_with_details(env_cfg: EnvConfig) -> list:
    """List all nodepools from ALL supercomputers in the workspace with their details.

    Scratch dataContainer association is driven by the explicit per-supercomputer
    mapping on ``env_cfg.supercomputer_scratch_dcs`` (set during interactive
    ``configure``). Each entry maps a supercomputer ID to a
    ``Microsoft.Discovery/datacontainers`` resource of kind ``DiscoveryStorage``,
    used to construct an explicit ``/anf_scratch`` URI on V1 tool runs.

    Args:
        env_cfg: Active configuration. Must have ``workspace_resource_id`` set.
            ``supercomputer_scratch_dcs`` (dict) provides the SC ID →
            dataContainer ID map; missing entries leave ``scratch_dc_id`` blank.

    Returns:
        List of NodepoolInfo objects with id, name, supercomputer_id,
        supercomputer_name, resource_group, scratch_dc_id,
        sku, and resource details.
    """
    from discovery.poll.models.compute import NodepoolInfo

    workspace_resource_id = env_cfg.workspace_resource_id

    # Get all supercomputer IDs from workspace
    supercomputer_ids = get_workspace_ids(workspace_resource_id, "supercomputerIds")
    debug(f"list_all_nodepools_with_details(): found {len(supercomputer_ids)} supercomputers")

    sub = env_cfg.subscription
    sc_scratch_map: dict[str, str] = {
        k.lower(): v for k, v in (env_cfg.supercomputer_scratch_dcs or {}).items()
    }

    # Get all nodepool IDs (we'll filter by supercomputer later)
    all_nodepool_ids = list_resources("Microsoft.Discovery/supercomputers/nodepools", assert_present=False)
    debug(f"list_all_nodepools_with_details: all_nodepool_ids={all_nodepool_ids}")
    debug(f"list_all_nodepools_with_details: supercomputer_ids={supercomputer_ids}")

    # Build list of nodepool IDs that belong to our supercomputers; track full SC ID.
    nodepool_to_sc: dict[str, tuple[str, str]] = {}  # nodepool_id -> (sc_id, sc_name)
    for sc_id in supercomputer_ids:
        sc_name = sc_id.split("/")[-1] if "/" in sc_id else sc_id
        for np_id in all_nodepool_ids:
            if is_nodepool_of_supercomputer(np_id, sc_id):
                nodepool_to_sc[np_id] = (sc_id, sc_name)
                debug(f"list_all_nodepools_with_details: matched {np_id} to {sc_name}")

    # Fetch ALL nodepool details in parallel using async HTTP
    all_details = get_all_nodepool_details(list(nodepool_to_sc.keys()))

    # Collect VM sizes per location for bulk SKU prefetch
    location_to_sizes: dict[str, set[str]] = {}
    for details in all_details.values():
        props = details.get("properties", {})
        location = details.get("location", "")
        vm_size = props.get("vmSize", "")
        if vm_size and location:
            if location not in location_to_sizes:
                location_to_sizes[location] = set()
            location_to_sizes[location].add(vm_size)

    # Prefetch all needed VM SKUs in bulk (one query per location)
    prefetch_vm_skus(location_to_sizes)

    # Build NodepoolInfo objects with SKU data from cache
    nodepools = []
    for np_id, (sc_id, sc_name) in nodepool_to_sc.items():
        details = all_details.get(np_id, {})
        rg_name = extract_resource_group(np_id)
        scratch_dc_id = sc_scratch_map.get(sc_id.lower(), "")

        props = details.get("properties", {})
        location = details.get("location", "")
        vm_size = props.get("vmSize", "")
        max_nodes = props.get("maxNodeCount", 0)
        name = np_id.split("/")[-1] if "/" in np_id else np_id

        sku_info = {"cpus": "", "memory": "", "gpus": "0"}
        if vm_size and location:
            sku_info = get_vm_sku_details(vm_size, location)

        nodepools.append(NodepoolInfo(
            id=np_id,
            name=name,
            supercomputer_id=sc_id,
            supercomputer_name=sc_name,
            resource_group=rg_name,
            scratch_dc_id=scratch_dc_id,
            sku=vm_size,
            cpus=sku_info.get("cpus", ""),
            memory=sku_info.get("memory", ""),
            gpus=sku_info.get("gpus", "0"),
            max_nodes=max_nodes,
        ))

    return nodepools
