"""Interactive selection helpers split from CLI for reuse and to avoid circular imports."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from discovery.common.logging import debug, info
from discovery.poll.build_acr_task import get_acr_login_server, list_acr_names
from discovery.poll.models.api_version import ApiVersion

from .resources import (
    derive_workspace_id_from_project_id,
    fetch_workspace_url_from_resource_id,
    get_workspace_ids,
    list_all_nodepools_with_details,
    list_datacontainers,
    list_resources,
    list_storagecontainers,
    resolve_supercomputer_region,
    resolve_supercomputer_vnet,
)


if TYPE_CHECKING:  # pragma: no cover - type checking only
    from .models.config import EnvConfig


def _extract_short_name(resource_id: str) -> str:
    """Extract resource group and resource name from a full Azure resource ID.

    Azure resource IDs follow the pattern:
    /subscriptions/{sub}/resourceGroups/{rg}/providers/{provider}/{type}/{name}

    For nested resources like nodepools:
    .../providers/Microsoft.Discovery/supercomputers/{sc}/nodepools/{np}

    Returns: "{resource_group}/{resource_name}" or the original ID if parsing fails.
    """
    parts = resource_id.split("/")
    # Find resource group
    rg_name = ""
    for i, part in enumerate(parts):
        if part.lower() == "resourcegroups" and i + 1 < len(parts):
            rg_name = parts[i + 1]
            break

    # Get the resource name (last non-empty part)
    resource_name = parts[-1] if parts else resource_id

    # For nested resources, include parent/child (e.g., "supercomputer/nodepool")
    # Look for the provider section and get everything after it
    try:
        providers_idx = next(i for i, p in enumerate(parts) if p.lower() == "providers")
        # After providers: provider_name, resource_type, resource_name, [nested_type, nested_name...]
        resource_parts = parts[providers_idx + 1:]  # Everything after "providers"
        # Skip provider name (e.g., "Microsoft.Discovery")
        if len(resource_parts) >= 3:  # noqa: PLR2004
            # Take alternating parts starting from index 2 (the resource names)
            names = [resource_parts[i] for i in range(2, len(resource_parts), 2)]
            resource_name = "/".join(names) if names else resource_name
    except (StopIteration, IndexError):
        pass

    if rg_name:
        return f"{rg_name}/{resource_name}"
    return resource_name or resource_id


def select_acr_registry(env_cfg: EnvConfig) -> None:
    """Populate env_cfg.acr_name and acr_login_server via discovery + interactive fallback.

    Strategy:
    - Attempt to import helper functions from build_acr_task (no swallowing of unexpected errors).
    - If helpers unavailable, skip discovery and go straight to manual prompt.
    - Auto-select when exactly one registry found; otherwise,
      invoke interactive selector when present.
    - If still none chosen, prompt user.
    - After selection, resolves the login server via ``az acr show``.
    """
    chosen = _interactive_choice("Select ACR registry:", list_acr_names())
    env_cfg.acr_name = chosen
    env_cfg.acr_login_server = get_acr_login_server(chosen)


def _interactive_choice(title: str, options: list[str]) -> str:
    if len(options) == 0:
        typer.echo("No options available for selection.", err=True)
        raise typer.Exit(1)
    if len(options) == 1:
        # Show short name for auto-selected option
        short_name = _extract_short_name(options[0].split("\t")[-1] if "\t" in options[0] else options[0])
        info(f"Using sole discovered option: {short_name}")
        return options[0]

    # Create a rich table for the options
    console = Console()

    # Check if options have tab-delimited fields with resource IDs
    sample = options[0]
    has_tabs = "\t" in sample

    # Determine if we have meaningful resource info to show
    # Resource IDs start with "/" (Azure resource paths)
    has_resource_info = False
    if has_tabs:
        for opt in options:
            parts = opt.split("\t")
            if len(parts) > 1 and parts[-1].startswith("/"):
                has_resource_info = True
                break

    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("#", style="bold yellow", width=4, justify="right")
    table.add_column("Name", style="green")
    if has_resource_info:
        table.add_column("Resource Group / Resource", style="cyan")

    for i, opt in enumerate(options, start=1):
        if has_tabs:
            parts = opt.split("\t")
            name = parts[0]
            if has_resource_info:
                # Get the resource ID (last part) and extract short name
                resource_id = parts[-1] if len(parts) > 1 else parts[0]
                short_id = _extract_short_name(resource_id)
                table.add_row(str(i), name, short_id)
            else:
                # Show additional info if present (e.g., CPU/memory details)
                extra = parts[1] if len(parts) > 1 else ""
                display = f"{name}  [dim]{extra}[/dim]" if extra else name
                table.add_row(str(i), display)
        else:
            # Single value - extract short name from it
            short_name = _extract_short_name(opt)
            if has_resource_info:
                table.add_row(str(i), short_name, "")
            else:
                table.add_row(str(i), short_name)

    # Display in a panel
    panel = Panel(
        table,
        title=f"[bold]{title}[/bold]",
        border_style="blue",
        expand=False,
    )
    console.print(panel)

    while True:
        # Use typer.prompt for consistent CLI experience and built-in validation of type casting
        idx = typer.prompt("Enter number", type=int)
        if 1 <= idx <= len(options):
            return options[idx - 1]
        typer.echo(f"Invalid selection, enter a number between 1 and {len(options)}")


def select_related_resources(env_cfg: EnvConfig) -> None:
    """Populate nodepool and related resources on env_cfg.

    Expects env_cfg.workspace_resource_id to be set. Per-supercomputer scratch
    dataContainer selection (env_cfg.supercomputer_scratch_dcs) should typically
    be populated first via select_supercomputer_scratch_dcs() so the resulting
    NodepoolInfo objects carry correct scratch_dc_id values.

    Fetches all nodepools from ALL supercomputers in the workspace.
    Mutates env_cfg.nodepool_id and nodepools list.
    """
    # Fetch all nodepools from ALL supercomputers with their details
    info("Fetching nodepool details from all supercomputers...")
    nodepools = list_all_nodepools_with_details(env_cfg)
    env_cfg.nodepools = nodepools

    # Create selection options showing nodepool resources
    if not nodepools:
        typer.echo("No nodepools found in any supercomputer.", err=True)
        raise typer.Exit(1)

    # Build display options with resource info - always use qualified_name (supercomputer/pool)
    np_options = []
    for np in nodepools:
        # Always use qualified name (supercomputer/poolname) for clarity
        display_name = np.qualified_name
        # Format: "supercomputer/name\tCPUs: X, Memory: Y, GPUs: Z"
        resources = []
        if np.cpus:
            resources.append(f"CPUs: {np.cpus}")
        if np.memory:
            resources.append(f"Mem: {np.memory}")
        if np.gpus and np.gpus != "0":
            resources.append(f"GPUs: {np.gpus}")
        resource_str = ", ".join(resources) if resources else "No resource info"
        np_options.append(f"{display_name}\t{resource_str}\t{np.id}")

    choice = _interactive_choice("Select default nodepool", np_options)
    # Parse the selected nodepool ID (last tab-separated field)
    parts = choice.split("\t")
    selected_id = parts[-1] if parts else choice
    env_cfg.nodepool_id = selected_id


def _parse_name_id(choice: str) -> tuple[str, str]:
    """Parse a selection string that may be delimited by tab or whitespace.

    Returns (name, id). Raises ValueError if format unexpected.
    """
    parts = choice.split("\t", 1) if "\t" in choice else choice.strip().split()
    if len(parts) < 2:  # noqa: PLR2004
        msg = f"Unexpected choice format: {choice!r}"
        raise ValueError(msg)
    return parts[0], parts[1]


def resolve_project() -> str:
    """Interactively choose a project and return its id.

    list_resources returns entries like 'name\tid'. We present those directly to the user,
    then parse back the id.
    """
    rows = list_resources("Microsoft.Discovery/workspaces/projects", properties=("name", "id"))
    # Strip workspace prefix (workspace/project -> project) from displayed project names
    processed_rows: list[str] = []
    for r in rows:
        try:
            name, rid = r.split("\t", 1)
        except ValueError:
            processed_rows.append(r)
            continue
        if "/" in name:
            # Azure nested resource name pattern: "<workspace>/<project>"
            project_only = name.split("/", 1)[1] or name
            processed_rows.append(f"{project_only}\t{rid}")
        else:
            processed_rows.append(r)
    rows = processed_rows
    choice = _interactive_choice("Select project:", rows)
    _, pid = _parse_name_id(choice)
    return pid


def select_tool(env_cfg: EnvConfig) -> None:
    """Discover and select a tool id, mutating env_cfg.tool_id.

    If no tools are discovered or user aborts (blank input), tool_id remains
    empty string. Entries are expected to be 'name\tid'.
    """
    rows = list_resources("Microsoft.Discovery/tools", properties=("name", "id"))
    choice = _interactive_choice("Select tool:", rows)
    try:
        _, tool_id = _parse_name_id(choice)
    except ValueError:
        # Fallback: do not mutate if parsing fails
        return
    env_cfg.tool_id = tool_id


def select_api_version(env_cfg: EnvConfig) -> None:
    """Interactively select the Discovery data-plane API version.

    Persists the choice on ``env_cfg.api_version``. The currently configured value
    (or the latest known version, if unset) is highlighted as the default.
    """
    current = ApiVersion.parse(env_cfg.api_version)
    latest = ApiVersion.latest()

    options: list[str] = []
    for member in ApiVersion:
        labels: list[str] = []
        if member is latest:
            labels.append("latest")
        if member is current:
            labels.append("current")
        # Container kind hint mirrors README.md guidance.
        labels.append(
            "V1 / datacontainers" if member.uses_dataassets_uri else "V2 / storagecontainers"
        )
        options.append(f"{member.value}\t{', '.join(labels)}")

    choice = _interactive_choice("Select API version:", options)
    selected = choice.split("\t", 1)[0]
    env_cfg.api_version = selected
    info(f"API version set to: {selected}")


def _format_archive_options(containers: list[dict]) -> list[str]:
    """Build "name\tresource_id" options for blob-kind containers."""
    return [
        f"{c.get('name', '')}\t{c.get('id', '')}"
        for c in sorted(containers, key=lambda c: c.get("name", ""))
    ]


def select_datacontainer(env_cfg: EnvConfig) -> None:
    """V1 Archive picker: select (or create) a blob-kind ``Microsoft.Discovery/datacontainers``.

    Filters to ``dataStore.kind == AzureStorageBlob``; non-blob (ANF / Files)
    dataContainers are not surfaced — Scratch (``--scratch-select``) handles
    ANF wrappers. Offers ``+ Create new...`` at the top of the picker so the
    user can author a new blob dataContainer wrapping an existing storage
    account without leaving the CLI.
    """
    info("Listing data containers...")
    sub = env_cfg.subscription or _extract_subscription(env_cfg.workspace_resource_id)
    all_containers = list_datacontainers(subscription=sub)
    containers = [c for c in all_containers if c.get("kind") == "AzureStorageBlob"]

    if not containers:
        typer.echo(
            "  No blob-backed data containers found. You can create one now "
            "by wrapping an existing Microsoft.Storage/storageAccounts resource.",
            err=True,
        )

    options = ["+ Create new blob data container...\t__CREATE_NEW__"] + _format_archive_options(containers)
    choice = _interactive_choice("Select Archive (blob data container):", options)
    parts = choice.split("\t")
    selected_id = parts[-1] if parts else ""

    if selected_id == "__CREATE_NEW__":
        selected_id = _create_archive_dc_interactive(env_cfg)
        if not selected_id:
            msg = "Archive data container creation was cancelled or failed; required to continue."
            raise RuntimeError(msg)

    env_cfg.datacontainer_id = selected_id


def select_storagecontainer(env_cfg: EnvConfig) -> None:
    """V2 Archive picker: select (or create) a blob-kind ``Microsoft.Discovery/storagecontainers``.

    Filters to ``storageStore.kind == AzureStorageBlob``; ANF-kind storage
    containers are not surfaced — Scratch (``--scratch-select``) handles
    those. Offers ``+ Create new...`` at the top of the picker so the user
    can author a new blob storageContainer wrapping an existing storage
    account without leaving the CLI.
    """
    info("Listing storage containers...")
    sub = env_cfg.subscription or _extract_subscription(env_cfg.workspace_resource_id)
    all_containers = list_storagecontainers(subscription=sub)
    containers = [c for c in all_containers if c.get("kind") == "AzureStorageBlob"]

    if not containers:
        typer.echo(
            "  No blob-backed storage containers found. You can create one now "
            "by wrapping an existing Microsoft.Storage/storageAccounts resource.",
            err=True,
        )

    options = ["+ Create new blob storage container...\t__CREATE_NEW__"] + _format_archive_options(containers)
    choice = _interactive_choice("Select Archive (blob storage container):", options)
    parts = choice.split("\t")
    selected_id = parts[-1] if parts else ""

    if selected_id == "__CREATE_NEW__":
        selected_id = _create_archive_sc_interactive(env_cfg)
        if not selected_id:
            msg = "Archive storage container creation was cancelled or failed; required to continue."
            raise RuntimeError(msg)

    env_cfg.storagecontainer_id = selected_id


def _pick_storage_account(
    subscription: str, prompt_label: str, region: str = "",
) -> dict | None:
    """Interactive picker over Microsoft.Storage/storageAccounts in ``subscription``.

    When ``region`` is given, filters to same-region accounts only — Archive
    blob is typically co-located with the workspace to avoid egress, and
    listing every storage account in the sub creates picker noise.
    """
    from .resources import list_storage_accounts

    accounts = list_storage_accounts(subscription=subscription)
    if region:
        region_lc = region.lower()
        accounts = [a for a in accounts if (a.get("location", "") or "").lower() == region_lc]
    if not accounts:
        typer.echo(
            f"  No Microsoft.Storage/storageAccounts visible in the subscription"
            f"{f' (region {region})' if region else ''}. Create a storage account "
            f"first (portal/ARM/Bicep), then re-run.",
            err=True,
        )
        return None

    options = [
        f"{a['name']}  [{a.get('location', '?')}]  {a.get('resourceGroup', '?')}\t{a['id']}"
        for a in sorted(accounts, key=lambda a: a.get("name", ""))
    ]
    choice = _interactive_choice(prompt_label, options)
    sa_id = choice.split("\t")[-1]
    return next((a for a in accounts if a["id"] == sa_id), None)


def _resolve_workspace_uami(env_cfg: EnvConfig) -> str:
    """Return the workspace's workspaceIdentity.id for use as a credential UAMI.

    Returns ``""`` when not resolvable (caller should prompt the user).
    """
    if not env_cfg.workspace_resource_id:
        return ""
    cmd = [
        "az", "resource", "show",
        "--ids", env_cfg.workspace_resource_id,
        "--query", "properties.workspaceIdentity.id",
        "-o", "tsv",
    ]
    sub = env_cfg.subscription
    if sub:
        cmd.extend(["--subscription", sub])
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode == 0:
        return (res.stdout or "").strip()
    return ""


def _resolve_workspace_region(env_cfg: EnvConfig) -> str:
    """Return the workspace's ``location``, or '' when not resolvable."""
    if not env_cfg.workspace_resource_id:
        return ""
    cmd = [
        "az", "resource", "show",
        "--ids", env_cfg.workspace_resource_id,
        "--query", "location",
        "-o", "tsv",
    ]
    sub = env_cfg.subscription
    if sub:
        cmd.extend(["--subscription", sub])
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode == 0:
        return (res.stdout or "").strip()
    return ""


