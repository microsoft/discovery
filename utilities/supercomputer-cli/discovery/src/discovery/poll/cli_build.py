"""Build-related CLI commands: build, rebuild, storage_url, create_user_storage."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer
from rich.console import Console

from discovery.common.logging import debug, error, info
from discovery.poll.models.api_version import ApiVersion
from discovery.poll.models.config import EnvConfig
from discovery.poll.models.dataasset import (
    BlobContainerInputs,
    DataAssetInputs,
    StorageAssetInputs,
)

from . import build_acr_task as acr
from .cli_helpers import (
    get_azure_username,
    get_config_file_path,
    get_location_from_supercomputer,
    load_project_config,
    run_configure_if_needed,
    sanitize_username,
)
from .deploy_dataasset import (
    check_blob_container_exists,
    check_dataasset_exists,
    deploy_blob_container,
    deploy_dataasset,
)
from .deploy_storageasset import (
    check_storageasset_exists,
    deploy_storageasset,
)
from .deploy_tooldef import ToolDefinitionInputs, deploy_tool_definition
from .resources import (
    get_datacontainer_datastore,
    get_datacontainer_storage_details,
    get_resource_group_and_location,
    get_storagecontainer_storage_details,
    get_storagecontainer_storagestore,
)
from .selection import select_acr_registry


app = typer.Typer()


def _load_acr_config(env_file: Path | None = None) -> EnvConfig:
    """Load config ensuring ACR is configured."""
    if env_file is None:
        env_file = get_config_file_path()
    env_cfg = run_configure_if_needed(env_file)
    if not env_cfg.acr_ready():
        select_acr_registry(env_cfg)
    else:
        debug("Using ACR from env (complete set present)")
    return env_cfg


def _ensure_data_assets_and_containers(
    env_cfg: EnvConfig, usernames: list[str] | None = None
) -> None:
    """Ensure data assets and blob containers for given usernames exist.

    Creates both data assets and blob containers if they don't already exist.
    Requires datacontainer_id to be set in env_cfg.

    Args:
        env_cfg: Environment configuration with datacontainer_id and subscription
        usernames: List of usernames to create assets for. If None, uses Azure CLI
                   logged-in username plus 'shared'.
    """
    if not env_cfg.datacontainer_id:
        debug("_ensure_data_assets_and_containers(): no datacontainer_id set, skipping")
        return

    if not env_cfg.subscription:
        error("_ensure_data_assets_and_containers(): missing subscription")
        return

    # Determine asset names
    if usernames is None:
        # Default behavior: use Azure CLI logged-in username plus 'shared'
        azure_username = get_azure_username()
        asset_names = [azure_username, "shared"]
    else:
        # Sanitize provided usernames the same way as Azure usernames
        asset_names = [sanitize_username(u) for u in usernames]

    # Extract data container name from resource ID
    data_container_name = env_cfg.datacontainer_id.split("/")[-1]

    # Get resource group and location from the datacontainer itself
    try:
        datacontainer_rg, datacontainer_location = get_resource_group_and_location(
            env_cfg.datacontainer_id
        )
        debug(
            f"Using datacontainer resource group: {datacontainer_rg}, "
            f"location: {datacontainer_location}"
        )
    except Exception as ex:
        error(f"Failed to get datacontainer resource group and location: {ex}")
        return

    # Inspect data container's dataStore kind. Only AzureStorageBlob data
    # containers have a backing storage account where we need to ensure blob
    # containers exist; DiscoveryStorage-backed data containers manage their
    # own storage, so we only create data assets for them.
    try:
        data_store = get_datacontainer_datastore(env_cfg.datacontainer_id)
    except Exception as ex:
        error(f"Failed to read data container dataStore: {ex}")
        return

    datastore_kind = data_store.get("kind")
    is_blob_backed = datastore_kind == "AzureStorageBlob"

    storage_account_name: str | None = None
    storage_rg: str | None = None

    if is_blob_backed:
        # Get storage account details for blob container operations
        try:
            storage_account_id = get_datacontainer_storage_details(env_cfg.datacontainer_id)
            storage_account_name = storage_account_id.split("/")[-1]
            # Get storage account resource group (may differ from datacontainer)
            storage_rg, _ = get_resource_group_and_location(storage_account_id)
            debug(f"Storage account resource group: {storage_rg}")
        except Exception as ex:
            error(f"Failed to get storage account details: {ex}")
            return
    else:
        debug(
            f"Data container dataStore.kind={datastore_kind!r}; "
            "skipping blob container creation"
        )

    typer.echo()
    typer.secho("Checking data assets and blob containers...", fg=typer.colors.CYAN, bold=True)

    for asset_name in asset_names:
        # Check and create data asset using datacontainer's RG and location
        try:
            asset_exists = check_dataasset_exists(
                env_cfg.subscription,
                env_cfg.datacontainer_id,
                asset_name,
            )

            if not asset_exists:
                info(f"Creating data asset '{asset_name}'...")
                asset_inputs = DataAssetInputs(
                    name=asset_name,
                    data_container_name=data_container_name,
                    location=datacontainer_location,
                    description=f"Data asset for {asset_name}",
                    path=f"{asset_name}/",
                )

                deploy_dataasset(
                    subscription_id=env_cfg.subscription,
                    resource_group=datacontainer_rg,
                    inputs=asset_inputs,
                    execute=True,
                    skip_if_exists=True,
                )
            else:
                info(f"Data asset '{asset_name}' already exists")
        except Exception as ex:
            error(f"Failed to ensure data asset '{asset_name}': {ex}")

        # Check and create blob container with same name using storage account's RG
        if not is_blob_backed:
            continue
        try:
            container_exists = check_blob_container_exists(
                storage_account_name,
                asset_name,
                env_cfg.subscription,
            )

            if not container_exists:
                info(f"Creating blob container '{asset_name}'...")
                container_inputs = BlobContainerInputs(
                    storage_account_name=storage_account_name,
                    container_name=asset_name,
                    subscription_id=env_cfg.subscription,
                    resource_group=storage_rg,
                    public_access="off",
                )

                deploy_blob_container(
                    inputs=container_inputs,
                    execute=True,
                    skip_if_exists=True,
                )
            else:
                info(f"Blob container '{asset_name}' already exists")
        except Exception as ex:
            error(f"Failed to ensure blob container '{asset_name}': {ex}")

    if is_blob_backed:
        typer.secho("✓ Data assets and blob containers verified", fg=typer.colors.GREEN)
    else:
        typer.secho("✓ Data assets verified", fg=typer.colors.GREEN)


def _ensure_scratch_assets(env_cfg: EnvConfig) -> None:
    """Ensure a 'scratch' asset exists in each per-supercomputer scratch ANF wrapper.

    Dispatches by API version:

    * V1 (``uses_dataassets_uri``): iterate
      ``env_cfg.supercomputer_scratch_dcs`` and create a ``scratch`` dataAsset
      under each DiscoveryStorage-kind dataContainer.
    * V2: iterate ``env_cfg.supercomputer_scratch_scs`` and create a
      ``scratch`` storageAsset under each AzureNetAppFiles-kind
      storageContainer.

    The asset is shared across runs against that supercomputer; per-run
    uniqueness is provided by the UUID subpath in the ``/scratch`` URI
    constructed at submit time (see ``cli_submit._build_scratch_mount``).

    Safe to call multiple times — uses ``check_*_exists`` and
    ``skip_if_exists=True``. Silently no-ops when the relevant mapping is empty.
    """
    if not env_cfg.subscription:
        debug("_ensure_scratch_assets(): missing subscription")
        return

    av = ApiVersion.parse(env_cfg.api_version)
    if av.uses_dataassets_uri:
        _ensure_scratch_dataassets(env_cfg)
    else:
        _ensure_scratch_storageassets(env_cfg)


def _ensure_scratch_dataassets(env_cfg: EnvConfig) -> None:
    unique_dcs = {dc_id for dc_id in (env_cfg.supercomputer_scratch_dcs or {}).values() if dc_id}
    if not unique_dcs:
        debug("_ensure_scratch_dataassets(): no scratch dataContainers configured")
        return

    typer.echo()
    typer.secho("Checking scratch dataAssets...", fg=typer.colors.CYAN, bold=True)

    for dc_id in sorted(unique_dcs):
        dc_name = dc_id.split("/")[-1] if "/" in dc_id else dc_id
        try:
            dc_rg, dc_location = get_resource_group_and_location(dc_id)
        except Exception as ex:  # noqa: BLE001 - best effort
            error(f"Failed to read scratch dataContainer '{dc_name}': {ex}")
            continue

        try:
            asset_exists = check_dataasset_exists(env_cfg.subscription, dc_id, "scratch")
            if asset_exists:
                info(f"Scratch dataAsset already exists in '{dc_name}'")
                continue
            info(f"Creating scratch dataAsset in '{dc_name}'...")
            asset_inputs = DataAssetInputs(
                name="scratch",
                data_container_name=dc_name,
                location=dc_location,
                description="Scratch ANF dataAsset for /scratch tool-run mounts",
                path="scratch/",
            )
            deploy_dataasset(
                subscription_id=env_cfg.subscription,
                resource_group=dc_rg,
                inputs=asset_inputs,
                execute=True,
                skip_if_exists=True,
            )
        except Exception as ex:  # noqa: BLE001
            error(f"Failed to ensure scratch dataAsset in '{dc_name}': {ex}")


def _ensure_scratch_storageassets(env_cfg: EnvConfig) -> None:
    unique_scs = {sc_id for sc_id in (env_cfg.supercomputer_scratch_scs or {}).values() if sc_id}
    if not unique_scs:
        debug("_ensure_scratch_storageassets(): no scratch storageContainers configured")
        return

    typer.echo()
    typer.secho("Checking scratch storageAssets...", fg=typer.colors.CYAN, bold=True)

    for sc_id in sorted(unique_scs):
        sc_name = sc_id.split("/")[-1] if "/" in sc_id else sc_id
        try:
            sc_rg, sc_location = get_resource_group_and_location(sc_id)
        except Exception as ex:  # noqa: BLE001
            error(f"Failed to read scratch storageContainer '{sc_name}': {ex}")
            continue

        try:
            asset_exists = check_storageasset_exists(env_cfg.subscription, sc_id, "scratch")
            if asset_exists:
                info(f"Scratch storageAsset already exists in '{sc_name}'")
                continue
            info(f"Creating scratch storageAsset in '{sc_name}'...")
            asset_inputs = StorageAssetInputs(
                name="scratch",
                storage_container_name=sc_name,
                location=sc_location,
                description="Scratch ANF storageAsset for /scratch tool-run mounts",
                path="scratch/",
            )
            deploy_storageasset(
                subscription_id=env_cfg.subscription,
                resource_group=sc_rg,
                inputs=asset_inputs,
                execute=True,
                skip_if_exists=True,
            )
        except Exception as ex:  # noqa: BLE001
            error(f"Failed to ensure scratch storageAsset in '{sc_name}': {ex}")


def _ensure_storage_assets_and_containers(
    env_cfg: EnvConfig, usernames: list[str] | None = None
) -> None:
    """Ensure storage assets and blob containers for given usernames exist.

    Storage assets are the v2 equivalent of data assets, introduced in the
    ``2026-02-01-preview`` API version. For ``AzureStorageBlob``-backed
    storage containers, this helper creates both a storage asset *and* a blob
    container of the same name (mirroring the legacy data-asset flow), so
    ``discovery://storageassets.../storageassets/{name}`` URIs resolve.

    Requires ``storagecontainer_id`` to be set in ``env_cfg``.

    Args:
        env_cfg: Environment configuration with storagecontainer_id and subscription
        usernames: List of usernames to create assets for. If None, uses Azure CLI
                   logged-in username plus 'shared'.
    """
    if not env_cfg.storagecontainer_id:
        debug("_ensure_storage_assets_and_containers(): no storagecontainer_id set, skipping")
        return

    if not env_cfg.subscription:
        error("_ensure_storage_assets_and_containers(): missing subscription")
        return

    if usernames is None:
        azure_username = get_azure_username()
        asset_names = [azure_username, "shared"]
    else:
        asset_names = [sanitize_username(u) for u in usernames]

    storage_container_name = env_cfg.storagecontainer_id.split("/")[-1]

    try:
        storagecontainer_rg, storagecontainer_location = get_resource_group_and_location(
            env_cfg.storagecontainer_id
        )
        debug(
            f"Using storagecontainer resource group: {storagecontainer_rg}, "
            f"location: {storagecontainer_location}"
        )
    except Exception as ex:
        error(f"Failed to get storagecontainer resource group and location: {ex}")
        return

    # Inspect storage container's storageStore kind. Only AzureStorageBlob
    # storage containers have a backing storage account where we also need to
    # ensure blob containers exist; DiscoveryStorage-backed storage containers
    # manage their own storage, so we only create storage assets for them.
    try:
        storage_store = get_storagecontainer_storagestore(env_cfg.storagecontainer_id)
    except Exception as ex:
        error(f"Failed to read storage container storageStore: {ex}")
        return

    storagestore_kind = storage_store.get("kind")
    is_blob_backed = storagestore_kind == "AzureStorageBlob"

    storage_account_name: str | None = None
    storage_rg: str | None = None

    if is_blob_backed:
        try:
            storage_account_id = get_storagecontainer_storage_details(
                env_cfg.storagecontainer_id
            )
            storage_account_name = storage_account_id.split("/")[-1]
            storage_rg, _ = get_resource_group_and_location(storage_account_id)
            debug(f"Storage account resource group: {storage_rg}")
        except Exception as ex:
            error(f"Failed to get storage account details: {ex}")
            return
    else:
        debug(
            f"Storage container storageStore.kind={storagestore_kind!r}; "
            "skipping blob container creation"
        )

    typer.echo()
    typer.secho(
        "Checking storage assets and blob containers...", fg=typer.colors.CYAN, bold=True
    )

    storage_container_resource_id = env_cfg.storagecontainer_id

    for asset_name in asset_names:
        # The storage asset's path has format "<container_name>[/<subpath>]";
        # match the legacy data-asset convention of using the same name for
        # both the asset and its backing blob container, with a trailing slash.
        asset_path = f"{asset_name}/"

        try:
            asset_exists = check_storageasset_exists(
                env_cfg.subscription,
                storage_container_resource_id,
                asset_name,
            )

            if not asset_exists:
                info(f"Creating storage asset '{asset_name}'...")
                asset_inputs = StorageAssetInputs(
                    name=asset_name,
                    storage_container_name=storage_container_name,
                    location=storagecontainer_location,
                    description=f"Storage asset for {asset_name}",
                    path=asset_path,
                )

                deploy_storageasset(
                    subscription_id=env_cfg.subscription,
                    resource_group=storagecontainer_rg,
                    inputs=asset_inputs,
                    execute=True,
                    skip_if_exists=True,
                )
            else:
                info(f"Storage asset '{asset_name}' already exists")
        except Exception as ex:
            error(f"Failed to ensure storage asset '{asset_name}': {ex}")

        if not is_blob_backed:
            continue
        try:
            container_exists = check_blob_container_exists(
                storage_account_name,
                asset_name,
                env_cfg.subscription,
            )

            if not container_exists:
                info(f"Creating blob container '{asset_name}'...")
                container_inputs = BlobContainerInputs(
                    storage_account_name=storage_account_name,
                    container_name=asset_name,
                    subscription_id=env_cfg.subscription,
                    resource_group=storage_rg,
                    public_access="off",
                )

                deploy_blob_container(
                    inputs=container_inputs,
                    execute=True,
                    skip_if_exists=True,
                )
            else:
                info(f"Blob container '{asset_name}' already exists")
        except Exception as ex:
            error(f"Failed to ensure blob container '{asset_name}': {ex}")

    if is_blob_backed:
        typer.secho("✓ Storage assets and blob containers verified", fg=typer.colors.GREEN)
    else:
        typer.secho("✓ Storage assets verified", fg=typer.colors.GREEN)



@app.command()
def build(
    context: Path = typer.Argument(  # noqa: B008
        Path("."),
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Build context directory (positional, default='.')",
    ),
    image: str = typer.Option("discovery-poller", prompt="Image name"),
    tag: str = typer.Option("latest", prompt="Image tag"),
    vscode: bool = typer.Option(
        False,
        help="Layer VS Code CLI into the final image (adds /usr/local/bin/code)",
    ),
    timeout: int = typer.Option(
        7200,
        help="Timeout in seconds for ACR task execution (default: 7200 / 2 hours)",
    ),
) -> None:
    """Build a Docker image via ACR Task (wrapper around internal build_acr_task).

    Args:
        context: Build context directory (positional, default='.')
        image: Image name (default: 'discovery-poller')
        tag: Image tag (default: 'latest')
        vscode: Layer VS Code CLI into the final image (default: False)
        timeout: Timeout in seconds for ACR task execution (default: 7200 / 2 hours)
    """
    env_cfg = _load_acr_config(get_config_file_path())

    code = acr.execute_build(
        context=context,
        image=image,
        tag=tag,
        acr_name=env_cfg.acr_name,
        vscode=vscode,
        timeout=timeout,
        login_server=env_cfg.acr_url,
    )

    if code == 0:
        info("Build completed successfully.")
    else:
        error(f"Build failed with exit code {code}")
        raise typer.Exit(code=code)

    if typer.confirm("Deploy tool definition now?", default=False):
        tool_name = typer.prompt("Tool name", default=image)
        description = typer.prompt("Tool description", default=f"Tool for {image}")

        # Get location from supercomputer
        location = get_location_from_supercomputer(env_cfg)
        if not location:
            error("Could not determine Azure location from configured supercomputer")
            raise typer.Exit(code=1)

        info(f"Using location '{location}' from configured supercomputer")

        full_image = (
            f"{env_cfg.acr_url}/{image}:{tag}" if env_cfg.acr_name else f"{image}:{tag}"
        )
        inputs = ToolDefinitionInputs(
            name=tool_name,
            description=description,
            image=full_image,
            location=location,
        )
        try:
            deploy_tool_definition(
                subscription_id=env_cfg.subscription,
                resource_group=env_cfg.resource_group,
                inputs=inputs,
            )
            typer.secho("Tool definition deployment completed.", fg=typer.colors.GREEN)
        except Exception as ex:  # pragma: no cover
            typer.secho(f"\nDeployment error: {ex}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from ex


@app.command()
def rebuild(
    image: str = typer.Option(..., prompt="Image name"),
    tag: str = typer.Option("latest", prompt="Image tag"),
    target_image: str = typer.Option(
        None,
        help="Optional target repository/image name. If not provided, uses the source image name.",
    ),
    target_tag: str = typer.Option(
        None,
        help="Optional new tag for the output image. If not provided, overwrites the source tag.",
    ),
    timeout: int = typer.Option(
        7200,
        help="Timeout in seconds for ACR task execution (default: 7200 / 2 hours)",
    ),
) -> None:
    """Layer VS Code CLI onto an existing ACR image.

    Args:
        image: Repository/image name
        tag: Existing image tag
        target_image: Optional target repository/image name. Defaults to source image.
        target_tag: Optional new tag for the output image. If not provided, overwrites the source tag.
        timeout: Timeout in seconds for ACR task execution (default: 7200 / 2 hours)
    """
    env_cfg = _load_acr_config(get_config_file_path())

    code = acr.execute_rebuild(
        image=image,
        tag=tag,
        acr_name=env_cfg.acr_name,
        target_image=target_image,
        target_tag=target_tag,
        timeout=timeout,
        login_server=env_cfg.acr_url,
    )

    if code == 0:
        info("Rebuild completed successfully.")
    else:
        error(f"Rebuild failed with exit code {code}")
        raise typer.Exit(code=code)


# Export the helpers for use in storage commands
ensure_data_assets_and_containers = _ensure_data_assets_and_containers
ensure_scratch_assets = _ensure_scratch_assets
ensure_storage_assets_and_containers = _ensure_storage_assets_and_containers


__all__ = [
    "app",
    "build",
    "ensure_data_assets_and_containers",
    "ensure_scratch_assets",
    "ensure_storage_assets_and_containers",
    "rebuild",
]
