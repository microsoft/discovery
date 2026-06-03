"""``discovery job history`` — view and manage the local submit history.

This is primarily a *local* command: it reads
``~/.discovery/job-history.jsonl`` and does not touch the Discovery
service. Use it to remember what you submitted earlier (even across
days), to find an operation ID after the service-side list has rolled
over, or to wipe the history.

Pass ``--status`` to additionally fetch each entry's current status
and computed runtime from the API in parallel.
"""

from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import typer
from rich.console import Console
from rich.table import Table

from discovery.common.job_history import (
    JobHistoryEntry,
    clear,
    history_path,
    load_history,
    parse_since,
)
from discovery.common.logging import debug, info
from discovery.poll.cli_helpers import get_config_file_path, load_project_config
from discovery.poll.dataplane_api import get_operation_status


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
    """Wrapper that converts :class:`ValueError` to ``typer.BadParameter``."""
    try:
        return parse_since(value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


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


def _format_duration(td: timedelta, *, in_progress: bool = False) -> str:
    """Format ``td`` as ``2h 30m`` / ``45s`` / ``3d 5h``.

    Mirrors :func:`discovery.poll.cli_status._format_duration` semantics
    so the runtime values line up between ``discovery job list`` and
    ``discovery job history --status``.
    """
    total = int(td.total_seconds())
    if total < 0:
        return "0s"
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    out = " ".join(parts[:2])
    return out + "+" if in_progress else out


# Status categories returned from :func:`get_operation_status` carry
# both a top-level lifecycle string and a per-execution result with
# timing. We collapse them into a tiny snapshot dataclass so the
# renderer doesn't have to know about the API shape.
@dataclass
class _StatusSnapshot:
    """Live status + runtime for one entry, or an explanatory error tag."""

    status: str = ""
    runtime: str = ""
    style: str = "white"


# Color / style hints for the rendered status cell. Keys are the
# lowercased status string returned by the API; values are Rich style
# specs.
_STATUS_STYLES: dict[str, str] = {
    "succeeded": "green",
    "completed": "green",
    "running": "cyan",
    "active": "cyan",
    "pending": "yellow",
    "notstarted": "yellow",
    "accepted": "yellow",
    "failed": "red",
    "canceled": "magenta",
    "cancelled": "magenta",
    "expired": "dim",
    "?": "dim",
}


def _snapshot_from_response(resp) -> _StatusSnapshot:
    """Build a :class:`_StatusSnapshot` from a ``ToolExecutionResponse``."""
    raw_status = (resp.status or "").strip() or "?"
    style = _STATUS_STYLES.get(raw_status.lower(), "white")
    result = resp.result
    runtime = ""
    if result and result.created_at:
        end = result.completed_at or datetime.now(tz=timezone.utc)
        in_progress = result.completed_at is None
        runtime = _format_duration(end - result.created_at, in_progress=in_progress)
    return _StatusSnapshot(status=raw_status, runtime=runtime, style=style)


def _classify_status_error(op_id: str, exc: httpx.HTTPStatusError) -> _StatusSnapshot:
    """Map an HTTP error to a snapshot tag."""
    code = getattr(getattr(exc, "response", None), "status_code", None)
    if code == 404:
        return _StatusSnapshot(status="expired", style=_STATUS_STYLES["expired"])
    debug(f"history --status: HTTP {code} for {op_id}")
    return _StatusSnapshot(status="?", style=_STATUS_STYLES["?"])


def _fetch_status_snapshots(
    env_cfg,
    entries: list[JobHistoryEntry],
    *,
    workers: int = 16,
) -> dict[str, _StatusSnapshot]:
    """Parallel-fetch live status for ``entries``; never raise.

    Each lookup is independent so failures (404, network, etc.) only
    affect that one row — the rest of the table renders normally with
    a tagged status cell.
    """
    if not entries:
        return {}
    pool_size = max(1, min(workers, len(entries)))

    def _one(op_id: str) -> tuple[str, _StatusSnapshot]:
        try:
            resp = get_operation_status(
                env_cfg.project_name,
                op_id,
                env_cfg.workspace_url,
                api_version=env_cfg.api_version,
            )
        except httpx.HTTPStatusError as exc:
            return op_id, _classify_status_error(op_id, exc)
        except Exception as exc:  # network / timeout / parse
            debug(f"history --status: lookup failed for {op_id}: {exc}")
            return op_id, _StatusSnapshot(
                status="?", style=_STATUS_STYLES["?"]
            )
        return op_id, _snapshot_from_response(resp)

    out: dict[str, _StatusSnapshot] = {}
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        for op_id, snap in pool.map(_one, [e.operation_id for e in entries]):
            out[op_id] = snap
    return out


def _render_table(
    entries: list[JobHistoryEntry],
    *,
    status_map: dict[str, _StatusSnapshot] | None = None,
) -> None:
    """Render entries as a Rich table (newest first).

    When ``status_map`` is supplied, two extra columns (Status,
    Runtime) are appended with live values fetched from the API.
    """
    table = Table(
        show_header=True,
        header_style="bold cyan",
        expand=True,
        show_lines=False,
    )
    table.add_column("Operation ID", style="white", no_wrap=True)
    table.add_column("Submitted", no_wrap=True, width=18)
    if status_map is not None:
        table.add_column("Status", no_wrap=True, width=10)
        table.add_column("Runtime", no_wrap=True, width=9)
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
        cells: list[str] = [entry.operation_id, ts_str]
        if status_map is not None:
            snap = status_map.get(entry.operation_id) or _StatusSnapshot(
                status="?", style=_STATUS_STYLES["?"]
            )
            cells.append(f"[{snap.style}]{snap.status}[/{snap.style}]")
            cells.append(snap.runtime or "—")
        cells.extend(
            [
                f"[{mode_style}]{entry.mode}[/{mode_style}]",
                entry.project_name or "—",
                entry.hostname or "—",
                _truncate(entry.command or "—", width=80),
            ]
        )
        table.add_row(*cells)
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
    status: bool = typer.Option(
        False,
        "--status",
        "-s",
        help=(
            "Fetch each entry's current status and computed runtime "
            "from the Discovery service. Adds two columns to the "
            "output; one HTTP call per entry (parallelized). Without "
            "this flag the command stays fully offline."
        ),
    ),
    status_workers: int = typer.Option(
        16,
        "--status-workers",
        help="Parallel workers when --status is set (default: 16).",
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

    # When --status is set we always need an env_cfg for the API calls.
    # Otherwise we only load it if the user wants workspace scoping
    # (and tolerate failure so pure offline use still works).
    env_cfg = None
    workspace_url: str | None = None
    if status or workspace:
        try:
            env_cfg = load_project_config(get_config_file_path())
            workspace_url = env_cfg.workspace_url or None
        except Exception:
            env_cfg = None
            workspace_url = None
    if not workspace:
        workspace_url = None

    if status and env_cfg is None:
        info(
            "[red]--status requires a configured workspace[/red] "
            "(run `discovery configure` first)."
        )
        raise typer.Exit(code=EXIT_BAD_USAGE)

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

    status_map: dict[str, _StatusSnapshot] | None = None
    if status:
        info(
            f"Fetching live status for {len(entries_sorted)} entr"
            f"{'y' if len(entries_sorted) == 1 else 'ies'} "
            f"(parallel x {min(status_workers, len(entries_sorted))})…"
        )
        status_map = _fetch_status_snapshots(
            env_cfg, entries_sorted, workers=status_workers
        )

    _render_table(entries_sorted, status_map=status_map)
    console.print(
        f"\n[dim]{len(entries_sorted)} of {len(entries)} matching entries · "
        f"file: {history_path()}[/dim]"
    )


__all__ = ["app", "history_command"]
