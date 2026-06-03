"""Typer-based CLI exposing polling utilities in `poll.py`.

Commands:
    start  -> start tool run and wait for completion; outputs operation id
    poll   -> poll existing operation id until terminal state

Configuration:
    Settings are auto-persisted to ~/.discovery-sc-config when first configured

Exit Codes:
  0 success (terminal succeeded)
  1 general failure (error or terminal failed)
  2 canceled (terminal canceled)
  3 connection/HTTP transient error (retry exhaustion)

Note: Azure CLI (`az`) must be authenticated; token acquisition uses `az account get-access-token`.
"""

from __future__ import annotations

import atexit

import typer

from discovery._version import get_version_string
from discovery.common.auto_update import maybe_notify, schedule_check
from discovery.common.logging import set_level

# Re-export from build_acr_task for tests
from . import build_acr_task as acr  # noqa: F401

# Re-export for tests
from .cli_build import (  # noqa: F401
    _ensure_data_assets_and_containers,
    _load_acr_config,
)
from .cli_build import app as build_app
from .cli_cleanup import app as cleanup_app
from .cli_configure import app as configure_app
from .cli_debug import app as debug_app
from .cli_doctor import app as doctor_app

# Re-export helpers for backward compatibility with tests
from .cli_helpers import (  # noqa: F401
    emit_env as _emit_env,
)
from .cli_history import app as history_app
from .cli_smoke import app as smoke_test_app
from .cli_status import app as status_app
from .cli_storage import app as storage_app
from .cli_submit import app as submit_app
from .cli_update import app as update_app

# Re-export API functions for tests
from .dataplane_api import (  # noqa: F401
    cancel_operation,
    connect_debug_container,
    get_compute_status,
    get_operation_status,
    list_operations,
    run_and_poll,
    start_tool_run,
)


app = typer.Typer(help="Discovery Supercomputer CLI")

# Command groups
blob_app = typer.Typer(help="Blob storage commands (upload, download, list, remove)")
job_app = typer.Typer(help="Job commands (submit, status, list, cancel)")
build_group_app = typer.Typer(help="Build commands (build, rebuild)")
smoke_app = typer.Typer(help="Smoke tests for supercomputer API")

app.add_typer(blob_app, name="blob")
app.add_typer(job_app, name="job")
app.add_typer(build_group_app, name="build")
app.add_typer(smoke_app, name="smoke")

set_level("INFO")


def _arm_auto_update() -> None:
    """Schedule a background update check and queue an at-exit notice.

    Extracted so it can be invoked from both the root callback and the
    eager ``--version`` handler — Typer raises ``typer.Exit`` from eager
    callbacks before the main callback body has a chance to run, which
    would otherwise suppress notifications for users who only run
    ``discovery --version``.
    """
    schedule_check()
    atexit.register(maybe_notify)


def _version_callback(value: bool) -> None:
    """Print version and exit when --version is passed."""
    if value:
        _arm_auto_update()
        typer.echo(f"discovery {get_version_string()}")
        raise typer.Exit()


@app.callback()
def _root_callback(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose (debug) logging globally for the invocation",
    ),
    _version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
) -> None:
    """Global options applied before any subcommand executes."""
    if verbose:
        set_level("DEBUG")
    # Auto-update: spawn a daemon thread to refresh the cache when stale
    # and queue a notification for after the command finishes. Both are
    # no-ops when opted out, when not installed via ``uv tool``, or when
    # the cache is already fresh.
    _arm_auto_update()

# Register configure command
app.command(name="configure")(configure_app.registered_commands[0].callback)

# Register doctor command
app.command(name="doctor")(doctor_app.registered_commands[0].callback)

# Register update command
app.command(name="update")(update_app.registered_commands[0].callback)

# ---------------------------------------------------------------------------
# Command groups (alternative organization)
# ---------------------------------------------------------------------------

# 'blob' group - storage commands
blob_app.command(name="upload")(storage_app.registered_commands[0].callback)
blob_app.command(name="up")(storage_app.registered_commands[0].callback)
blob_app.command(name="download")(storage_app.registered_commands[1].callback)
blob_app.command(name="down")(storage_app.registered_commands[1].callback)
blob_app.command(name="ls")(storage_app.registered_commands[2].callback)
blob_app.command(name="remove")(storage_app.registered_commands[3].callback)
blob_app.command(name="rm")(storage_app.registered_commands[3].callback)
blob_app.command(name="url")(storage_app.registered_commands[4].callback)
blob_app.command(name="create-user-storage")(storage_app.registered_commands[5].callback)

# 'job' group - submit and status commands
job_app.command(name="start")(submit_app.registered_commands[0].callback)
job_app.command(name="batch")(submit_app.registered_commands[1].callback)
job_app.command(name="vscode")(submit_app.registered_commands[2].callback)
job_app.command(name="cancel")(submit_app.registered_commands[3].callback)
job_app.command(name="debug")(debug_app.registered_commands[0].callback)
job_app.command(name="running")(status_app.registered_commands[0].callback)
job_app.command(name="pending")(status_app.registered_commands[1].callback)
job_app.command(name="done")(status_app.registered_commands[2].callback)
job_app.command(name="list")(status_app.registered_commands[3].callback)
job_app.command(name="status")(status_app.registered_commands[4].callback)
job_app.command(name="pools")(status_app.registered_commands[5].callback)
job_app.command(name="cleanup-anf")(cleanup_app.registered_commands[0].callback)
job_app.command(name="history")(history_app.registered_commands[0].callback)

# 'build' group - build commands
build_group_app.command(name="image")(build_app.registered_commands[0].callback)
build_group_app.command(name="rebuild")(build_app.registered_commands[1].callback)

# 'smoke' group - load testing commands
smoke_app.command(name="load")(smoke_test_app.registered_commands[0].callback)


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