def _create_archive_dc_interactive(env_cfg: EnvConfig) -> str:
    """Interactively create a V1 blob-kind dataContainer.

    Picks an existing storage account, the workspace UAMI as credential,
    prompts for a name (defaulted from the account name), and deploys via
    ARM. Returns the new dataContainer's ARM ID, or "" on cancellation/failure.
    """
    from .deploy_datacontainer import deploy_blob_datacontainer
    from .models.dataasset import BlobDataContainerInputs
    from .resources import extract_resource_group

    sub = env_cfg.subscription or _extract_subscription(env_cfg.workspace_resource_id)
    if not sub:
        typer.echo("Cannot create dataContainer without a subscription context.", err=True)
        return ""

    ws_region = _resolve_workspace_region(env_cfg)
    chosen = _pick_storage_account(
        sub,
        f"Pick a storage account to wrap as Archive (region {ws_region or 'any'})",
        region=ws_region,
    )
    if not chosen:
        return ""

    uami_id = _resolve_workspace_uami(env_cfg)
    if not uami_id:
        uami_id = typer.prompt(
            "Could not auto-detect workspace UAMI. Enter a user-assigned identity "
            "resource ID with Storage Blob Data Contributor on the account",
        )
    if not uami_id:
        typer.echo("UAMI is required for V1 dataContainer credentials; aborting.", err=True)
        return ""

    sa_rg = chosen.get("resourceGroup", "") or extract_resource_group(chosen["id"])
    sa_location = chosen.get("location", "") or ""
    default_name = f"archive-dc-{chosen['name']}"
    dc_name = typer.prompt("New blob dataContainer name", default=default_name)

    try:
        result = deploy_blob_datacontainer(
            subscription_id=sub,
            resource_group=sa_rg,
            inputs=BlobDataContainerInputs(
                name=dc_name,
                location=sa_location,
                storage_account_id=chosen["id"],
                credential_identity_id=uami_id,
            ),
            execute=True,
            skip_if_exists=True,
        )
    except RuntimeError as e:
        typer.echo(f"Deployment failed: {e}", err=True)
        return ""

    if result.get("cancelled"):
        return ""

    new_id = (
        f"/subscriptions/{sub}/resourceGroups/{sa_rg}"
        f"/providers/Microsoft.Discovery/dataContainers/{dc_name}"
    )
    typer.echo(f"  Selected newly-created '{dc_name}'.")
    return new_id


