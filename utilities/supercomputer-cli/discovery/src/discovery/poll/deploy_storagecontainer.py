"""Deploy AzureNetAppFiles-kind storageContainers via ARM templates.

Creates ``Microsoft.Discovery/storageContainers`` resources whose
``properties.storageStore.kind == "AzureNetAppFiles"``, wrapping a
``Microsoft.NetApp/netAppAccounts/capacityPools/volumes`` resource. The CLI
uses these as the V2 target for the user-mounted ``/scratch`` path; see
``cli_submit._build_scratch_mount`` for how the resulting URI is composed.

Mirrors the structure of ``deploy_datacontainer.py`` — the V1 equivalent
that wraps ``Microsoft.Discovery/storages`` instead.
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

from .models.dataasset import StorageContainerInputs


TEMPLATE_DIR = files("discovery.poll").joinpath("templates/storagecontainer")


def _load_text(name: str) -> str:
    return TEMPLATE_DIR.joinpath(name).read_text(encoding="utf-8")


def render_storagecontainer_parameters(inputs: StorageContainerInputs) -> dict[str, Any]:
    """Render parameters.json with placeholders substituted from ``inputs``."""
    raw = _load_text("parameters.json")
    obj = json.loads(raw)
    obj["parameters"]["outLocation"]["value"] = inputs.location
    obj["parameters"]["outStorageContainerName"]["value"] = inputs.name
    obj["parameters"]["outApiVersion"]["value"] = inputs.api_version
    obj["parameters"]["outNetAppVolumeId"]["value"] = inputs.netapp_volume_id
    return obj


def check_storagecontainer_exists(
    subscription_id: str,
    resource_group: str,
    name: str,
) -> bool:
    """Return True if ``Microsoft.Discovery/storageContainers/{name}`` exists in ``resource_group``."""
    rid = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Discovery/storageContainers/{name}"
    )
    cmd = ["az", "resource", "show", "--ids", rid, "-o", "json"]
    debug(f"check_storagecontainer_exists(): {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode == 0:
        return True
    stderr_lower = res.stderr.lower()
    if "notfound" in stderr_lower or "not found" in stderr_lower or "404" in stderr_lower:
        return False
    error(f"Unexpected error checking storageContainer: {res.stderr.strip()}")
    msg = f"Failed to check storageContainer existence: {res.stderr.strip()}"
    raise RuntimeError(msg)


def deploy_storagecontainer(
    subscription_id: str,
    resource_group: str,
    inputs: StorageContainerInputs,
    execute: bool = True,
    skip_if_exists: bool = True,
) -> dict[str, Any]:
    """Deploy an AzureNetAppFiles-kind storageContainer via ARM group deployment.

    Args:
        subscription_id: Subscription containing the target resource group.
        resource_group: Resource group to deploy into. Should usually match
            the wrapped ANF volume's RG.
        inputs: ``StorageContainerInputs`` (name, location, netAppVolumeId).
        execute: When False, no az command runs — rendered template/params
            are returned for inspection.
        skip_if_exists: When True, check existence before deploying.

    Returns:
        Dict with ``success``, ``skipped``, and ARM ``exitCode`` keys.

    Raises:
        RuntimeError: When the deployment command exits non-zero.
    """
    if skip_if_exists and execute:
        try:
            if check_storagecontainer_exists(subscription_id, resource_group, inputs.name):
                info(f"Storage container '{inputs.name}' already exists, skipping deployment")
                return {"success": True, "skipped": True, "reason": "exists"}
        except RuntimeError as ex:
            error(f"Could not verify storageContainer existence: {ex}")

    template_obj = json.loads(_load_text("template.json"))
    params_obj = render_storagecontainer_parameters(inputs)

    if not execute:
        return {"template": template_obj, "parameters": params_obj}

    typer.echo("\nThe following storage container deployment will be executed:\n")
    typer.secho("StorageContainer:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Name: {inputs.name}")
    typer.echo(f"  Kind: AzureNetAppFiles")
    typer.echo(f"  Location: {inputs.location}")
    typer.echo(f"  Wraps ANF volume: {inputs.netapp_volume_id}")
    typer.echo()
    typer.secho("Target:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Subscription: {subscription_id}")
    typer.echo(f"  Resource Group: {resource_group}")
    typer.echo()

    if not typer.confirm("Continue with deployment?", default=True):
        typer.secho("Deployment cancelled.", fg=typer.colors.YELLOW)
        return {"cancelled": True}

    with tempfile.TemporaryDirectory(prefix="storagecontainer-") as td:
        tdir = Path(td)
        template_path = tdir / "template.json"
        params_path = tdir / "parameters.json"
        template_path.write_text(json.dumps(template_obj, indent=2), encoding="utf-8")
        params_path.write_text(json.dumps(params_obj, indent=2), encoding="utf-8")

        deployment_name = f"storagecontainer-{datetime.now(tz=timezone.utc).strftime('%m%d%H%M%S')}"
        cmd = [
            "az", "deployment", "group", "create",
            "--subscription", subscription_id,
            "--resource-group", resource_group,
            "--template-file", str(template_path),
            "--parameters", str(params_path),
            "--name", deployment_name,
        ]

        typer.secho(f"Deploying storage container '{inputs.name}'...", fg=typer.colors.GREEN)
        proc = subprocess.run(cmd, text=True, check=False)
        if proc.returncode != 0:
            typer.secho("Storage container deployment failed", fg=typer.colors.RED, err=True)
            msg = f"Deployment command exited with code {proc.returncode}"
            raise RuntimeError(msg)

        typer.secho(
            f"Storage container '{inputs.name}' deployed successfully!",
            fg=typer.colors.GREEN, bold=True,
        )
        return {"exitCode": proc.returncode, "success": True}


def render_blob_storagecontainer_parameters(inputs: "BlobStorageContainerInputs") -> dict[str, Any]:
    """Render parameters_blob.json from a ``BlobStorageContainerInputs``."""
    raw = _load_text("parameters_blob.json")
    obj = json.loads(raw)
    obj["parameters"]["outLocation"]["value"] = inputs.location
    obj["parameters"]["outStorageContainerName"]["value"] = inputs.name
    obj["parameters"]["outApiVersion"]["value"] = inputs.api_version
    obj["parameters"]["outStorageAccountId"]["value"] = inputs.storage_account_id
    return obj


def deploy_blob_storagecontainer(
    subscription_id: str,
    resource_group: str,
    inputs: "BlobStorageContainerInputs",
    execute: bool = True,
    skip_if_exists: bool = True,
) -> dict[str, Any]:
    """Deploy an ``AzureStorageBlob``-kind V2 storageContainer via ARM group deployment.

    Equivalent of :func:`deploy_storagecontainer` for the blob discriminator.
    Wraps a ``Microsoft.Storage/storageAccounts`` resource. V2 storageContainers
    don't carry credentials (RBAC is bound at the workspace level), so this
    only requires the storage account ID.
    """
    if skip_if_exists and execute:
        try:
            if check_storagecontainer_exists(subscription_id, resource_group, inputs.name):
                info(f"Storage container '{inputs.name}' already exists, skipping deployment")
                return {"success": True, "skipped": True, "reason": "exists"}
        except RuntimeError as ex:
            error(f"Could not verify storageContainer existence: {ex}")

    template_obj = json.loads(_load_text("template_blob.json"))
    params_obj = render_blob_storagecontainer_parameters(inputs)

    if not execute:
        return {"template": template_obj, "parameters": params_obj}

    typer.echo("\nThe following storage container deployment will be executed:\n")
    typer.secho("StorageContainer:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Name: {inputs.name}")
    typer.echo(f"  Kind: AzureStorageBlob")
    typer.echo(f"  Location: {inputs.location}")
    typer.echo(f"  Wraps storage account: {inputs.storage_account_id}")
    typer.echo()
    typer.secho("Target:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Subscription: {subscription_id}")
    typer.echo(f"  Resource Group: {resource_group}")
    typer.echo()

    if not typer.confirm("Continue with deployment?", default=True):
        typer.secho("Deployment cancelled.", fg=typer.colors.YELLOW)
        return {"cancelled": True}

    with tempfile.TemporaryDirectory(prefix="storagecontainer-blob-") as td:
        tdir = Path(td)
        template_path = tdir / "template.json"
        params_path = tdir / "parameters.json"
        template_path.write_text(json.dumps(template_obj, indent=2), encoding="utf-8")
        params_path.write_text(json.dumps(params_obj, indent=2), encoding="utf-8")

        deployment_name = f"storagecontainer-blob-{datetime.now(tz=timezone.utc).strftime('%m%d%H%M%S')}"
        cmd = [
            "az", "deployment", "group", "create",
            "--subscription", subscription_id,
            "--resource-group", resource_group,
            "--template-file", str(template_path),
            "--parameters", str(params_path),
            "--name", deployment_name,
        ]

        typer.secho(f"Deploying blob storage container '{inputs.name}'...", fg=typer.colors.GREEN)
        proc = subprocess.run(cmd, text=True, check=False)
        if proc.returncode != 0:
            typer.secho("Storage container deployment failed", fg=typer.colors.RED, err=True)
            msg = f"Deployment command exited with code {proc.returncode}"
            raise RuntimeError(msg)

        typer.secho(
            f"Storage container '{inputs.name}' deployed successfully!",
            fg=typer.colors.GREEN, bold=True,
        )
        return {"exitCode": proc.returncode, "success": True}


__all__ = [
    "check_storagecontainer_exists",
    "deploy_blob_storagecontainer",
    "deploy_storagecontainer",
    "render_blob_storagecontainer_parameters",
    "render_storagecontainer_parameters",
]
