"""Deploy data assets and blob containers using ARM templates.

This module provides functions to:
1. Check if a data asset exists in Azure Discovery
2. Deploy a data asset if not present
3. Check if a blob container exists in Azure Storage
4. Deploy a blob container if not present

Follows the same pattern as deploy_tooldef.py for consistency.
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

from .models.dataasset import BlobContainerInputs, DataAssetInputs


TEMPLATE_DIR = files("discovery.poll").joinpath("templates/dataasset")


def _load_text(name: str) -> str:
    """Load a template file from the dataasset templates directory."""
    return TEMPLATE_DIR.joinpath(name).read_text(encoding="utf-8")


def render_dataasset_parameters(inputs: DataAssetInputs) -> dict[str, Any]:
    """Render the parameters.json with placeholder replacements.

    Args:
        inputs: DataAssetInputs containing deployment parameters

    Returns:
        Structured dict representing the ARM parameters file
    """
    raw_params = _load_text("parameters.json")
    params_obj = json.loads(raw_params)

    # Update parameter values
    params_obj["parameters"]["outLocation"]["value"] = inputs.location
    params_obj["parameters"]["outDataContainerName"]["value"] = inputs.data_container_name
    params_obj["parameters"]["outDataAssetName"]["value"] = inputs.name
    params_obj["parameters"]["outApiVersion"]["value"] = inputs.api_version
    params_obj["parameters"]["outDataAssetDescription"]["value"] = inputs.description
    params_obj["parameters"]["outDataAssetPath"]["value"] = inputs.path

    return params_obj


def check_dataasset_exists(
    subscription_id: str,
    data_container_resource_id: str,
    asset_name: str,
) -> bool:
    """Check if a data asset already exists.

    Args:
        subscription_id: Azure subscription ID
        data_container_resource_id: Full resource ID of the parent data container
        asset_name: Name of the data asset to check

    Returns:
        True if the data asset exists, False otherwise

    Raises:
        RuntimeError: If az CLI fails with an unexpected error
    """
    # Construct the full data asset resource ID
    asset_resource_id = f"{data_container_resource_id}/dataAssets/{asset_name}"

    cmd = [
        "az",
        "resource",
        "show",
        "--ids",
        asset_resource_id,
        "--subscription",
        subscription_id,
        "-o",
        "json",
    ]

    debug(f"check_dataasset_exists(): executing {' '.join(cmd)}")

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        msg = "Azure CLI 'az' not found while checking data asset"
        raise RuntimeError(msg) from exc

    if res.returncode == 0:
        info(f"Data asset '{asset_name}' already exists")
        return True

    # Check if it's a "not found" error vs. other errors
    stderr_lower = res.stderr.lower()
    if "notfound" in stderr_lower or "not found" in stderr_lower or "404" in stderr_lower:
        debug(f"Data asset '{asset_name}' does not exist")
        return False

    # Unexpected error
    error(f"Unexpected error checking data asset: {res.stderr.strip()}")
    msg = f"Failed to check data asset existence: {res.stderr.strip()}"
    raise RuntimeError(msg)


def deploy_dataasset(
    subscription_id: str,
    resource_group: str,
    inputs: DataAssetInputs,
    execute: bool = True,
    skip_if_exists: bool = True,
) -> dict[str, Any]:
    """Deploy (or prepare) a data asset via ARM group deployment.

    Args:
        subscription_id: Azure subscription containing the resource group
        resource_group: Target resource group name
        inputs: DataAssetInputs describing the data asset
        execute: When False, no az command is executed; payload returned for inspection
        skip_if_exists: When True, check if asset exists and skip deployment if found

    Returns:
        Dict with deployment results and metadata

    Raises:
        RuntimeError: If deployment fails
    """
    # Construct the data container resource ID for existence check
    data_container_resource_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Discovery/dataContainers/{inputs.data_container_name}"
    )

    # Check if asset already exists
    if skip_if_exists and execute:
        try:
            if check_dataasset_exists(subscription_id, data_container_resource_id, inputs.name):
                info(f"Data asset '{inputs.name}' already exists, skipping deployment")
                return {
                    "success": True,
                    "skipped": True,
                    "reason": "Data asset already exists",
                }
        except RuntimeError as ex:
            # If we can't check, proceed with deployment attempt
            error(f"Could not verify data asset existence: {ex}")

    # Load and render templates
    template_text = _load_text("template.json")
    template_obj = json.loads(template_text)
    params_obj = render_dataasset_parameters(inputs)

    if not execute:
        return {"template": template_obj, "parameters": params_obj}

    result: dict[str, Any] = {}

    # Display deployment details
    typer.echo("\nThe following data asset deployment will be executed:\n")
    typer.secho("Data Asset:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Name: {inputs.name}")
    typer.echo(f"  Data Container: {inputs.data_container_name}")
    typer.echo(f"  Location: {inputs.location}")
    typer.echo(f"  Path: {inputs.path}")
    if inputs.description:
        typer.echo(f"  Description: {inputs.description}")
    typer.echo()
    typer.secho("Target:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Subscription: {subscription_id}")
    typer.echo(f"  Resource Group: {resource_group}")
    typer.echo()

    # Prompt for confirmation
    if not typer.confirm("Continue with deployment?", default=True):
        typer.secho("Deployment cancelled.", fg=typer.colors.YELLOW)
        result["cancelled"] = True
        return result

    with tempfile.TemporaryDirectory(prefix="dataasset-") as td:
        tdir = Path(td)
        template_path = tdir / "template.json"
        params_path = tdir / "parameters.json"

        template_path.write_text(json.dumps(template_obj, indent=2), encoding="utf-8")
        params_path.write_text(json.dumps(params_obj, indent=2), encoding="utf-8")

        deployment_name = f"dataasset-{datetime.now(tz=timezone.utc).strftime('%m%d%H%M%S')}"

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

        typer.secho(f"Deploying data asset '{inputs.name}'...", fg=typer.colors.GREEN)

        # Stream output in real-time
        proc = subprocess.run(real_cmd, text=True, check=False)

        if proc.returncode != 0:
            typer.secho("Data asset deployment failed", fg=typer.colors.RED, err=True)
            msg = f"Deployment command exited with code {proc.returncode}"
            raise RuntimeError(msg)

        result["exitCode"] = proc.returncode
        result["success"] = True
        typer.secho(
            f"Data asset '{inputs.name}' deployed successfully!", fg=typer.colors.GREEN, bold=True
        )
        return result


def check_blob_container_exists(
    storage_account_name: str,
    container_name: str,
    subscription_id: str,
) -> bool:
    """Check if a blob container exists in the specified storage account.

    Args:
        storage_account_name: Name of the storage account
        container_name: Name of the blob container
        subscription_id: Azure subscription ID

    Returns:
        True if the container exists, False otherwise

    Raises:
        RuntimeError: If az CLI fails with an unexpected error
    """
    cmd = [
        "az",
        "storage",
        "container",
        "exists",
        "--account-name",
        storage_account_name,
        "--name",
        container_name,
        "--subscription",
        subscription_id,
        "--auth-mode",
        "login",
        "-o",
        "json",
    ]

    debug(f"check_blob_container_exists(): executing {' '.join(cmd)}")

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        msg = "Azure CLI 'az' not found while checking blob container"
        raise RuntimeError(msg) from exc

    if res.returncode != 0:
        stderr = res.stderr.strip()
        error(f"Failed to check blob container existence: {stderr}")
        msg = f"az CLI failed with exit code {res.returncode}: {stderr}"
        raise RuntimeError(msg)

    try:
        result = json.loads(res.stdout)
        exists = result.get("exists", False)
        debug(f"Blob container '{container_name}' exists: {exists}")
        return exists
    except Exception as exc:
        msg = "Failed to parse JSON from az storage container exists output"
        raise RuntimeError(msg) from exc


def deploy_blob_container(
    inputs: BlobContainerInputs,
    execute: bool = True,
    skip_if_exists: bool = True,
) -> dict[str, Any]:
    """Deploy a blob container if it doesn't already exist.

    Args:
        inputs: BlobContainerInputs containing deployment parameters
        execute: When False, returns the command that would be executed
        skip_if_exists: When True, check if container exists and skip if found

    Returns:
        Dict with deployment results and metadata

    Raises:
        RuntimeError: If deployment fails
    """
    # Check if container already exists
    if skip_if_exists and execute:
        try:
            if check_blob_container_exists(
                inputs.storage_account_name,
                inputs.container_name,
                inputs.subscription_id,
            ):
                info(f"Blob container '{inputs.container_name}' already exists, skipping creation")
                return {
                    "success": True,
                    "skipped": True,
                    "reason": "Blob container already exists",
                }
        except RuntimeError as ex:
            # If we can't check, proceed with creation attempt
            error(f"Could not verify blob container existence: {ex}")

    cmd = [
        "az",
        "storage",
        "container",
        "create",
        "--account-name",
        inputs.storage_account_name,
        "--name",
        inputs.container_name,
        "--subscription",
        inputs.subscription_id,
        "--auth-mode",
        "login",
        "--public-access",
        inputs.public_access,
        "-o",
        "json",
    ]

    if not execute:
        return {"command": cmd}

    # Display deployment details
    typer.echo("\nThe following blob container will be created:\n")
    typer.secho("Blob Container:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Name: {inputs.container_name}")
    typer.echo(f"  Storage Account: {inputs.storage_account_name}")
    typer.echo(f"  Public Access: {inputs.public_access}")
    typer.echo()
    typer.secho("Target:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Subscription: {inputs.subscription_id}")
    typer.echo(f"  Resource Group: {inputs.resource_group}")
    typer.echo()

    # Prompt for confirmation
    if not typer.confirm("Continue with container creation?", default=True):
        typer.secho("Container creation cancelled.", fg=typer.colors.YELLOW)
        return {"cancelled": True}

    debug(f"deploy_blob_container(): executing {' '.join(cmd)}")
    typer.secho(f"Creating blob container '{inputs.container_name}'...", fg=typer.colors.GREEN)

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        msg = "Azure CLI 'az' not found while creating blob container"
        raise RuntimeError(msg) from exc

    if res.returncode != 0:
        stderr = res.stderr.strip()
        typer.secho("Blob container creation failed", fg=typer.colors.RED, err=True)
        typer.echo(f"Error: {stderr}", err=True)
        msg = f"az CLI failed with exit code {res.returncode}: {stderr}"
        raise RuntimeError(msg)

    try:
        result = json.loads(res.stdout)
        created = result.get("created", False)

        if created:
            typer.secho(
                f"Blob container '{inputs.container_name}' created successfully!",
                fg=typer.colors.GREEN,
                bold=True,
            )
        else:
            typer.secho(
                f"Blob container '{inputs.container_name}' already exists",
                fg=typer.colors.YELLOW,
            )

        return {
            "success": True,
            "created": created,
            "exitCode": res.returncode,
        }
    except Exception as exc:
        msg = "Failed to parse JSON from az storage container create output"
        raise RuntimeError(msg) from exc


__all__ = [
    "check_blob_container_exists",
    "check_dataasset_exists",
    "deploy_blob_container",
    "deploy_dataasset",
    "render_dataasset_parameters",
]