def _create_archive_sc_interactive(env_cfg: EnvConfig) -> str:
    """Interactively create a V2 blob-kind storageContainer.

    Picks an existing storage account, prompts for a name, and deploys via
    ARM. V2 storageContainers don't carry credentials. Returns the new
    storageContainer's ARM ID, or "" on cancellation/failure.
    """
    from .deploy_storagecontainer import deploy_blob_storagecontainer
    from .models.dataasset import BlobStorageContainerInputs
    from .resources import extract_resource_group

    sub = env_cfg.subscription or _extract_subscription(env_cfg.workspace_resource_id)
    if not sub:
        typer.echo("Cannot create storageContainer without a subscription context.", err=True)
        return ""

    ws_region = _resolve_workspace_region(env_cfg)
    chosen = _pick_storage_account(
        sub,
        f"Pick a storage account to wrap as Archive (region {ws_region or 'any'})",
        region=ws_region,
    )
    if not chosen:
        return ""

    sa_rg = chosen.get("resourceGroup", "") or extract_resource_group(chosen["id"])
    sa_location = chosen.get("location", "") or ""
    default_name = f"archive-sc-{chosen['name']}"
    sc_name = typer.prompt("New blob storageContainer name", default=default_name)

    try:
        result = deploy_blob_storagecontainer(
            subscription_id=sub,
            resource_group=sa_rg,
            inputs=BlobStorageContainerInputs(
                name=sc_name,
                location=sa_location,
                storage_account_id=chosen["id"],
            ),
            execute=True,
            skip_if_exists=True,
        )
    except RuntimeError as e:
        typer.echo(f"Deployment failed: {e}", err=True)
        return ""

    if result.get("cancelled"):
        return ""

    new_id = (
        f"/subscriptions/{sub}/resourceGroups/{sa_rg}"
        f"/providers/Microsoft.Discovery/storageContainers/{sc_name}"
    )
    typer.echo(f"  Selected newly-created '{sc_name}'.")
    return new_id


