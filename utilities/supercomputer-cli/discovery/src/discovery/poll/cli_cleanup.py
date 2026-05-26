"""Cleanup commands for ANF scratch storage.

Provides the ``cleanup-anf`` command which identifies stale operation folders
on the shared ANF scratch volume by querying the operations API, and optionally
submits a cleanup tool run to delete them.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

import typer
from rich.console import Console
from rich.table import Table

from discovery.common.logging import debug, error, info
from discovery.poll.models.tool_response import AzureCoreOperationState
from discovery.poll.models.tool_run import DataMount, ToolRunRequest

from .cli_helpers import (
    emit_env,
    get_config_file_path,
    load_project_config,
)
from .dataplane_api import (
    list_operations,
    list_operations_page,
    run_and_poll,
)


app = typer.Typer()

# Operation states that indicate a job is still active
_ACTIVE_STATES = frozenset(
    {
        AzureCoreOperationState.NOT_STARTED,
        AzureCoreOperationState.PENDING,
        AzureCoreOperationState.ACCEPTED,
        AzureCoreOperationState.ACTIVE,
        AzureCoreOperationState.RUNNING,
    }
)

# Terminal states whose ANF folders can be cleaned up
_TERMINAL_STATES = frozenset(
    {
        AzureCoreOperationState.SUCCEEDED,
        AzureCoreOperationState.FAILED,
        AzureCoreOperationState.CANCELED,
    }
)

_DEFAULT_AGE_DAYS = 7
_MAX_OPERATIONS_SCAN = 5000

# Name for the ANF-root data container and data asset used by cleanup
_ANF_DC_NAME = "anf-scratch-dc"
_ANF_DA_NAME = "anf-root"


def _collect_all_operations(
    project_name: str, workspace_url: str
) -> list[tuple[str, str, datetime, str | None]]:
    """Paginate through operations and return (id, status, created_at, created_by) tuples."""
    ops: list[tuple[str, str, datetime, str | None]] = []
    scanned = 0

    result = list_operations(project_name, workspace_url)
    while True:
        for op in result.values:
            scanned += 1
            ops.append((op.id, op.status, op.created_at, op.created_by))
        debug(f"Scanned {scanned} operations so far")
        if not result.next_link or scanned >= _MAX_OPERATIONS_SCAN:
            break
        result = list_operations_page(result.next_link)

    info(f"Scanned {scanned} operations total")
    return ops


def _find_stale_operations(
    ops: list[tuple[str, str, datetime, str | None]],
    age_days: int,
) -> list[tuple[str, str, datetime, float, str | None]]:
    """Return (id, status, created_at, age_days, created_by) for stale terminal operations."""
    now = datetime.now(tz=timezone.utc)
    cutoff = now.timestamp() - (age_days * 86400)
    stale: list[tuple[str, str, datetime, float, str | None]] = []

    for op_id, status, created_at, created_by in ops:
        if status in _ACTIVE_STATES:
            continue
        if status not in _TERMINAL_STATES:
            continue
        ts = created_at.timestamp()
        if ts > cutoff:
            continue
        age = (now.timestamp() - ts) / 86400
        stale.append((op_id, status, created_at, age, created_by))

    stale.sort(key=lambda x: x[2])
    return stale


def _az_json(cmd: list[str]) -> dict:
    """Run an az CLI command and return parsed JSON output."""
    debug(f"Running: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        msg = f"az CLI failed (exit {res.returncode}): {res.stderr.strip()}"
        raise RuntimeError(msg)
    return json.loads(res.stdout)


def _resource_exists(resource_id: str, subscription: str) -> bool:
    """Check if an Azure resource exists by ID."""
    try:
        _az_json([
            "az", "resource", "show",
            "--ids", resource_id,
            "--subscription", subscription,
            "--api-version", "2025-07-01-preview",
            "-o", "json",
        ])
        return True
    except RuntimeError:
        return False


def _get_resource(resource_id: str, subscription: str) -> dict:
    """Get an Azure resource by ID."""
    return _az_json([
        "az", "resource", "show",
        "--ids", resource_id,
        "--subscription", subscription,
        "--api-version", "2025-07-01-preview",
        "-o", "json",
    ])


def _ensure_anf_datacontainer(
    subscription: str, resource_group: str, location: str,
    storage_id: str, existing_dc_id: str,
) -> str:
    """Ensure a DiscoveryStorage-backed DataContainer exists for ANF root access.

    Copies credentials from the existing blob-backed DataContainer.
    Returns the DataContainer resource ID.
    """
    dc_id = (
        f"/subscriptions/{subscription}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Discovery/dataContainers/{_ANF_DC_NAME}"
    )

    if _resource_exists(dc_id, subscription):
        info(f"DataContainer '{_ANF_DC_NAME}' already exists")
        return dc_id

    # Get credentials from the existing DataContainer
    info("Reading credentials from existing DataContainer...")
    existing_dc = _get_resource(existing_dc_id, subscription)
    credentials = existing_dc.get("properties", {}).get("credentials", [])
    if not credentials:
        raise RuntimeError(
            f"No credentials found on existing DataContainer {existing_dc_id}. "
            "Cannot create ANF DataContainer without credentials."
        )

    info(f"Creating DataContainer '{_ANF_DC_NAME}' backed by DiscoveryStorage...")
    _az_json([
        "az", "resource", "create",
        "--id", dc_id,
        "--subscription", subscription,
        "--location", location,
        "--api-version", "2025-07-01-preview",
        "--properties", json.dumps({
            "dataStore": {
                "kind": "DiscoveryStorage",
                "discoveryStorageId": storage_id,
            },
            "credentials": credentials,
        }),
        "-o", "json",
    ])
    info(f"DataContainer '{_ANF_DC_NAME}' created")
    return dc_id


def _ensure_anf_root_dataasset(subscription: str, resource_group: str, location: str, dc_id: str) -> str:
    """Ensure a DataAsset with path '.' exists under the ANF DataContainer.

    Returns the DataAsset resource ID.
    """
    da_id = f"{dc_id}/dataAssets/{_ANF_DA_NAME}"

    if _resource_exists(da_id, subscription):
        info(f"DataAsset '{_ANF_DA_NAME}' already exists")
        return da_id

    info(f"Creating DataAsset '{_ANF_DA_NAME}' with path '.'...")
    _az_json([
        "az", "resource", "create",
        "--id", da_id,
        "--subscription", subscription,
        "--location", location,
        "--api-version", "2025-07-01-preview",
        "--properties", json.dumps({
            "description": "Root of ANF scratch volume for cleanup operations",
            "path": ".",
        }),
        "-o", "json",
    ])
    info(f"DataAsset '{_ANF_DA_NAME}' created")
    return da_id


def _get_resource_location(resource_id: str, subscription: str) -> str:
    """Get the Azure location of a resource."""
    result = _get_resource(resource_id, subscription)
    return result["location"]


@app.command("cleanup-anf")
def cleanup_anf(
    age_days: int = typer.Option(
        _DEFAULT_AGE_DAYS,
        "--age-days",
        help="Show operations older than this many days (default: 7)",
    ),
    delete: bool = typer.Option(
        False,
        "--delete",
        help="Submit a cleanup tool run to delete stale ANF folders",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="With --delete: show the command that would run without submitting",
    ),
) -> None:
    """List stale operations whose ANF scratch folders can be cleaned up.

    Queries the operations API to find completed/failed/canceled operations
    older than --age-days (default 7). Each operation has an ANF scratch
    folder named by its tool run ID that persists after completion.

    Use --delete to submit a tool run that mounts the full ANF volume
    and removes stale operation folders.
    """
    debug("cleanup_anf(): entering")
    console = Console()

    env_cfg = load_project_config(get_config_file_path())
    emit_env(env_cfg)

    # ── Step 1: Collect all operations ───────────────────────────────────
    info("Fetching operations...")
    with console.status("Scanning operations..."):
        all_ops = _collect_all_operations(env_cfg.project_name, env_cfg.workspace_url)

    active_count = sum(1 for _, s, _, _ in all_ops if s in _ACTIVE_STATES)
    terminal_count = sum(1 for _, s, _, _ in all_ops if s in _TERMINAL_STATES)
    info(f"{active_count} active, {terminal_count} terminal operations")

    # ── Step 2: Identify stale operations ────────────────────────────────
    stale = _find_stale_operations(all_ops, age_days)
    if not stale:
        info(
            f"No stale operations found older than {age_days} days "
            f"(scanned {len(all_ops)} operations)."
        )
        return

    # ── Step 3: Display stale operations ─────────────────────────────────
    table = Table(title=f"Stale Operations ({len(stale)} found, older than {age_days} days)")
    table.add_column("Operation ID (ANF folder)", style="cyan", no_wrap=True)
    table.add_column("Status", style="green")
    table.add_column("Age (days)", style="yellow", justify="right")
    table.add_column("Created", style="magenta")
    table.add_column("Owner", style="bright_black")

    for op_id, status, created_at, age, created_by in stale:
        local_time = created_at.astimezone()
        table.add_row(
            op_id,
            status,
            f"{age:.1f}",
            local_time.strftime("%Y-%m-%d %H:%M"),
            created_by or "",
        )

    console.print(table)
    console.print()

    total_stale = len(stale)
    info(
        f"{total_stale} stale operation(s) with ANF folders that can be cleaned up. "
        f"Each operation's ANF data is stored under its operation ID on the ANF volume."
    )

    if not delete:
        return

    # ── Step 4: Ensure ANF-root DataContainer and DataAsset exist ────────
    if not env_cfg.storage_id:
        error("storage_id not configured. Run 'discovery configure' first.")
        raise typer.Exit(1)
    if not env_cfg.tool_id:
        error("tool_id not configured. Run 'discovery configure' first.")
        raise typer.Exit(1)
    if not env_cfg.nodepool_id:
        error("nodepool_id not configured. Run 'discovery configure' first.")
        raise typer.Exit(1)
    if not env_cfg.datacontainer_id:
        error("datacontainer_id not configured. Run 'discovery configure' first.")
        raise typer.Exit(1)

    subscription = env_cfg.subscription
    resource_group = env_cfg.resource_group

    with console.status("Ensuring ANF cleanup resources exist..."):
        location = _get_resource_location(env_cfg.storage_id, subscription)
        dc_id = _ensure_anf_datacontainer(
            subscription, resource_group, location,
            env_cfg.storage_id, env_cfg.datacontainer_id,
        )
        da_id = _ensure_anf_root_dataasset(subscription, resource_group, location, dc_id)

    # ── Step 5: Build and submit the cleanup tool run ────────────────────
    # Mount the full ANF volume as an output at /anf-scratch via the root DataAsset
    anf_root_uri = f"discovery://dataassets{da_id}"
    stale_ids = [op_id for op_id, *_ in stale]

    # Build rm command for all stale folders
    # Each operation creates folders at /{toolRunId}/anf_scratch on the volume
    rm_targets = " ".join(f"/anf-scratch/{op_id}" for op_id in stale_ids)
    cleanup_cmd = f"rm -rf {rm_targets}"

    console.print()
    console.print(f"[bold cyan]Cleanup command:[/bold cyan] {cleanup_cmd}")
    console.print(f"[bold cyan]ANF mount URI:[/bold cyan] {anf_root_uri}")
    console.print()

    if dry_run:
        info("Dry run — no job submitted.")
        return

    if not typer.confirm(f"Submit cleanup job to delete {total_stale} stale folder(s)?", default=False):
        info("Cancelled.")
        return

    payload = ToolRunRequest(
        toolId=env_cfg.tool_id,
        storageId=env_cfg.storage_id,
        command=cleanup_cmd,
        nodePoolIds=[env_cfg.nodepool_id],
        outputData=[
            DataMount(mountPath="/anf-scratch", uri=anf_root_uri),
        ],
    )

    info("Submitting cleanup tool run...")
    result = run_and_poll(
        env_cfg.project_name,
        payload,
        env_cfg.workspace_url,
        timeout_seconds=600,
    )
    if result.status == "Succeeded":
        info(f"Cleanup completed successfully. Removed {total_stale} stale folder(s).")
    else:
        error(f"Cleanup job finished with status: {result.status}")


__all__ = ["app", "cleanup_anf"]
