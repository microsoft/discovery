"""Deploy DiscoveryStorage-kind dataContainers via ARM templates.

Creates ``Microsoft.Discovery/datacontainers`` resources whose
``properties.dataStore.kind == "DiscoveryStorage"``, wrapping a
``Microsoft.Discovery/storages`` (ANF) resource. The CLI uses these as the
target for the V1 ``/anf_scratch`` mount; see
``cli_submit._build_anf_scratch_mount`` for how the resulting URI is composed.

Mirrors the structure of ``deploy_dataasset.py``.
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

from .models.dataasset import DataContainerInputs


TEMPLATE_DIR = files("discovery.poll").joinpath("templates/datacontainer")


def _load_text(name: str) -> str:
    return TEMPLATE_DIR.joinpath(name).read_text(encoding="utf-8")


def render_datacontainer_parameters(inputs: DataContainerInputs) -> dict[str, Any]:
    """Render parameters.json with placeholders substituted from ``inputs``."""
    raw = _load_text("parameters.json")
    obj = json.loads(raw)
    obj["parameters"]["outLocation"]["value"] = inputs.location
    obj["parameters"]["outDataContainerName"]["value"] = inputs.name
    obj["parameters"]["outApiVersion"]["value"] = inputs.api_version
    obj["parameters"]["outDiscoveryStorageId"]["value"] = inputs.discovery_storage_id
    obj["parameters"]["outCredentialIdentityId"]["value"] = inputs.credential_identity_id
    return obj


def check_datacontainer_exists(
    subscription_id: str,
    resource_group: str,
    name: str,
) -> bool:
    """Return True if a ``Microsoft.Discovery/datacontainers/{name}`` exists in ``resource_group``."""
    rid = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Discovery/dataContainers/{name}"
    )
    cmd = ["az", "resource", "show", "--ids", rid, "-o", "json"]
    debug(f"check_datacontainer_exists(): {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode == 0:
        return True
    stderr_lower = res.stderr.lower()
    if "notfound" in stderr_lower or "not found" in stderr_lower or "404" in stderr_lower:
        return False
    error(f"Unexpected error checking dataContainer: {res.stderr.strip()}")
    msg = f"Failed to check dataContainer existence: {res.stderr.strip()}"
    raise RuntimeError(msg)


def deploy_datacontainer(
    subscription_id: str,
    resource_group: str,
    inputs: DataContainerInputs,
    execute: bool = True,
    skip_if_exists: bool = True,
) -> dict[str, Any]:
    """Deploy a DiscoveryStorage-kind dataContainer via ARM group deployment.

    Args:
        subscription_id: Subscription containing the target resource group.
        resource_group: Resource group to deploy into. Should usually be the
            same RG as the wrapped ANF storage to keep the CLI's RG-derived
            heuristics happy elsewhere.
        inputs: ``DataContainerInputs`` with name, location, discoveryStorageId.
        execute: When False, no az command runs; the rendered template +
            parameters are returned for inspection (useful in tests).
        skip_if_exists: When True, check existence before deploying.

    Returns:
        Dict with ``success``, ``skipped``, and ARM ``exitCode`` keys.

    Raises:
        RuntimeError: When the deployment command exits non-zero.
    """
    if skip_if_exists and execute:
        try:
            if check_datacontainer_exists(subscription_id, resource_group, inputs.name):
                info(f"Data container '{inputs.name}' already exists, skipping deployment")
                return {"success": True, "skipped": True, "reason": "exists"}
        except RuntimeError as ex:
            error(f"Could not verify dataContainer existence: {ex}")

    template_obj = json.loads(_load_text("template.json"))
    params_obj = render_datacontainer_parameters(inputs)

    if not execute:
        return {"template": template_obj, "parameters": params_obj}

    typer.echo("\nThe following data container deployment will be executed:\n")
    typer.secho("DataContainer:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Name: {inputs.name}")
    typer.echo(f"  Kind: DiscoveryStorage")
    typer.echo(f"  Location: {inputs.location}")
    typer.echo(f"  Wraps ANF: {inputs.discovery_storage_id}")
    typer.echo()
    typer.secho("Target:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Subscription: {subscription_id}")
    typer.echo(f"  Resource Group: {resource_group}")
    typer.echo()

    if not typer.confirm("Continue with deployment?", default=True):
        typer.secho("Deployment cancelled.", fg=typer.colors.YELLOW)
        return {"cancelled": True}

    with tempfile.TemporaryDirectory(prefix="datacontainer-") as td:
        tdir = Path(td)
        template_path = tdir / "template.json"
        params_path = tdir / "parameters.json"
        template_path.write_text(json.dumps(template_obj, indent=2), encoding="utf-8")
        params_path.write_text(json.dumps(params_obj, indent=2), encoding="utf-8")

        deployment_name = f"datacontainer-{datetime.now(tz=timezone.utc).strftime('%m%d%H%M%S')}"
        cmd = [
            "az", "deployment", "group", "create",
            "--subscription", subscription_id,
            "--resource-group", resource_group,
            "--template-file", str(template_path),
            "--parameters", str(params_path),
            "--name", deployment_name,
        ]

        typer.secho(f"Deploying data container '{inputs.name}'...", fg=typer.colors.GREEN)
        proc = subprocess.run(cmd, text=True, check=False)
        if proc.returncode != 0:
            typer.secho("Data container deployment failed", fg=typer.colors.RED, err=True)
            msg = f"Deployment command exited with code {proc.returncode}"
            raise RuntimeError(msg)

        typer.secho(
            f"Data container '{inputs.name}' deployed successfully!",
            fg=typer.colors.GREEN, bold=True,
        )
        return {"exitCode": proc.returncode, "success": True}


def render_blob_datacontainer_parameters(inputs: "BlobDataContainerInputs") -> dict[str, Any]:
    """Render parameters_blob.json from a ``BlobDataContainerInputs``."""
    raw = _load_text("parameters_blob.json")
    obj = json.loads(raw)
    obj["parameters"]["outLocation"]["value"] = inputs.location
    obj["parameters"]["outDataContainerName"]["value"] = inputs.name
    obj["parameters"]["outApiVersion"]["value"] = inputs.api_version
    obj["parameters"]["outStorageAccountId"]["value"] = inputs.storage_account_id
    obj["parameters"]["outCredentialIdentityId"]["value"] = inputs.credential_identity_id
    return obj


def deploy_blob_datacontainer(
    subscription_id: str,
    resource_group: str,
    inputs: "BlobDataContainerInputs",
    execute: bool = True,
    skip_if_exists: bool = True,
) -> dict[str, Any]:
    """Deploy an ``AzureStorageBlob``-kind V1 dataContainer via ARM group deployment.

    Equivalent of :func:`deploy_datacontainer` for the blob discriminator.
    Wraps a ``Microsoft.Storage/storageAccounts`` resource and attaches a
    UAMI credential. The UAMI must already have RBAC for the account
    (Storage Blob Data Contributor or similar) — this function does not
    grant roles.
    """
    if skip_if_exists and execute:
        try:
            if check_datacontainer_exists(subscription_id, resource_group, inputs.name):
                info(f"Data container '{inputs.name}' already exists, skipping deployment")
                return {"success": True, "skipped": True, "reason": "exists"}
        except RuntimeError as ex:
            error(f"Could not verify dataContainer existence: {ex}")

    template_obj = json.loads(_load_text("template_blob.json"))
    params_obj = render_blob_datacontainer_parameters(inputs)

    if not execute:
        return {"template": template_obj, "parameters": params_obj}

    typer.echo("\nThe following data container deployment will be executed:\n")
    typer.secho("DataContainer:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Name: {inputs.name}")
    typer.echo(f"  Kind: AzureStorageBlob")
    typer.echo(f"  Location: {inputs.location}")
    typer.echo(f"  Wraps storage account: {inputs.storage_account_id}")
    typer.echo(f"  UAMI credential: {inputs.credential_identity_id}")
    typer.echo()
    typer.secho("Target:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Subscription: {subscription_id}")
    typer.echo(f"  Resource Group: {resource_group}")
    typer.echo()

    if not typer.confirm("Continue with deployment?", default=True):
        typer.secho("Deployment cancelled.", fg=typer.colors.YELLOW)
        return {"cancelled": True}

    with tempfile.TemporaryDirectory(prefix="datacontainer-blob-") as td:
        tdir = Path(td)
        template_path = tdir / "template.json"
        params_path = tdir / "parameters.json"
        template_path.write_text(json.dumps(template_obj, indent=2), encoding="utf-8")
        params_path.write_text(json.dumps(params_obj, indent=2), encoding="utf-8")

        deployment_name = f"datacontainer-blob-{datetime.now(tz=timezone.utc).strftime('%m%d%H%M%S')}"
        cmd = [
            "az", "deployment", "group", "create",
            "--subscription", subscription_id,
            "--resource-group", resource_group,
            "--template-file", str(template_path),
            "--parameters", str(params_path),
            "--name", deployment_name,
        ]

        typer.secho(f"Deploying blob data container '{inputs.name}'...", fg=typer.colors.GREEN)
        proc = subprocess.run(cmd, text=True, check=False)
        if proc.returncode != 0:
            typer.secho("Data container deployment failed", fg=typer.colors.RED, err=True)
            msg = f"Deployment command exited with code {proc.returncode}"
            raise RuntimeError(msg)

        typer.secho(
            f"Data container '{inputs.name}' deployed successfully!",
            fg=typer.colors.GREEN, bold=True,
        )
        return {"exitCode": proc.returncode, "success": True}


# NOTE: ``BlobDataContainerInputs`` is referenced only via string annotations
# above so this module stays import-cheap.


__all__ = [
    "check_datacontainer_exists",
    "deploy_blob_datacontainer",
    "deploy_datacontainer",
    "render_blob_datacontainer_parameters",
    "render_datacontainer_parameters",
]
