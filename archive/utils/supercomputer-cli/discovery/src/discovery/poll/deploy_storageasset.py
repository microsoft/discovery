"""Deploy storage assets using ARM templates.

This module provides functions to:
1. Check if a storage asset exists in Azure Discovery
2. Deploy a storage asset if not present

Storage assets are the v2 equivalent of data assets, introduced in the
``2026-02-01-preview`` API version. They live under
``Microsoft.Discovery/storagecontainers/{name}/storageAssets/{asset}``.

Follows the same pattern as deploy_dataasset.py for consistency.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

import typer

from discovery.common.logging import debug, error, info

from .models.dataasset import StorageAssetInputs


TEMPLATE_DIR = files("discovery.poll").joinpath("templates/storageasset")

STORAGE_ASSET_API_VERSION = "2026-02-01-preview"


def _load_text(name: str) -> str:
    """Load a template file from the storageasset templates directory."""
    return TEMPLATE_DIR.joinpath(name).read_text(encoding="utf-8")


def render_storageasset_parameters(inputs: StorageAssetInputs) -> dict[str, Any]:
    """Render the parameters.json with placeholder replacements.

    Args:
        inputs: StorageAssetInputs containing deployment parameters

    Returns:
        Structured dict representing the ARM parameters file
    """
    raw_params = _load_text("parameters.json")
    params_obj = json.loads(raw_params)

    params_obj["parameters"]["outLocation"]["value"] = inputs.location
    params_obj["parameters"]["outStorageContainerName"]["value"] = inputs.storage_container_name
    params_obj["parameters"]["outStorageAssetName"]["value"] = inputs.name
    params_obj["parameters"]["outApiVersion"]["value"] = inputs.api_version
    params_obj["parameters"]["outStorageAssetDescription"]["value"] = inputs.description
    params_obj["parameters"]["outStorageAssetPath"]["value"] = inputs.path

    return params_obj


def check_storageasset_exists(
    subscription_id: str,
    storage_container_resource_id: str,
    asset_name: str,
) -> bool:
    """Check if a storage asset already exists.

    Args:
        subscription_id: Azure subscription ID
        storage_container_resource_id: Full resource ID of the parent storage container
        asset_name: Name of the storage asset to check

    Returns:
        True if the storage asset exists, False otherwise

    Raises:
        RuntimeError: If az CLI fails with an unexpected error
    """
    asset_resource_id = f"{storage_container_resource_id}/storageAssets/{asset_name}"

    cmd = [
        "az",
        "resource",
        "show",
        "--ids",
        asset_resource_id,
        "--subscription",
        subscription_id,
        "--api-version",
        STORAGE_ASSET_API_VERSION,
        "-o",
        "json",
    ]

    debug(f"check_storageasset_exists(): executing {' '.join(cmd)}")

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        msg = "Azure CLI 'az' not found while checking storage asset"
        raise RuntimeError(msg) from exc

    if res.returncode == 0:
        info(f"Storage asset '{asset_name}' already exists")
        return True

    stderr_lower = res.stderr.lower()
    if "notfound" in stderr_lower or "not found" in stderr_lower or "404" in stderr_lower:
        debug(f"Storage asset '{asset_name}' does not exist")
        return False

    error(f"Unexpected error checking storage asset: {res.stderr.strip()}")
    msg = f"Failed to check storage asset existence: {res.stderr.strip()}"
    raise RuntimeError(msg)


def deploy_storageasset(
    subscription_id: str,
    resource_group: str,
    inputs: StorageAssetInputs,
    execute: bool = True,
    skip_if_exists: bool = True,
) -> dict[str, Any]:
    """Deploy (or prepare) a storage asset via ARM group deployment.

    Args:
        subscription_id: Azure subscription containing the resource group
        resource_group: Target resource group name
        inputs: StorageAssetInputs describing the storage asset
        execute: When False, no az command is executed; payload returned for inspection
        skip_if_exists: When True, check if asset exists and skip deployment if found

    Returns:
        Dict with deployment results and metadata

    Raises:
        RuntimeError: If deployment fails
    """
    storage_container_resource_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Discovery/storagecontainers/{inputs.storage_container_name}"
    )

    if skip_if_exists and execute:
        try:
            if check_storageasset_exists(
                subscription_id, storage_container_resource_id, inputs.name
            ):
                info(f"Storage asset '{inputs.name}' already exists, skipping deployment")
                return {
                    "success": True,
                    "skipped": True,
                    "reason": "Storage asset already exists",
                }
        except RuntimeError as ex:
            error(f"Could not verify storage asset existence: {ex}")

    template_text = _load_text("template.json")
    template_obj = json.loads(template_text)
    params_obj = render_storageasset_parameters(inputs)

    if not execute:
        return {"template": template_obj, "parameters": params_obj}

    result: dict[str, Any] = {}

    typer.echo("\nThe following storage asset deployment will be executed:\n")
    typer.secho("Storage Asset:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Name: {inputs.name}")
    typer.echo(f"  Storage Container: {inputs.storage_container_name}")
    typer.echo(f"  Location: {inputs.location}")
    typer.echo(f"  Path: {inputs.path}")
    if inputs.description:
        typer.echo(f"  Description: {inputs.description}")
    typer.echo()
    typer.secho("Target:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Subscription: {subscription_id}")
    typer.echo(f"  Resource Group: {resource_group}")
    typer.echo()

    if not typer.confirm("Continue with deployment?", default=True):
        typer.secho("Deployment cancelled.", fg=typer.colors.YELLOW)
        result["cancelled"] = True
        return result

    with tempfile.TemporaryDirectory(prefix="storageasset-") as td:
        tdir = Path(td)
        template_path = tdir / "template.json"
        params_path = tdir / "parameters.json"

        template_path.write_text(json.dumps(template_obj, indent=2), encoding="utf-8")
        params_path.write_text(json.dumps(params_obj, indent=2), encoding="utf-8")

        deployment_name = f"storageasset-{datetime.now(tz=timezone.utc).strftime('%m%d%H%M%S')}"

        real_cmd = [
            "az",
            "deployment",
            "group",
            "create",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--template-file",
            str(template_path),
            "--parameters",
            str(params_path),
            "--name",
            deployment_name,
        ]

        typer.secho(f"Deploying storage asset '{inputs.name}'...", fg=typer.colors.GREEN)

        proc = subprocess.run(real_cmd, text=True, check=False)

        if proc.returncode != 0:
            typer.secho("Storage asset deployment failed", fg=typer.colors.RED, err=True)
            msg = f"Deployment command exited with code {proc.returncode}"
            raise RuntimeError(msg)

        result["exitCode"] = proc.returncode
        result["success"] = True
        typer.secho(
            f"Storage asset '{inputs.name}' deployed successfully!",
            fg=typer.colors.GREEN,
            bold=True,
        )
        return result


__all__ = [
    "STORAGE_ASSET_API_VERSION",
    "check_storageasset_exists",
    "deploy_storageasset",
    "render_storageasset_parameters",
]
