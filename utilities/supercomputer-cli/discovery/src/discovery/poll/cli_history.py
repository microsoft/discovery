"""``discovery job history`` — view and manage the local submit history.

This is a *local* command: it reads ``~/.discovery/job-history.jsonl``
and does not touch the Discovery service. Use it to remember what you
submitted earlier (even across days), to find an operation ID after
the service-side list has rolled over, or to wipe the history.
"""

from __future__ import annotations

import socket
from datetime import datetime, timedelta, timezone

import typer
from rich.console import Console
from rich.table import Table

from discovery.common.job_history import (
    JobHistoryEntry,
    clear,
    history_path,
    load_history,
)
from discovery.common.logging import info
from discovery.poll.cli_helpers import get_config_file_path, load_project_config


app = typer.Typer(help="View and manage the local job-submit history")
console = Console()

EXIT_OK = 0
EXIT_BAD_USAGE = 2

MODE_STYLES = {
    "start": "cyan",
    "batch": "magenta",
    "vscode": "green",
}


def _parse_since(value: str) -> datetime:
    """Parse ``--since`` value: either ``YYYY-MM-DD`` or ``<N><unit>`` shorthand.

    Supported shorthand units: ``h`` (hours), ``d`` (days), ``w`` (weeks).
    Examples: ``24h``, ``7d``, ``2w``.
    """
    value = value.strip()
    now = datetime.now(tz=timezone.utc)
    if len(value) >= 2 and value[:-1].isdigit() and value[-1] in {"h", "d", "w"}:
        n = int(value[:-1])
        unit = value[-1]
        if unit == "h":
            return now - timedelta(hours=n)
        if unit == "d":
            return now - timedelta(days=n)
        return now - timedelta(weeks=n)
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        msg = f"Invalid --since value: {value!r}. Expected YYYY-MM-DD, '24h', '7d', or '2w'."
        raise typer.BadParameter(msg) from exc


def _truncate(value: str, *, width: int) -> str:
    """Truncate ``value`` to ``width`` chars with a trailing ellipsis."""
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return value[: width - 1] + "…"


def _format_relative(ts: datetime) -> str:
    """Format ``ts`` as ``5m ago`` / ``2h ago`` / ``YYYY-MM-DD HH:MM``."""
    now = datetime.now(tz=timezone.utc)
    delta = now - ts
    if delta < timedelta(seconds=0):
        return ts.isoformat()
    if delta < timedelta(minutes=1):
        return f"{int(delta.total_seconds())}s ago"
    if delta < timedelta(hours=1):
        return f"{int(delta.total_seconds() // 60)}m ago"
    if delta < timedelta(days=1):
        return f"{int(delta.total_seconds() // 3600)}h ago"
    if delta < timedelta(days=14):
        return f"{int(delta.total_seconds() // 86400)}d ago"
    return ts.astimezone().strftime("%Y-%m-%d %H:%M")


def _render_table(entries: list[JobHistoryEntry]) -> None:
    """Render entries as a Rich table (newest first)."""
    table = Table(
        show_header=True,
        header_style="bold cyan",
        expand=True,
        show_lines=False,
    )
    table.add_column("Operation ID", style="white", no_wrap=True)
    table.add_column("Submitted", no_wrap=True, width=18)
    table.add_column("Mode", no_wrap=True, width=7)
    table.add_column("Project", no_wrap=True, max_width=24, overflow="ellipsis")
    table.add_column("Host", no_wrap=True, max_width=18, overflow="ellipsis")
    table.add_column("Command", overflow="ellipsis")

    for entry in entries:
        try:
            ts = datetime.fromisoformat(entry.submitted_at.replace("Z", "+00:00"))
            ts_str = _format_relative(ts)
        except ValueError:
            ts_str = entry.submitted_at
        mode_style = MODE_STYLES.get(entry.mode, "white")
        table.add_row(
            entry.operation_id,
            ts_str,
            f"[{mode_style}]{entry.mode}[/{mode_style}]",
            entry.project_name or "—",
            entry.hostname or "—",
            _truncate(entry.command or "—", width=80),
        )
    console.print(table)


@app.command(name="history")
def history_command(
    limit: int = typer.Option(
        50, "--limit", "-n", help="Show the most recent N entries (default: 50)."
    ),
    since: str = typer.Option(
        "",
        "--since",
        help=(
            "Only show entries from on/after this point. Accepts YYYY-MM-DD or "
            "shorthand like '24h', '7d', '2w'."
        ),
    ),
    workspace: bool = typer.Option(
        True,
        "--workspace/--all-workspaces",
        help=(
            "Restrict to entries that match the current workspace_url (default). "
            "Pass --all-workspaces to see every recorded submission."
        ),
    ),
    this_host_only: bool = typer.Option(
        False,
        "--this-host",
        help="Only show entries recorded on this machine.",
    ),
    show_path: bool = typer.Option(
        False, "--path", help="Print the history file path and exit."
    ),
    clear_all: bool = typer.Option(
        False, "--clear", help="Delete the entire history file and exit."
    ),
) -> None:
    """List, locate, or wipe the local job-submit history."""
    if show_path:
        console.print(str(history_path()))
        raise typer.Exit(code=EXIT_OK)

    if clear_all:
        if not typer.confirm(
            f"Delete {history_path()} and forget all locally-recorded jobs?",
            default=False,
        ):
            raise typer.Exit(code=EXIT_OK)
        removed = clear()
        info(f"Removed {removed} history entr{'y' if removed == 1 else 'ies'}.")
        raise typer.Exit(code=EXIT_OK)

    workspace_url: str | None = None
    if workspace:
        try:
            env_cfg = load_project_config(get_config_file_path())
            workspace_url = env_cfg.workspace_url or None
        except Exception:
            workspace_url = None

    since_dt = _parse_since(since) if since else None

    hostname_filter: str | None = None
    if this_host_only:
        try:
            hostname_filter = socket.gethostname()
        except OSError:
            hostname_filter = None

    entries = load_history(
        workspace_url=workspace_url,
        hostname=hostname_filter,
        since=since_dt,
    )

    if not entries:
        path = history_path()
        info(
            f"No local job-history entries found at {path}. "
            "Submit a job with `discovery job start` first."
        )
        raise typer.Exit(code=EXIT_OK)

    # Newest first, then truncated by --limit
    entries_sorted = sorted(entries, key=lambda e: e.submitted_at, reverse=True)
    if limit > 0:
        entries_sorted = entries_sorted[:limit]

    _render_table(entries_sorted)
    console.print(
        f"\n[dim]{len(entries_sorted)} of {len(entries)} matching entries · "
        f"file: {history_path()}[/dim]"
    )


__all__ = ["app", "history_command"]