def select_archive(env_cfg: EnvConfig) -> None:
    """Mandatory Archive picker: blob-backed wrapper for tool-run I/O persistence.

    Dispatches to the V1 datacontainer or V2 storagecontainer picker by API
    version. Both flows filter to blob-kind containers — Scratch (ANF) is a
    separate concept handled by ``--scratch-select``.
    """
    if ApiVersion.parse(env_cfg.api_version).uses_dataassets_uri:
        select_datacontainer(env_cfg)
    else:
        select_storagecontainer(env_cfg)


def select_project_and_related(env_cfg: EnvConfig) -> None:
    """Resolve project, derive workspace, and select related resources, mutating env_cfg.

    Populates the fields on EnvConfig in-place:
      project_id, project_name, workspace_resource_id, workspace_url,
      supercomputer_scratch_dcs (when API version uses storageId on the wire),
      nodepool_id, nodepools (from all supercomputers).
    Leaves existing values if selection fails (e.g., no projects discovered).
    """
    pid = resolve_project()
    # Set project id
    env_cfg.project_id = pid
    # Derive workspace id from fully-qualified project id if available
    derive_workspace_id_from_project_id(pid, env_cfg)
    get_workspace_ids(env_cfg.workspace_resource_id, "workspaceApiUri")
    fetch_workspace_url_from_resource_id(env_cfg.workspace_resource_id, env_cfg)
    # Scratch dataContainer selection runs before nodepool discovery so the
    # resulting NodepoolInfo objects carry correct per-supercomputer
    # scratch_dc_id values.
    select_supercomputer_scratch(env_cfg)
    select_related_resources(env_cfg)


def _extract_subscription(resource_id: str) -> str:
    """Extract the subscription ID from a full Azure resource ID."""
    parts = resource_id.split("/")
    for i, p in enumerate(parts):
        if p.lower() == "subscriptions" and i + 1 < len(parts):
            return parts[i + 1]
    return ""


def _pick_scratch_resource(
    sc_name: str,
    sc_vnet_id: str,
    sc_region: str,
    candidates: list[dict],
    *,
    label: str,
    create_callback,
) -> str:
    """Generic scratch-resource picker shared by V1 and V2 flows.

    Hard-filters candidates to those whose wrapped ANF lives on the same
    VNet as the supercomputer. Same-VNet is a stricter requirement than
    same-region: ANF must be reachable over a private endpoint on the
    supercomputer's own network, so wrappers around volumes on a different
    VNet (even in the same region) are not mountable.

    When the supercomputer's VNet cannot be determined at all, refuses to
    pick — the safer default than offering a guess.

    Args:
        sc_name: Display name of the supercomputer being mapped.
        sc_vnet_id: Resolved VNet resource ID for the supercomputer.
        sc_region: Display-only region label for the picker title.
        candidates: ``[{"name", "id", "vnet", "region"}, ...]``.
        label: User-visible name for the resource type ("dataContainer" or
            "storageContainer"), used in prompts/messages.
        create_callback: Zero-arg callable invoked when the user picks
            "+ Create new...". Returns the new resource's ARM ID, or "" on
            cancel.

    Returns:
        The selected/created resource's ARM ID, or "" if the user skipped.
    """
    if not sc_vnet_id:
        typer.echo(
            f"  ⚠️  Could not determine the VNet of {sc_name}; cannot safely "
            f"pick a Scratch {label}. Skipping {sc_name}.",
            err=True,
        )
        return ""

    sc_vnet_lc = sc_vnet_id.lower()
    sc_vnet_name = sc_vnet_id.rstrip("/").split("/")[-1]
    same_vnet = [c for c in candidates if (c.get("vnet", "") or "").lower() == sc_vnet_lc]

    def _fmt(c: dict) -> str:
        loc = c.get("region", "?") or "?"
        return f"{c['name']}  [ANF {loc}]\t{c['id']}"

    create_label = f"+ Create new Scratch {label}...\t__CREATE_NEW__"
    skip_label = f"Skip {sc_name} (no Scratch /scratch mount)\t__SKIP__"

    if not same_vnet:
        typer.echo(
            f"  No Scratch {label}s on VNet '{sc_vnet_name}' visible for {sc_name}. "
            f"ANF must live on the supercomputer's VNet to be mountable, so "
            f"wrappers around volumes on a different VNet aren't usable.",
            err=True,
        )

    options: list[str] = [create_label, skip_label] + [_fmt(c) for c in same_vnet]

    region_label = f"region {sc_region}, " if sc_region else ""
    title = (
        f"Searching for Scratch {label}s on {region_label}VNet {sc_vnet_name} — "
        f"pick one for {sc_name}"
    )
    choice = _interactive_choice(title, options)
    parts = choice.split("\t")
    selected_id = parts[-1] if parts else ""

    if selected_id == "__SKIP__":
        typer.echo(
            f"  Skipped Scratch for {sc_name} — jobs on this supercomputer "
            f"won't be able to mount /scratch via 'discovery start --scratch'.",
        )
        return ""

    if selected_id == "__CREATE_NEW__":
        return create_callback()

    return selected_id


