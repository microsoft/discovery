"""``discovery update`` — check for and install CLI updates.

Mirrors the GitHub Copilot CLI's ``/update`` command. The command is a
thin Typer wrapper around helpers in :mod:`discovery.common.auto_update`.

Usage:
    discovery update              # check + interactive install
    discovery update --check      # check only; never install
    discovery update -y           # install without confirmation
    discovery update --disable    # turn off automatic background checks
    discovery update --enable     # turn them back on
"""

from __future__ import annotations

import typer
from rich.console import Console

from discovery._version import get_build_commit, get_version_string
from discovery.common.auto_update import (
    UPGRADE_COMMAND,
    UpdateInfo,
    UpgradeError,
    fetch_update_info,
    install_update,
    is_opted_out,
    load_cache,
    save_cache,
    set_disabled,
)


app = typer.Typer(help="Check for and install Discovery CLI updates")
console = Console()


EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_BAD_USAGE = 2
EXIT_NETWORK = 3


def _emit_status_line() -> None:
    """Print the one-line "current version" header used by all subcommands."""
    console.print(f"Current version: [cyan]{get_version_string()}[/cyan]")


def _handle_toggles(*, enable: bool, disable: bool) -> None:
    """Apply --enable/--disable; exit early when either flag is set."""
    if enable and disable:
        console.print("[red]--enable and --disable are mutually exclusive.[/red]")
        raise typer.Exit(code=EXIT_BAD_USAGE)
    if disable:
        set_disabled(True)
        console.print(
            "[yellow]Automatic update checks disabled.[/yellow] "
            "Re-enable with `discovery update --enable`."
        )
        raise typer.Exit(code=EXIT_OK)
    if enable:
        set_disabled(False)
        console.print("[green]Automatic update checks re-enabled.[/green]")
        raise typer.Exit(code=EXIT_OK)


def _report_up_to_date(current: str, info: UpdateInfo) -> None:
    """Print 'up to date' and refresh the cache baseline."""
    console.print(f"[green]You are on the latest version[/green] ({current}).")
    state = load_cache()
    state.latest_commit = info.latest_commit
    state.latest_commit_date = info.latest_commit_date or None
    state.current_at_check = current
    state.notified_commit = None
    save_cache(state)


def _report_available(current: str, info: UpdateInfo) -> None:
    """Print the 'update available' summary lines."""
    date_part = ""
    if info.latest_commit_date:
        date_part = f" ({info.latest_commit_date.split('T')[0]})"
    console.print(
        f"Update available: [green]{info.latest_commit}[/green]{date_part}"
    )
    console.print(f"Installed:      [cyan]{current}[/cyan]")


def _apply_install(latest_commit: str) -> None:
    """Run ``uv tool upgrade discovery`` and baseline the cache on success."""
    try:
        rc = install_update()
    except UpgradeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=EXIT_FAILURE) from exc
    if rc != 0:
        console.print(
            f"[red]`{UPGRADE_COMMAND}` exited with status {rc}.[/red]"
        )
        raise typer.Exit(code=rc)
    state = load_cache()
    state.notified_commit = latest_commit
    state.current_at_check = latest_commit
    save_cache(state)
    console.print(
        "[bold green]✓ Discovery CLI upgraded.[/bold green] "
        "Re-run your command to pick up the new version."
    )


@app.command(name="update")
def update_command(
    check: bool = typer.Option(
        False,
        "--check",
        help="Only check for updates; do not install even if one is available.",
    ),
    enable: bool = typer.Option(
        False,
        "--enable",
        help="Re-enable automatic background update checks.",
    ),
    disable: bool = typer.Option(
        False,
        "--disable",
        help="Disable automatic background update checks (persists across runs).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Apply the update without an interactive confirmation prompt.",
    ),
) -> None:
    """Check for a newer Discovery CLI release and optionally install it.

    The check hits the GitHub compare API for the
    ``microsoft/discovery`` repository's ``main`` branch and reports an
    update only when the CLI subdirectory has actually changed since the
    installed build.
    """
    _handle_toggles(enable=enable, disable=disable)

    _emit_status_line()

    if is_opted_out():
        console.print(
            "[yellow]Note:[/yellow] background checks are disabled but a "
            "manual check will still run."
        )

    console.print("Checking for updates…")
    current = get_build_commit()
    info = fetch_update_info(current)

    if info is None:
        console.print(
            "[red]Could not reach GitHub.[/red] The `microsoft/discovery` "
            "repository is private, so the update check requires a token. "
            "Try [bold]`gh auth login`[/bold] or set `GITHUB_TOKEN` and rerun."
        )
        raise typer.Exit(code=EXIT_NETWORK)

    if not info.update_available:
        _report_up_to_date(current, info)
        raise typer.Exit(code=EXIT_OK)

    _report_available(current, info)

    if check:
        console.print("Run `discovery update` to install.")
        raise typer.Exit(code=EXIT_OK)

    if not yes and not typer.confirm(
        f"Install now via `{UPGRADE_COMMAND}`?", default=True
    ):
        console.print("[dim]Upgrade skipped.[/dim]")
        raise typer.Exit(code=EXIT_OK)

    _apply_install(info.latest_commit)


__all__ = ["app", "update_command"]
