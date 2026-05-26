"""Configure CLI command."""

from __future__ import annotations

import shutil

import typer

from discovery.common.logging import debug, error, info
from discovery.poll.models.api_version import ApiVersion
from discovery.poll.models.config import EnvConfig

from .az_extensions import ensure_required_extensions
from .azcli import run_az
from .cli_helpers import emit_env, get_config_file_path
from .selection import (
    select_acr_registry,
    select_api_version,
    select_archive,
    select_nodepool,
    select_project_and_related,
    select_supercomputer_scratch,
    select_tool,
)


app = typer.Typer()


@app.command()
def configure(
    only_acr: bool = typer.Option(False, "--acr", help="Only configure ACR registry"),
    only_tool: bool = typer.Option(False, "--tool", help="Only configure tool"),
    only_archive_select: bool = typer.Option(
        False,
        "--archive-select",
        help=(
            "Only (re)configure the Archive blob container used for tool-run input/output "
            "data persistence. Mandatory for full configure. Dispatches by API version: "
            "V1 picks a Microsoft.Discovery/datacontainers (kind=AzureStorageBlob); "
            "V2 picks a Microsoft.Discovery/storagecontainers (kind=AzureStorageBlob)."
        ),
    ),
    only_nodepool: bool = typer.Option(False, "--nodepool", help="Only configure nodepool"),
    only_scratch_select: bool = typer.Option(
        False,
        "--scratch-select",
        help=(
            "Only (re)configure per-supercomputer Scratch ANF wrapper (optional). "
            "V1 picks/creates a DiscoveryStorage-kind dataContainer; V2 picks/creates "
            "an AzureNetAppFiles-kind storageContainer. Used by 'discovery start --scratch'."
        ),
    ),
    only_api_version: bool = typer.Option(
        False,
        "--api-version-select",
        help="Only configure API version (interactive picker)",
    ),
    api_version: str = typer.Option(
        None,
        "--api-version",
        help="API version to use for data plane calls (e.g. 2026-02-01-preview). Saved to config. Skips the interactive picker when provided.",
    ),
) -> None:
    """Interactively select related resources and tool, and optionally persist to env file.

    Configures two distinct storage concepts:

    * **Archive** (mandatory): blob-backed container for tool-run input/output
      data persistence. Pick with ``--archive-select``; auto-prompted during
      full configure.
    * **Scratch** (optional, per-supercomputer): ANF-backed wrapper providing
      ephemeral working storage at ``/scratch`` when jobs are submitted with
      ``discovery start --scratch``. Pick with ``--scratch-select``.

    Other steps: ``--acr``, ``--tool``, ``--nodepool``, ``--api-version-select``.
    """
    debug("configure(): entering")

    # Check for required CLI tools
    if not shutil.which("az"):
        error("Azure CLI ('az') is not installed. Please install it to continue.")
        raise typer.Exit(code=1)

    # Check login status. We use ``run_az`` (instead of bare
    # ``subprocess.run``) so the call cannot block on a hidden interactive
    # prompt — see :func:`discovery.poll.azcli.run_az`.
    login_check = run_az(["az", "account", "show"])
    if login_check.returncode != 0:
        error("Azure CLI is not logged in. Please run 'az login' to continue.")
        raise typer.Exit(code=1)

    # Ensure required az extensions are installed. Several Discovery
    # commands rely on `az graph query` (provided by `resource-graph`); if
    # the extension is missing, the underlying invocation would otherwise
    # block on a hidden install prompt and appear to freeze. We install
    # eagerly here so subsequent steps can assume the extensions are
    # present.
    ext_results = ensure_required_extensions()
    for r in ext_results:
        if r.action == "installed":
            info(f"Installed required az extension: {r.name}")
        elif r.action == "already-installed":
            debug(f"az extension already installed: {r.name}")
    failed = [r for r in ext_results if not r.ok]
    if failed:
        for r in failed:
            error(
                f"Failed to install required az extension '{r.name}': {r.detail}. "
                f"Run `az extension add --name {r.name}` manually and retry."
            )
        raise typer.Exit(code=1)

    # Load existing config from file if it exists and is not empty, otherwise create new
    env_file = get_config_file_path()
    if env_file.exists() and env_file.stat().st_size > 0:
        try:
            from .cli_helpers import _load_with_migration

            env_cfg = _load_with_migration(env_file)
            # Ensure path is set after loading from JSON
            env_cfg.path = env_file
        except Exception as ex:
            error(f"Failed to validate existing config file: {ex}")
            info("Deleting corrupt config file and starting fresh")
            env_file.unlink()
            env_cfg = EnvConfig(path=env_file)
    else:
        env_cfg = EnvConfig(path=env_file)

    # Determine which steps to run
    run_specific = (
        only_acr
        or only_tool
        or only_archive_select
        or only_nodepool
        or only_api_version
        or only_scratch_select
    )
    run_all = not run_specific

    # Persist api_version if provided non-interactively
    if api_version:
        env_cfg.api_version = api_version
        info(f"API version set to: {api_version}")
    elif run_all or only_api_version:
        # Offer interactive picker during full configure or when explicitly requested
        select_api_version(env_cfg)

    # Determine API generation from the effective api_version. The Archive
    # picker dispatches the right resource type internally.
    is_legacy_api = ApiVersion.parse(env_cfg.api_version).uses_dataassets_uri

    if run_all:
        select_project_and_related(env_cfg)

    if run_all or only_acr:
        select_acr_registry(env_cfg)

    if run_all or only_tool:
        select_tool(env_cfg)

    # Archive selection (mandatory blob target for tool-run I/O persistence).
    if run_all or only_archive_select:
        select_archive(env_cfg)

    if only_nodepool:
        select_nodepool(env_cfg)

    if only_scratch_select:
        if not env_cfg.workspace_resource_id:
            error("Run 'discovery configure' first to select a project/workspace.")
            raise typer.Exit(code=1)
        select_supercomputer_scratch(env_cfg, force=True)
        # Re-derive nodepool scratch_dc_id after the mapping changes.
        from .resources import list_all_nodepools_with_details

        env_cfg.nodepools = list_all_nodepools_with_details(env_cfg)

    # Automatically save configuration changes
    env_cfg.save()
    info("Configuration updated")

    # Ensure Archive blob assets and underlying blob containers exist after
    # selection. Dispatches by API version (V1 dataasset flow vs V2 storageasset).
    if run_all or only_archive_select:
        if is_legacy_api:
            from .cli_build import ensure_data_assets_and_containers

            ensure_data_assets_and_containers(env_cfg)
        else:
            from .cli_build import ensure_storage_assets_and_containers

            ensure_storage_assets_and_containers(env_cfg)

    # Ensure a 'scratch' asset exists under each per-supercomputer scratch
    # ANF wrapper (V1: dataasset under DiscoveryStorage dataContainer;
    # V2: storageasset under AzureNetAppFiles storageContainer).
    if run_all or only_scratch_select:
        from .cli_build import ensure_scratch_assets

        ensure_scratch_assets(env_cfg)

    emit_env(env_cfg)


__all__ = ["app", "configure"]