def select_scratch_dc_for_supercomputer(
    sc_id: str,  # noqa: ARG001 - kept for caller convenience / future logging
    sc_name: str,
    sc_vnet_id: str,
    sc_region: str,
    candidates: list[dict],
    env_cfg: EnvConfig,
    subscription: str = "",
) -> str:
    """V1 picker for a DiscoveryStorage-kind dataContainer per supercomputer.

    ``candidates`` items must have keys ``name``, ``id``, ``anf_vnet`` and
    ``anf_region`` (the wrapped ANF's VNet and region). Internally
    normalised to ``vnet``/``region`` for the shared picker.
    """
    norm = [
        {
            "name": c["name"], "id": c["id"],
            "vnet": c.get("anf_vnet", ""),
            "region": c.get("anf_region", ""),
        }
        for c in candidates
    ]
    return _pick_scratch_resource(
        sc_name, sc_vnet_id, sc_region, norm,
        label="dataContainer",
        create_callback=lambda: _create_scratch_dc_interactive(
            sc_name, sc_vnet_id, sc_region, subscription, env_cfg,
        ),
    )


def select_scratch_sc_for_supercomputer(
    sc_id: str,  # noqa: ARG001 - kept for caller convenience / future logging
    sc_name: str,
    sc_vnet_id: str,
    sc_region: str,
    candidates: list[dict],
    env_cfg: EnvConfig,
    subscription: str = "",
) -> str:
    """V2 picker for an AzureNetAppFiles-kind storageContainer per supercomputer.

    ``candidates`` items must have keys ``name``, ``id``, ``volume_vnet`` and
    ``volume_region`` (the wrapped ANF volume's VNet and region).
    """
    norm = [
        {
            "name": c["name"], "id": c["id"],
            "vnet": c.get("volume_vnet", ""),
            "region": c.get("volume_region", ""),
        }
        for c in candidates
    ]
    return _pick_scratch_resource(
        sc_name, sc_vnet_id, sc_region, norm,
        label="storageContainer",
        create_callback=lambda: _create_scratch_sc_interactive(
            sc_name, sc_vnet_id, sc_region, subscription, env_cfg,
        ),
    )


def _create_scratch_dc_interactive(
    sc_name: str, sc_vnet_id: str, sc_region: str, subscription: str, env_cfg: EnvConfig,
) -> str:
    """Interactively author a DiscoveryStorage-kind dataContainer wrapping an existing ANF.

    Lists ``Microsoft.Discovery/storages`` filtered to ANFs whose own
    ``properties.subnetId`` lives on the same VNet as the supercomputer
    (mountability requirement). Returns the new dataContainer's ARM ID, or
    "" on cancellation/failure.
    """
    from .deploy_datacontainer import deploy_datacontainer
    from .models.dataasset import DataContainerInputs
    from .resources import extract_resource_group, extract_vnet_id, list_storages

    if not sc_vnet_id:
        typer.echo(
            "  Cannot create Scratch dataContainer without a known supercomputer VNet.",
            err=True,
        )
        return ""

    try:
        anfs = list_storages(subscription=subscription)
    except Exception as e:
        typer.echo(f"Could not list ANF storages: {e}", err=True)
        return ""
    if not anfs:
        typer.echo(
            "  No Microsoft.Discovery/storages (ANF) resources visible in the "
            "subscription. Pre-create one on the supercomputer's VNet "
            "(portal/ARM/Bicep), then re-run 'discovery configure --scratch-select'.",
            err=True,
        )
        return ""

    sc_vnet_lc = sc_vnet_id.lower()
    sc_vnet_name = sc_vnet_id.rstrip("/").split("/")[-1]

    # Enrich each candidate ANF with its VNet (derived from properties.subnetId)
    # so we can hard-filter to same-VNet — region match alone is insufficient.
    same_vnet: list[dict] = []
    for s in anfs:
        cmd = [
            "az", "resource", "show", "--ids", s["id"],
            "--query", "properties.subnetId", "-o", "tsv",
        ]
        if subscription:
            cmd.extend(["--subscription", subscription])
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        anf_vnet = ""
        if res.returncode == 0:
            anf_vnet = extract_vnet_id((res.stdout or "").strip())
        if anf_vnet and anf_vnet.lower() == sc_vnet_lc:
            same_vnet.append({**s, "vnet": anf_vnet})

    if not same_vnet:
        typer.echo(
            f"  No Microsoft.Discovery/storages (ANF) resources on VNet "
            f"'{sc_vnet_name}' visible. ANF must be reachable from the "
            f"supercomputer's VNet; pre-create one on '{sc_vnet_name}' "
            f"(portal/ARM/Bicep), then re-run 'discovery configure --scratch-select'.",
            err=True,
        )
        return ""

    anf_options = [
        f"{s['name']}  [{s.get('location', '?')}]\t{s['id']}"
        for s in same_vnet
    ]
    anf_choice = _interactive_choice(
        f"Pick the ANF storage to wrap for {sc_name} (VNet {sc_vnet_name})",
        anf_options,
    )
    anf_id = anf_choice.split("\t")[-1]
    chosen_anf = next((s for s in same_vnet if s["id"] == anf_id), None)
    if chosen_anf is None:
        typer.echo("ANF selection failed; aborting create.", err=True)
        return ""

    anf_region = chosen_anf.get("location", "") or sc_region
    # Always deploy the wrapper into the workspace's resource group rather
    # than the wrapped ANF's RG — the ANF may live in a Discovery-managed
    # RG (e.g. mrg-*) we shouldn't touch, and grouping all Discovery
    # wrappers in the workspace RG matches the existing convention.
    workspace_rg = env_cfg.resource_group or extract_resource_group(anf_id)

    # V1 dataContainers always need a credentials block, even for
    # DiscoveryStorage kind. Use the workspace's UAMI (the same identity
    # the workspace itself runs under) so the new dataContainer inherits
    # the same access scope as everything else in the workspace.
    uami_id = _resolve_workspace_uami(env_cfg)
    if not uami_id:
        uami_id = typer.prompt(
            "Could not auto-detect workspace UAMI. Enter a user-assigned identity "
            "resource ID Discovery should use to access the wrapped ANF",
        )
    if not uami_id:
        typer.echo(
            "  UAMI is required for V1 dataContainer credentials; aborting.",
            err=True,
        )
        return ""

    default_name = f"scratch-dc-{chosen_anf['name']}"
    dc_name = typer.prompt("New scratch dataContainer name", default=default_name)

    try:
        result = deploy_datacontainer(
            subscription_id=subscription,
            resource_group=workspace_rg,
            inputs=DataContainerInputs(
                name=dc_name,
                location=anf_region,
                discovery_storage_id=anf_id,
                credential_identity_id=uami_id,
            ),
            execute=True,
            skip_if_exists=True,
        )
    except RuntimeError as e:
        typer.echo(f"Deployment failed: {e}", err=True)
        return ""

    if result.get("cancelled"):
        return ""

    new_id = (
        f"/subscriptions/{subscription}/resourceGroups/{workspace_rg}"
        f"/providers/Microsoft.Discovery/dataContainers/{dc_name}"
    )
    typer.echo(f"  Selected newly-created '{dc_name}' for {sc_name}.")
    return new_id


