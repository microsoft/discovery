#!/usr/bin/env python
"""Build a Docker image using Azure Container Registry (ACR) Tasks.

Features:
  * Discovers available ACR registries via `az acr list`
  * Writes discovered/selected registry into an env file as `ACR_NAME` when missing
    or when the --configure flag is provided
  * Positional argument for build context (directory) - defaults to current directory '.'
  * Optional --tag parameter (defaults to 'latest')
  * Confirmation prompt before executing build unless --yes supplied
  * Minimal, dependency-light (uses Typer + stdlib + az CLI)

Exit codes:
  0 success
  2 configuration / missing input problem
  3 registry discovery failure
  4 az cli invocation failure

NOTE: This script purposefully does not replicate every flag of `az acr build`; extend as needed.
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from textwrap import dedent

import typer

from .vscode_layer import prepare_vscode_layer


DEFAULT_TAG = "latest"
DEFAULT_IMAGE = "discovery-poller"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ensure_az_cli() -> None:
    """Ensure the Azure CLI is available."""
    if not shutil.which("az"):
        typer.secho("Azure CLI 'az' not found in PATH", fg=typer.colors.RED, err=True)
        raise typer.Exit(4)


def run_az(args: list[str]) -> subprocess.CompletedProcess:
    """Run an az CLI command returning the completed process.

    Does not raise; caller interprets returncode.
    """
    try:
        return subprocess.run(["az", *args], capture_output=True, text=True, check=False)
    except OSError as ex:  # pragma: no cover
        typer.secho(f"Failed invoking az: {ex}", fg=typer.colors.RED, err=True)
        raise typer.Exit(4) from ex


def list_acr_names() -> list[str]:
    """Return list of ACR names in the current subscription context."""
    proc = run_az(["acr", "list", "--query", "[].name", "-o", "tsv"])
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def get_acr_login_server(name: str) -> str:
    """Return the loginServer for an ACR registry, or fall back to ``{name}.azurecr.io``."""
    proc = run_az(["acr", "show", "--name", name, "--query", "loginServer", "-o", "tsv"])
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return f"{name}.azurecr.io"


def select_registry_interactive(options: list[str]) -> str:
    """Prompt user to select a registry from options."""
    typer.echo("Select ACR registry:")
    for idx, name in enumerate(options, start=1):
        typer.echo(f"  {idx}) {name}")
    while True:
        raw = input("Enter number or name: ").strip()
        if not raw:
            continue
        if raw.isdigit():
            i = int(raw)
            if 1 <= i <= len(options):
                return options[i - 1]
        elif raw in options:
            return raw
        typer.echo("Invalid selection, try again.")


def write_env_value(env_path: Path, key: str, value: str, force: bool) -> None:
    """Write or update a KEY=VALUE pair in a dotenv style file.

    If force is False and key exists, leaves it unchanged.
    """
    lines: list[str] = []
    replaced = False
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                if force:
                    lines.append(f"{key}={value}")
                else:
                    lines.append(line)
                replaced = True
            else:
                lines.append(line)
    if not replaced:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Core build logic (remaining helpers kept local to avoid extra imports)
# ---------------------------------------------------------------------------


def acr_registry_exists(name: str) -> bool:
    proc = run_az(["acr", "show", "--name", name])
    return proc.returncode == 0


def build_image(
    registry: str,
    image: str,
    tag: str,
    context: Path,
    timeout: int = 7200,
    login_server: str = "",
) -> int:
    """Build and push an image to ACR using BuildKit-enabled ACR tasks.

    Emits a temporary multi-step task that enables BuildKit (via ``DOCKER_BUILDKIT=1``)
    and executes it with ``az acr run``.
    Returns 0 on success else non-zero exit code (4 used for build failure).
    """
    context = context.resolve()
    effective_server = login_server or f"{registry}.azurecr.io"
    full_image = f"{effective_server}/{image}:{tag}"
    typer.secho(
        f"Building {full_image} (context={context}) [BuildKit]",
        fg=typer.colors.GREEN,
    )

    task_filename = f".acr-task-{uuid.uuid4().hex}.yaml"
    task_path = context / task_filename
    task_path.write_text(
        dedent(
            f"""
            version: v1.1.0
            stepTimeout: {timeout}
            steps:
              - build: >-
                  -t {full_image} .
                env:
                  - DOCKER_BUILDKIT=1
              - push:
                - "{full_image}"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    cmd = [
        "az",
        "acr",
        "run",
        "--registry",
        registry,
        "--file",
        task_filename,
        "--timeout",
        str(timeout),
        ".",
    ]
    try:
        proc = subprocess.run(cmd, check=False, cwd=str(context))
    finally:
        with contextlib.suppress(FileNotFoundError):
            task_path.unlink()

    if proc.returncode != 0:
        typer.secho(
            f"az acr run failed (exit {proc.returncode})",
            fg=typer.colors.RED,
            err=True,
        )
        return 4
    typer.secho(f"Image pushed: {full_image}", fg=typer.colors.CYAN)
    return 0


