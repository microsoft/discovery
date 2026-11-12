"""Deploy a Discovery tool definition using ARM templates.

This helper loads the packaged templates under templates/tooldef/, performs placeholder
substitutions, and invokes an Azure deployment. Network calls only occur when
`execute=True`; otherwise the function returns the computed deployment payload for testing.

Placeholders supported in template.json / parameters.json:
  NAME_PLACEHOLDER -> tool name
  DESC_PLACEHOLDER -> tool description
  ACR_IMAGE_PLACEHOLDER -> container image reference
  TOOL_LOCATION_PLACEHOLDER -> Azure region
  TOOL_JSON_PLACEHOLDER -> JSON-escaped tool definition (string) inserted into parameters

Usage example (execute mode):
    deploy_tool_definition(
        subscription_id="...",
        resource_group="rg-discovery",
        name="demo-tool",
        description="Demo container tool",
        image="acrname.azurecr.io/discovery-poller:latest",
        location="eastus",
    )

The resource type and properties envelope remain Microsoft.Discovery/tools across
the supported tool ARM APIs. Python deployments explicitly select GA by default;
the template retains a legacy fallback for standalone callers.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

import typer

from discovery.common.logging import debug, pretty_debug
from discovery.poll.models.arm_versions import TOOL_ARM_API_VERSION, ToolArmApiVersion


TEMPLATE_DIR = files("discovery.poll").joinpath("templates/tooldef")


def resolve_tool_pool_size(mpi: bool, pool_size: int | None) -> int:
    """Resolve and validate the default pod count for a tool definition."""
    minimum = 2 if mpi else 1
    effective_size = minimum if pool_size is None else pool_size
    if effective_size < minimum:
        suffix = " for MPI tools" if mpi else ""
        msg = f"pool_size must be at least {minimum}{suffix}"
        raise ValueError(msg)
    return effective_size


@dataclass
class ToolDefinitionInputs:
    name: str
    description: str
    image: str
    location: str
    version: str = "1.0"
    environment: dict[str, str] | None = None
    tags: dict[str, dict[str, str]] | None = None  # tagsByResource structure
    mpi: bool = False
    pool_size: int | None = None
    infiniband: bool = False
    api_version: str = TOOL_ARM_API_VERSION

    def __post_init__(self) -> None:
        """Validate pod count and the independent tool ARM API selection."""
        self.pool_size = resolve_tool_pool_size(self.mpi, self.pool_size)
        self.api_version = ToolArmApiVersion(self.api_version).value


def _load_text(name: str) -> str:
    return TEMPLATE_DIR.joinpath(name).read_text(encoding="utf-8")


def _escape_tool_json(obj: dict[str, Any]) -> str:
    # Embed as a JSON string in parameters file (the ARM template json() function will parse it)
    return json.dumps(obj, separators=(",", ":"))


def render_tool_definition(inputs: ToolDefinitionInputs) -> dict[str, Any]:
    """Render the tool definition JSON (template.json) with placeholders replaced.

    Returns structured dict (not string); separate function handles wrapping into ARM parameters.
    """
    raw = _load_text("template.json")
    raw = raw.replace("NAME_PLACEHOLDER", inputs.name)
    raw = raw.replace("DESC_PLACEHOLDER", inputs.description)
    raw = raw.replace("ACR_IMAGE_PLACEHOLDER", inputs.image)
    tool_def: dict[str, Any] = json.loads(raw)
    infra = tool_def["infra"][0]
    infra["compute"]["pool_size"] = inputs.pool_size
    if inputs.mpi:
        # MPI is selected by this metadata, not infra_type or replica count.
        infra["mpi"] = {"follower_command": "/opt/Microsoft.Discovery/mpid"}
        infra["internal_ports"] = [{"destination": 22, "protocol": "tcp"}]
    if inputs.infiniband:
        infra["compute"]["infiniband"] = True
    return tool_def


def build_arm_parameters(inputs: ToolDefinitionInputs, tool_def: dict[str, Any]) -> dict[str, Any]:
    raw_params = _load_text("parameters.json")
    escaped_tool_json = _escape_tool_json(tool_def)
    raw_params = raw_params.replace("NAME_PLACEHOLDER", inputs.name)
    raw_params = raw_params.replace("TOOL_LOCATION_PLACEHOLDER", inputs.location)
    # TOOL_JSON_PLACEHOLDER is within quotes already in parameters.json; we need to
    # escape internal quotes
    escaped_for_param = escaped_tool_json.replace('"', '\\"')
    raw_params = raw_params.replace("TOOL_JSON_PLACEHOLDER", escaped_for_param)
    # Respect version override if provided
    raw_params = raw_params.replace('"1.0"', json.dumps(inputs.version))
    params_obj = json.loads(raw_params)
    params_obj["parameters"]["outApiVersion"] = {"value": inputs.api_version}
    # Inject env vars if provided
    if inputs.environment:
        params_obj["parameters"]["OutEnvironmentVariables"]["value"] = json.dumps(
            inputs.environment
        )
    if inputs.tags:
        params_obj["parameters"]["outTagsByResource"]["value"] = inputs.tags
    return params_obj


def deploy_tool_definition(
    subscription_id: str,
    resource_group: str,
    inputs: ToolDefinitionInputs,
    execute: bool = True,
) -> dict[str, Any]:
    """Deploy (or prepare) a tool definition via ARM group deployment.

    Args:
        subscription_id: Azure subscription containing the resource group.
        resource_group: Target resource group name.
        inputs: ToolDefinitionInputs describing the tool.
        execute: When False, no az command is executed; payload returned for inspection.

    Returns:
        Dict with keys: template (dict), parameters (dict), command (list[str])
    """
    template_text = _load_text("arm_template.json")
    template_obj = json.loads(template_text)
    tool_def = render_tool_definition(inputs)
    params_obj = build_arm_parameters(inputs, tool_def)
    if not execute:
        return {"template": template_obj, "parameters": params_obj}

    result: dict = {}

    # Display deployment details
    typer.echo("\nThe following deployment will be executed:\n")
    typer.secho("Tool Definition:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Name: {inputs.name}")
    typer.echo(f"  Description: {inputs.description}")
    typer.echo(f"  Image: {inputs.image}")
    typer.echo(f"  Location: {inputs.location}")
    typer.echo(
        f"  Tool ARM API: {inputs.api_version}\n"
        f"  MPI: {inputs.mpi}\n"
        f"  Pool size (pods per run): {inputs.pool_size}\n"
        f"  InfiniBand required: {inputs.infiniband}"
    )
    typer.echo()
    typer.secho("Target:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Subscription: {subscription_id}")
    typer.echo(f"  Resource Group: {resource_group}")
    typer.echo()
    typer.secho("Command:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  az deployment group create --subscription {subscription_id} \\")
    typer.echo(f"    --resource-group {resource_group} \\")
    typer.echo("    --template-file <template.json> \\")
    typer.echo("    --parameters <parameters.json>")
    typer.echo()

    # Debug: print template and parameters JSON
    debug("ARM template and parameters prepared")
    pretty_debug(template_obj, label="Template JSON")
    pretty_debug(params_obj, label="Parameters JSON")

    # Prompt for confirmation
    if not typer.confirm("Continue with deployment?", default=True):
        typer.secho("Deployment cancelled.", fg=typer.colors.YELLOW)
        result["cancelled"] = True
        return result

    with tempfile.TemporaryDirectory(prefix="tooldef-") as td:
        tdir = Path(td)
        template_path = tdir / "template.json"
        params_path = tdir / "parameters.json"
        template_path.write_text(json.dumps(template_obj, indent=2), encoding="utf-8")
        params_path.write_text(json.dumps(params_obj, indent=2), encoding="utf-8")
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
            f"{datetime.now(tz=timezone.utc).strftime('%m%d%H%M%S')}",
        ]
        typer.secho(f"Deploying tool definition '{inputs.name}'", fg=typer.colors.GREEN)

        # Stream output in real-time instead of capturing
        proc = subprocess.run(real_cmd, text=True, check=False)

        if proc.returncode != 0:
            typer.secho("Deployment failed", fg=typer.colors.RED, err=True)
            typer.secho("\nTemplate JSON:", fg=typer.colors.YELLOW, err=True)
            typer.echo(json.dumps(template_obj, indent=2), err=True)
            typer.secho("\nParameters JSON:", fg=typer.colors.YELLOW, err=True)
            typer.echo(json.dumps(params_obj, indent=2), err=True)
            msg = f"Deployment command exited with code {proc.returncode}"
            raise RuntimeError(msg)

        result["exitCode"] = proc.returncode
        result["success"] = True
        return result


__all__ = [
    "ToolDefinitionInputs",
    "build_arm_parameters",
    "deploy_tool_definition",
    "render_tool_definition",
    "resolve_tool_pool_size",
]