def _resolve_scratch_dc_candidates(subscription: str) -> list[dict]:
    """Build the list of DiscoveryStorage-kind dataContainers + their ANF regions.

    Returns ``[{"name","id","anf_id","anf_region"}, ...]``. Resolves each
    candidate's wrapped ANF (``properties.dataStore.discoveryStorageId``) and
    looks up that resource's location, since the dataContainer's own
    ``location`` is unrelated to the underlying ANF region.
    """
    from .resources import (
        extract_vnet_id,
        get_datacontainer_datastore,
        list_datacontainers,
    )

    try:
        all_dcs = list_datacontainers(subscription=subscription)
    except Exception as e:
        typer.echo(f"Could not list dataContainers: {e}", err=True)
        return []

    candidates: list[dict] = []
    for dc in all_dcs:
        if (dc.get("kind") or "") != "DiscoveryStorage":
            continue
        anf_id = ""
        anf_region = ""
        anf_vnet = ""
        try:
            store = get_datacontainer_datastore(dc["id"])
            anf_id = store.get("discoveryStorageId", "") or ""
        except Exception as e:
            debug(f"could not read dataStore for {dc.get('name')}: {e}")
        if anf_id:
            # Fetch the wrapped ANF's location AND subnetId in one call.
            cmd = [
                "az", "resource", "show", "--ids", anf_id,
                "--query", "{loc:location, subnetId:properties.subnetId}",
                "-o", "json",
            ]
            if subscription:
                cmd.extend(["--subscription", subscription])
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout.strip():
                try:
                    payload = json.loads(res.stdout)
                except json.JSONDecodeError:
                    payload = {}
                anf_region = (payload.get("loc") or "").strip()
                anf_vnet = extract_vnet_id((payload.get("subnetId") or "").strip())
        candidates.append({
            "name": dc.get("name", ""),
            "id": dc.get("id", ""),
            "anf_id": anf_id,
            "anf_region": anf_region,
            "anf_vnet": anf_vnet,
        })
    return candidates