def _layer_vscode_and_build(
    acr_name: str,
    image: str,
    base_full_image: str,
    target_tag: str,
    timeout: int = 7200,
    login_server: str = "",
) -> int:
    """Layer VS Code CLI onto a base image and push to ACR."""
    with tempfile.TemporaryDirectory(prefix="vscode-layer-") as td:
        temp_ctx = Path(td)
        wrapper = prepare_vscode_layer(base_full_image, temp_ctx)
        typer.secho(
            f"Layering VS Code CLI onto {base_full_image} (temp context={temp_ctx})"
            + (" with CMD wrapper" if wrapper else ""),
            fg=typer.colors.GREEN,
        )
        return build_image(acr_name, image, target_tag, temp_ctx, timeout, login_server)


def execute_build(
    context: Path = Path("."),
    image: str = DEFAULT_IMAGE,
    tag: str = DEFAULT_TAG,
    acr_name: str = "",
    vscode: bool = False,
    timeout: int = 7200,
    login_server: str = "",
):
    """Build & push an image to a pre-configured ACR.

    Expects `ACR_NAME` to be present in the provided env file (takes precedence)
    or in the process environment. Discovery/interactive selection has been
    moved to the global `configure` command.

    Args:
        context: Docker build context directory for the base image.
        image: Repository/image name (without registry hostname).
        tag: Image tag to use.
        vscode: When True, perform a second build layering the VS Code CLI binary
            into the final image at /usr/local/bin/code (reusing same tag).
        login_server: ACR login server (e.g. ``myacr.azurecr.io``).  When empty,
            falls back to ``{acr_name}.azurecr.io``.

    Exit codes:
        0 success (or user abort)
        2 configuration error (missing ACR_NAME)
        3 registry not found/inaccessible
        4 az cli invocation failure
    """
    ensure_az_cli()

    # Only validate existence when we have a candidate
    if not acr_registry_exists(acr_name):
        typer.secho(
            f"Registry '{acr_name}' not found or inaccessible",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(3)

    # Strip tag from image name if the user included one (e.g. "myimage:latest")
    if ":" in image:
        image, embedded_tag = image.rsplit(":", 1)
        if tag == "latest" and embedded_tag:
            tag = embedded_tag

    effective_server = login_server or f"{acr_name}.azurecr.io"
    full_image = f"{effective_server}/{image}:{tag}"

    # Display commands that will be executed
    typer.echo("\nThe following commands will be executed:\n")
    if vscode:
        temp_tag = tag + "-temp"
        temp_image = f"{effective_server}/{image}:{temp_tag}"
        typer.secho("1. Base image build:", fg=typer.colors.CYAN, bold=True)
        typer.echo(f"   az acr run --registry {acr_name} --file <task.yaml> {context}")
        typer.echo(f"   → {temp_image}")
        typer.secho("\n2. Layer VS Code CLI:", fg=typer.colors.CYAN, bold=True)
        typer.echo(f"   az acr run --registry {acr_name} --file <task.yaml> <temp_context>")
        typer.echo(f"   → {full_image}")
    else:
        typer.secho("1. Image build:", fg=typer.colors.CYAN, bold=True)
        typer.echo(f"   az acr run --registry {acr_name} --file <task.yaml> {context}")
        typer.echo(f"   → {full_image}")

    # Prompt for confirmation
    typer.echo()
    if not typer.confirm("Continue with build?", default=True):
        typer.secho("Build cancelled.", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    if vscode:
        final_tag = tag
        tag = tag + "-temp"
    else:
        final_tag = tag
    # Phase 1: base image build
    rc = build_image(acr_name, image, tag, context, timeout, login_server)
    if rc != 0:
        raise typer.Exit(rc)

    if vscode:
        # Phase 2: create temporary context layering VS Code CLI
        base_full_image = f"{effective_server}/{image}:{tag}"
        rc2 = _layer_vscode_and_build(
            acr_name, image, base_full_image, final_tag, timeout, login_server
        )
        if rc2 != 0:
            raise typer.Exit(rc2)

    return 0


def execute_rebuild(
    image: str,
    tag: str,
    acr_name: str,
    target_image: str | None = None,
    target_tag: str | None = None,
    timeout: int = 7200,
    login_server: str = "",
) -> int:
    """Layer VS Code CLI onto an existing ACR image.

    Args:
        image: Repository/image name.
        tag: Existing image tag.
        acr_name: Name of the ACR registry.
        target_image: Optional target repository name. If None, uses `image`.
        target_tag: Optional new tag for the output image. If None, overwrites `tag`.
        login_server: ACR login server.  Falls back to ``{acr_name}.azurecr.io``.
    """
    ensure_az_cli()

    if not acr_registry_exists(acr_name):
        typer.secho(
            f"Registry '{acr_name}' not found or inaccessible",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(3)

    # Strip tag from image name if the user included one (e.g. "myimage:latest")
    if ":" in image:
        image, embedded_tag = image.rsplit(":", 1)
        if tag == "latest" and embedded_tag:
            tag = embedded_tag

    effective_server = login_server or f"{acr_name}.azurecr.io"
    base_full_image = f"{effective_server}/{image}:{tag}"
    final_image = target_image if target_image else image
    final_tag = target_tag if target_tag else tag
    final_full_image = f"{effective_server}/{final_image}:{final_tag}"

    typer.secho("Layering VS Code CLI:", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"   Base:   {base_full_image}")
    typer.echo(f"   Target: {final_full_image}")

    if not typer.confirm("Continue with rebuild?", default=True):
        typer.secho("Rebuild cancelled.", fg=typer.colors.YELLOW)
        raise typer.Exit(0)

    return _layer_vscode_and_build(acr_name, final_image, base_full_image, final_tag, timeout, login_server)
