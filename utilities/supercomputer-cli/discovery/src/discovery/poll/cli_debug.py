"""CLI command for starting a debug session on a running operation."""

from __future__ import annotations

import httpx
import typer

from discovery.common.logging import debug, error, info, success

from .cli_helpers import emit_env, format_service_error, get_config_file_path, load_project_config
from .dataplane_api import PollError, connect_debug_container

app = typer.Typer()


@app.command()
def debug_command(
    operation_id: str = typer.Argument(..., help="Operation ID of a running job to debug"),
    pod: int = typer.Option(0, "--pod", "-p", help="Pod index to debug (0=leader/main, 1+=workers). Use 'job status' to see available pods."),
) -> None:
    """Start a debug session on a running operation.

    Creates a Dev Tunnel on your behalf and attaches a VS Code debug container
    to the running job. The tunnel appears in your VS Code Remote Tunnels list.

    Example:
        discovery job debug abc12345-def6-7890-abcd-ef1234567890
        discovery job debug abc12345-def6-7890-abcd-ef1234567890 --pod 2
    """
    debug("debug_command(): entering")
    env_cfg = load_project_config(get_config_file_path())
    emit_env(env_cfg)

    info(f"Starting debug session for operation {operation_id} (pod {pod})...")

    try:
        result = connect_debug_container(
            project_name=env_cfg.project_name,
            operation_id=operation_id,
            workspace_url=env_cfg.workspace_url,
            pod_index=pod,
        )
    except httpx.HTTPStatusError as exc:
        error(format_service_error(exc))
        raise typer.Exit(code=1) from exc
    except httpx.TransportError as exc:
        error(f"Network error (retries exhausted): {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc
    except PollError as exc:
        error(f"Failed to start debug session: {exc}")
        raise typer.Exit(code=1) from exc

    tunnel_id = result.get("tunnelId", "unknown")
    session_id = result.get("debugSessionId", "unknown")
    status = result.get("status", "unknown")

    success("Debug session created!")
    info(f"  Tunnel ID:    {tunnel_id}")
    info(f"  Session ID:   {session_id}")
    info(f"  Status:       {status}")
    info("")
    info("Connect via VS Code:")
    info(f"  1. Open VS Code")
    info(f"  2. Go to Remote Explorer → Tunnels")
    info(f'  3. Find "{tunnel_id}" and click Connect')