def _create_scratch_sc_interactive(
    sc_name: str, sc_vnet_id: str, sc_region: str, subscription: str, env_cfg: EnvConfig,
) -> str:
    """Interactively author an AzureNetAppFiles-kind storageContainer wrapping an existing ANF volume.

    Lists ``Microsoft.NetApp/.../volumes`` filtered to those whose own
    ``properties.subnetId`` lives on the same VNet as the supercomputer
    (mountability requirement). Returns the new storageContainer's ARM ID,
    or "" on cancellation/failure.
    """
    from .deploy_storagecontainer import deploy_storagecontainer
    from .models.dataasset import StorageContainerInputs
    from .resources import extract_resource_group, extract_vnet_id, list_anf_volumes

    if not sc_vnet_id:
        typer.echo(
            "  Cannot create Scratch storageContainer without a known supercomputer VNet.",
            err=True,
        )
        return ""

    try:
        volumes = list_anf_volumes(subscription=subscription)
    except Exception as e:
        typer.echo(f"Could not list ANF volumes: {e}", err=True)
        return ""
    if not volumes:
        typer.echo(
            "  No Microsoft.NetApp/netAppAccounts/capacityPools/volumes resources visible. "
            "Pre-create one on the supercomputer's VNet (portal/ARM/Bicep), then "
            "re-run 'discovery configure --scratch-select'.",
            err=True,
        )
        return ""

    sc_vnet_lc = sc_vnet_id.lower()
    sc_vnet_name = sc_vnet_id.rstrip("/").split("/")[-1]

    same_vnet: list[dict] = []
    for v in volumes:
        cmd = [
            "az", "resource", "show", "--ids", v["id"],
            "--query", "properties.subnetId", "-o", "tsv",
        ]
        if subscription:
            cmd.extend(["--subscription", subscription])
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        vol_vnet = ""
        if res.returncode == 0:
            vol_vnet = extract_vnet_id((res.stdout or "").strip())
        if vol_vnet and vol_vnet.lower() == sc_vnet_lc:
            same_vnet.append({**v, "vnet": vol_vnet})

    if not same_vnet:
        typer.echo(
            f"  No Microsoft.NetApp/.../volumes resources on VNet "
            f"'{sc_vnet_name}' visible. ANF must be reachable from the "
            f"supercomputer's VNet; pre-create one on '{sc_vnet_name}' "
            f"(portal/ARM/Bicep), then re-run 'discovery configure --scratch-select'.",
            err=True,
        )
        return ""

    vol_options = [
        f"{v['name']}  [{v.get('location', '?')}]\t{v['id']}"
        for v in same_vnet
    ]
    vol_choice = _interactive_choice(
        f"Pick the ANF volume to wrap for {sc_name} (VNet {sc_vnet_name})",
        vol_options,
    )
    vol_id = vol_choice.split("\t")[-1]
    chosen = next((v for v in same_vnet if v["id"] == vol_id), None)
    if chosen is None:
        typer.echo("ANF volume selection failed; aborting create.", err=True)
        return ""

    vol_region = chosen.get("location", "") or sc_region or ""
    # Same convention as V1: deploy the wrapper to the workspace's RG, not
    # the volume's RG (which may be a Discovery-managed mrg-* RG).
    workspace_rg = env_cfg.resource_group or extract_resource_group(vol_id)
    short_vol_name = chosen["name"].split("/")[-1] if "/" in chosen["name"] else chosen["name"]
    default_name = f"scratch-sc-{short_vol_name}"
    sc_container_name = typer.prompt("New scratch storageContainer name", default=default_name)

    try:
        result = deploy_storagecontainer(
            subscription_id=subscription,
            resource_group=workspace_rg,
            inputs=StorageContainerInputs(
                name=sc_container_name,
                location=vol_region,
                netapp_volume_id=vol_id,
            ),
            execute=True,
            skip_if_exists=True,
        )
    except RuntimeError as e:
        typer.echo(f"Deployment failed: {e}", err=True)
        return ""

    if result.get("cancelled"):
        return ""

    new_id = (
        f"/subscriptions/{subscription}/resourceGroups/{workspace_rg}"
        f"/providers/Microsoft.Discovery/storageContainers/{sc_container_name}"
    )
    typer.echo(f"  Selected newly-created '{sc_container_name}' for {sc_name}.")
    return new_id


def _resolve_scratch_sc_candidates(subscription: str) -> list[dict]:
    """Build the list of AzureNetAppFiles-kind storageContainers + their volume vnets.

    Returns ``[{"name","id","volume_id","volume_region","volume_vnet"}, ...]``.
    Resolves each candidate's wrapped ANF volume
    (``properties.storageStore.netAppVolumeId``) and reads its location AND
    subnetId so the picker can vnet-match against the supercomputer's VNet.
    """
    from .resources import (
        extract_vnet_id,
        get_storagecontainer_storagestore,
        list_storagecontainers,
    )

    try:
        all_scs = list_storagecontainers(subscription=subscription)
    except Exception as e:
        typer.echo(f"Could not list storageContainers: {e}", err=True)
        return []

    candidates: list[dict] = []
    for sc in all_scs:
        if (sc.get("kind") or "") != "AzureNetAppFiles":
            continue
        vol_id = ""
        vol_region = ""
        vol_vnet = ""
        try:
            store = get_storagecontainer_storagestore(sc["id"])
            vol_id = store.get("netAppVolumeId", "") or ""
        except Exception as e:
            debug(f"could not read storageStore for {sc.get('name')}: {e}")
        if vol_id:
            cmd = [
                "az", "resource", "show", "--ids", vol_id,
                "--query", "{loc:location, subnetId:properties.subnetId}",
                "-o", "json",
            ]
            if subscription:
                cmd.extend(["--subscription", subscription])
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout.strip():
                try:
                    payload = json.loads(res.stdout)
                except json.JSONDecodeError:
                    payload = {}
                vol_region = (payload.get("loc") or "").strip()
                vol_vnet = extract_vnet_id((payload.get("subnetId") or "").strip())
        candidates.append({
            "name": sc.get("name", ""),
            "id": sc.get("id", ""),
            "volume_id": vol_id,
            "volume_region": vol_region,
            "volume_vnet": vol_vnet,
        })
    return candidates


def select_supercomputer_scratch_dcs(env_cfg: EnvConfig, force: bool = False) -> None:
    """V1: build env_cfg.supercomputer_scratch_dcs (one DiscoveryStorage dataContainer per SC).

    Validates pre-existing mappings against the live dataContainer list and
    re-prompts for stale entries.

    Args:
        env_cfg: Active configuration. Must have ``workspace_resource_id`` set.
        force: When True, re-prompt for every supercomputer regardless of any
            existing mapping. Used by ``configure --scratch-select``.
    """
    if not env_cfg.workspace_resource_id:
        typer.echo("Workspace not configured. Skipping scratch dataContainer selection.", err=True)
        return

    sub = env_cfg.subscription or _extract_subscription(env_cfg.workspace_resource_id)

    try:
        sc_ids = get_workspace_ids(env_cfg.workspace_resource_id, "supercomputerIds")
    except Exception as e:
        typer.echo(f"Could not list supercomputers: {e}", err=True)
        return
    if not sc_ids:
        info("No supercomputers in workspace; nothing to map.")
        env_cfg.supercomputer_scratch_dcs = {}
        return

    candidates = _resolve_scratch_dc_candidates(sub)
    valid_ids = {c["id"].lower() for c in candidates}

    mapping: dict[str, str] = dict(env_cfg.supercomputer_scratch_dcs or {})

    # Drop stale entries
    if not force:
        for sc_id, dc_id in list(mapping.items()):
            if dc_id and dc_id.lower() not in valid_ids:
                typer.echo(
                    f"  Scratch dataContainer previously mapped for {sc_id.split('/')[-1]} "
                    f"({dc_id.split('/')[-1]}) no longer exists; will re-prompt."
                )
                mapping.pop(sc_id, None)

    info(f"Mapping scratch dataContainer for {len(sc_ids)} supercomputer(s)...")
    for sc_id in sc_ids:
        if not force and mapping.get(sc_id):
            continue
        sc_name = sc_id.rstrip("/").split("/")[-1]
        sc_vnet = resolve_supercomputer_vnet(sc_id, subscription=sub)
        sc_region, _ = resolve_supercomputer_region(sc_id, subscription=sub)
        chosen = select_scratch_dc_for_supercomputer(
            sc_id, sc_name, sc_vnet, sc_region, candidates,
            env_cfg=env_cfg, subscription=sub,
        )
        if chosen:
            mapping[sc_id] = chosen
            # If the user just created a new dataContainer, the candidates
            # list won't see it next iteration; refresh so subsequent SC
            # prompts can re-use it.
            if not any(c["id"] == chosen for c in candidates):
                candidates = _resolve_scratch_dc_candidates(sub)
        else:
            # Skip / cancel — drop any stale prior mapping for this SC so
            # ensure_scratch_assets and submit-time logic don't reuse it.
            mapping.pop(sc_id, None)

    env_cfg.supercomputer_scratch_dcs = mapping


def select_supercomputer_scratch_scs(env_cfg: EnvConfig, force: bool = False) -> None:
    """V2: build env_cfg.supercomputer_scratch_scs (one ANF storageContainer per SC)."""
    if not env_cfg.workspace_resource_id:
        typer.echo("Workspace not configured. Skipping scratch storageContainer selection.", err=True)
        return

    sub = env_cfg.subscription or _extract_subscription(env_cfg.workspace_resource_id)

    try:
        sc_ids = get_workspace_ids(env_cfg.workspace_resource_id, "supercomputerIds")
    except Exception as e:
        typer.echo(f"Could not list supercomputers: {e}", err=True)
        return
    if not sc_ids:
        info("No supercomputers in workspace; nothing to map.")
        env_cfg.supercomputer_scratch_scs = {}
        return

    candidates = _resolve_scratch_sc_candidates(sub)
    valid_ids = {c["id"].lower() for c in candidates}

    mapping: dict[str, str] = dict(env_cfg.supercomputer_scratch_scs or {})

    if not force:
        for sc_id, sc_container_id in list(mapping.items()):
            if sc_container_id and sc_container_id.lower() not in valid_ids:
                typer.echo(
                    f"  Scratch storageContainer previously mapped for {sc_id.split('/')[-1]} "
                    f"({sc_container_id.split('/')[-1]}) no longer exists; will re-prompt."
                )
                mapping.pop(sc_id, None)

    info(f"Mapping scratch storageContainer for {len(sc_ids)} supercomputer(s)...")
    for sc_id in sc_ids:
        if not force and mapping.get(sc_id):
            continue
        sc_name = sc_id.rstrip("/").split("/")[-1]
        sc_vnet = resolve_supercomputer_vnet(sc_id, subscription=sub)
        sc_region, _ = resolve_supercomputer_region(sc_id, subscription=sub)
        chosen = select_scratch_sc_for_supercomputer(
            sc_id, sc_name, sc_vnet, sc_region, candidates,
            env_cfg=env_cfg, subscription=sub,
        )
        if chosen:
            mapping[sc_id] = chosen
            if not any(c["id"] == chosen for c in candidates):
                candidates = _resolve_scratch_sc_candidates(sub)
        else:
            mapping.pop(sc_id, None)

    env_cfg.supercomputer_scratch_scs = mapping


def select_supercomputer_scratch(env_cfg: EnvConfig, force: bool = False) -> None:
    """Dispatch to the V1 or V2 scratch picker based on the active API version.

    Both flows let the user pick (or create on the fly) one ANF wrapper per
    supercomputer in the workspace; the resulting URI scheme used at submit
    time differs (V1 dataasset vs V2 storageasset) but the user experience
    is identical.
    """
    if ApiVersion.parse(env_cfg.api_version).uses_dataassets_uri:
        select_supercomputer_scratch_dcs(env_cfg, force=force)
    else:
        select_supercomputer_scratch_scs(env_cfg, force=force)


def select_nodepool(env_cfg: EnvConfig) -> None:
    """Select a nodepool from all available supercomputers.

    Expects env_cfg.workspace_resource_id to be set.
    Mutates env_cfg.nodepool_id and nodepools list with the selected nodepool.
    """
    try:
        if not env_cfg.workspace_resource_id:
            typer.echo("Workspace not configured. Please configure resources first.", err=True)
            return

        # Fetch all nodepools from all supercomputers with their details
        info("Fetching nodepool details from all supercomputers...")
        nodepools = list_all_nodepools_with_details(env_cfg)
        env_cfg.nodepools = nodepools

        if not nodepools:
            typer.echo("No nodepools found in any supercomputer.", err=True)
            return

        # Build display options with resource info - always use qualified name (supercomputer/pool)
        np_options = []
        for np in nodepools:
            # Always use qualified name (supercomputer/poolname) for clarity
            display_name = np.qualified_name
            resources = []
            if np.cpus:
                resources.append(f"CPUs: {np.cpus}")
            if np.memory:
                resources.append(f"Mem: {np.memory}")
            if np.gpus and np.gpus != "0":
                resources.append(f"GPUs: {np.gpus}")
            resource_str = ", ".join(resources) if resources else "No resource info"
            np_options.append(f"{display_name}\t{resource_str}\t{np.id}")

        choice = _interactive_choice("Select default nodepool", np_options)
        # Parse the selected nodepool ID (last tab-separated field)
        parts = choice.split("\t")
        selected_id = parts[-1] if parts else choice
        env_cfg.nodepool_id = selected_id

        info(f"Nodepool configured: {env_cfg.nodepool_id}")
    except RuntimeError as e:
        typer.echo(f"Nodepool configuration failed: {e}", err=True)


__all__ = [
    "resolve_project",
    "select_acr_registry",
    "select_api_version",
    "select_archive",
    "select_datacontainer",
    "select_nodepool",
    "select_project_and_related",
    "select_related_resources",
    "select_scratch_dc_for_supercomputer",
    "select_scratch_sc_for_supercomputer",
    "select_storagecontainer",
    "select_supercomputer_scratch",
    "select_supercomputer_scratch_dcs",
    "select_supercomputer_scratch_scs",
    "select_tool",
]
