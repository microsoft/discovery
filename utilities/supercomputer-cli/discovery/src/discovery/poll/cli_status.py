"""Status-related CLI commands: running, pending, done, list, status."""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.table import Table

from discovery.common.job_history import (
    load_history,
    local_operation_ids,
)
from discovery.common.logging import debug, error, info
from discovery.poll.models.tool_response import AzureCoreOperationState

from .cli_helpers import (
    emit_env,
    get_config_file_path,
    load_project_config,
    render_error_with_details,
)
from .dataplane_api import (
    OperationNotFoundError,
    get_compute_status,
    get_operation_pods,
    get_operation_status,
    list_operations,
    list_operations_page,
)


app = typer.Typer()


def _format_duration(td: timedelta, in_progress: bool = False) -> str:
    """Format a timedelta as a compact human-readable string.

    Uses the two most significant non-zero units for readability.
    Appends '+' suffix for in-progress jobs to indicate the duration is still growing.
    """
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        return "0s"

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")

    # Show at most two units for compactness
    result = " ".join(parts[:2])
    if in_progress:
        result += "+"
    return result


def _mine_ids_or_hint(env_cfg) -> set[str] | None:
    """Return the local-history operation IDs for the current workspace.

    Returns ``None`` (and prints a one-line hint) when the local
    history is empty, so callers can degrade to "no matches" without
    error-exiting. ``None`` means "no filter possible" — the caller
    typically converts that to a no-results outcome with guidance to
    pass ``--all``.
    """
    ids = local_operation_ids(workspace_url=env_cfg.workspace_url)
    if not ids:
        info(
            "No locally-recorded jobs found for this workspace yet. "
            "Submit a job with `discovery job start` first, or pass "
            "[bold]--all[/bold] to see everyone's jobs."
        )
        return None
    return ids


def _oldest_mine_submission(env_cfg, *, slack: timedelta = timedelta(hours=1)) -> datetime | None:
    """Return ``min(submitted_at)`` across local history for this workspace.

    Used as a ``not_before`` cutoff for the paginator: operations older
    than this are guaranteed not to be in the local history (since they
    would have to predate the very first job we ever recorded here).

    A small ``slack`` is subtracted to account for clock skew between
    the local machine and the Discovery service — better to scan one
    extra op than to incorrectly skip a match.
    """
    entries = load_history(workspace_url=env_cfg.workspace_url)
    timestamps: list[datetime] = []
    for entry in entries:
        if not entry.submitted_at:
            continue
        try:
            ts = datetime.fromisoformat(entry.submitted_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        timestamps.append(ts)
    if not timestamps:
        return None
    return min(timestamps) - slack


@app.command("running")
def list_running(
    limit: int = typer.Option(1000, "--limit", "-n", help="Limit results to search"),
    all_jobs: bool = typer.Option(
        False,
        "--all",
        "-a",
        help=(
            "Show every running operation in the workspace, not just those "
            "submitted from this machine."
        ),
    ),
) -> None:
    """List running operations.

    By default only lists operations recorded in this machine's local
    job history (see ``discovery job history``). Pass ``--all`` to
    include jobs submitted by other people or from other machines.
    """
    env_cfg = load_project_config(get_config_file_path())
    emit_env(env_cfg)
    mine_ids = None if all_jobs else _mine_ids_or_hint(env_cfg)
    if not all_jobs and mine_ids is None:
        raise typer.Exit(code=0)
    _list_helper(
        status=(AzureCoreOperationState.RUNNING, AzureCoreOperationState.ACTIVE),
        limit=limit,
        env_cfg=env_cfg,
        mine_ids=mine_ids,
    )


@app.command("pending")
def list_queued(
    limit: int = typer.Option(1000, "--limit", "-n", help="Limit results to search"),
    all_jobs: bool = typer.Option(
        False,
        "--all",
        "-a",
        help=(
            "Show every queued operation in the workspace, not just those "
            "submitted from this machine."
        ),
    ),
) -> None:
    """List queued operations.

    By default only lists operations recorded in this machine's local
    job history (see ``discovery job history``). Pass ``--all`` to
    include jobs submitted by other people or from other machines.
    """
    env_cfg = load_project_config(get_config_file_path())
    emit_env(env_cfg)
    mine_ids = None if all_jobs else _mine_ids_or_hint(env_cfg)
    if not all_jobs and mine_ids is None:
        raise typer.Exit(code=0)
    _list_helper(
        status=(
            AzureCoreOperationState.NOT_STARTED,
            AzureCoreOperationState.PENDING,
            AzureCoreOperationState.ACCEPTED,
        ),
        limit=limit,
        env_cfg=env_cfg,
        mine_ids=mine_ids,
    )


@app.command("done")
def list_done(
    limit: int = typer.Option(200, "--limit", "-n", help="Limit results to search"),
    all_jobs: bool = typer.Option(
        False,
        "--all",
        "-a",
        help=(
            "Show every completed operation in the workspace, not just those "
            "submitted from this machine."
        ),
    ),
) -> None:
    """List successful and failed operations.

    By default only lists operations recorded in this machine's local
    job history. Pass ``--all`` to include jobs submitted by other
    people or from other machines.
    """
    env_cfg = load_project_config(get_config_file_path())
    emit_env(env_cfg)
    mine_ids = None if all_jobs else _mine_ids_or_hint(env_cfg)
    if not all_jobs and mine_ids is None:
        raise typer.Exit(code=0)
    _list_helper(
        status=(
            AzureCoreOperationState.FAILED,
            AzureCoreOperationState.SUCCEEDED,
            AzureCoreOperationState.CANCELED,
        ),
        limit=limit,
        env_cfg=env_cfg,
        mine_ids=mine_ids,
    )


@app.command("list")
def list_cmd(
    nodepool: str = typer.Option("", "--pool", help="Filter by nodepool"),
    user: str = typer.Option("", "--user", help="Filter by user (implies --all)"),
    date: str = typer.Option("", "--date", help="Filter by date (YYYY-MM-DD format)"),
    limit: int = typer.Option(200, "--limit", "-n", help="Limit results to search"),
    all_jobs: bool = typer.Option(
        False,
        "--all",
        "-a",
        help=(
            "Show every operation in the workspace, not just those submitted "
            "from this machine."
        ),
    ),
) -> None:
    """List recent operations.

    By default only lists operations recorded in this machine's local
    job history. Pass ``--all`` (or ``--user X`` to filter by a specific
    user) to see jobs from other people or other machines.
    """
    debug("list(): entering")
    env_cfg = load_project_config(get_config_file_path())
    emit_env(env_cfg)

    # ``--user X`` is an explicit cross-user query; implicitly skip the
    # local-history default so the user actually sees something.
    skip_mine = all_jobs or bool(user)
    mine_ids = None if skip_mine else _mine_ids_or_hint(env_cfg)
    if not skip_mine and mine_ids is None:
        raise typer.Exit(code=0)

    # Resolve --pool to a full resource ID so the filter matches op.nodepool_id
    resolved_pool = ""
    if nodepool:
        np_info = env_cfg.get_nodepool(nodepool)
        if np_info:
            resolved_pool = np_info.id
        elif nodepool.startswith("/"):
            resolved_pool = nodepool
        else:
            available = [np.qualified_name for np in env_cfg.nodepools]
            error(f"Nodepool '{nodepool}' not found. Available pools: {available}")
            raise typer.Exit(code=1)

    # Parse date filter if provided
    target_date = None
    if date:
        try:
            naive_date = datetime.strptime(date, "%Y-%m-%d")  # noqa: DTZ007
            target_date = naive_date.replace(tzinfo=datetime.now().astimezone().tzinfo)
        except ValueError:
            error(f"Invalid date format: {date}. Expected YYYY-MM-DD")
            raise typer.Exit(code=1) from None

    def matches_filters(op):
        if mine_ids is not None and op.id not in mine_ids:
            return False
        if user and op.created_by != user:
            return False
        if resolved_pool and op.nodepool_id != resolved_pool:
            return False
        if target_date:
            time_diff = abs(op.created_at - target_date)
            if time_diff > timedelta(hours=24):
                return False
        return True

    asyncio.run(
        _paginated_list(
            env_cfg=env_cfg,
            filter_fn=matches_filters,
            limit=limit,
            target_ids=mine_ids,
            not_before=_oldest_mine_submission(env_cfg) if mine_ids else None,
        )
    )


def _list_helper(
    status: Iterable[str],
    *,
    limit: int = 0,
    page_size: int = 0,
    env_cfg=None,
    mine_ids: set[str] | None = None,
) -> None:
    """Helper for listing operations by status with interactive pagination."""
    if env_cfg is None:
        env_cfg = load_project_config(get_config_file_path())
        emit_env(env_cfg)

    def matches_status(op):
        if op.status not in status:
            return False
        return not (mine_ids is not None and op.id not in mine_ids)

    asyncio.run(
        _paginated_list(
            env_cfg=env_cfg,
            filter_fn=matches_status,
            limit=limit,
            page_size=page_size,
            target_ids=mine_ids,
            not_before=(
                _oldest_mine_submission(env_cfg) if mine_ids else None
            ),
        )
    )


async def _paginated_list(
    env_cfg,
    filter_fn,
    limit: int = 0,
    page_size: int = 0,
    target_ids: set[str] | None = None,
    not_before: datetime | None = None,
) -> None:
    """Async implementation of paginated list.

    Fetches pages until page_size matching results are collected, then displays
    and asks user if they want to continue. Prefetches next page while waiting
    for user input to reduce perceived latency.

    Args:
        target_ids: When set, stop paginating as soon as every ID in
            this set has been matched. Caps the scan when the caller
            knows in advance the maximum possible result count (e.g.
            the local-history default filter, where mine_ids is the
            only thing that can match).
        not_before: When set, stop paginating as soon as we encounter
            an operation older than this timestamp. Listings come back
            newest-first, so anything past this point can't be a
            match. Naive datetimes are treated as UTC.
    """
    # Auto-detect page size from terminal height if not specified
    if page_size <= 0:
        term_height = shutil.get_terminal_size().lines
        # Reserve lines for: table header (3), table footer (1), info line (1),
        # prompt (1), and some buffer (2)
        page_size = max(1, term_height - 8)

    console = Console()
    total_displayed = 0
    batch_num = 1
    next_link: str | None = None
    api_pages_fetched = 0
    total_api_results = 0
    total_matches = 0
    earliest_time: datetime | None = None
    latest_time: datetime | None = None
    spinner: Status | None = None

    # Build nodepool ID -> friendly display name mapping
    pool_display: dict[str, str] = {}
    for np in getattr(env_cfg, "nodepools", []):
        display = np.qualified_name if np.supercomputer_name else np.name
        pool_display[np.id] = display
        pool_display[np.name] = display

    # Normalize ``not_before`` to UTC for safe comparison with op.created_at
    # (which is timezone-aware per the API model).
    if not_before is not None and not_before.tzinfo is None:
        not_before = not_before.replace(tzinfo=timezone.utc)

    # Track which target_ids we've already matched so we can stop paginating
    # the moment every locally-known ID has been seen.
    matches_seen: set[str] = set()
    early_exit = False

    def update_spinner() -> None:
        if spinner:
            spinner.update(
                f"Scanning operations... (page {api_pages_fetched}, {total_api_results} scanned, {total_matches} matches)"
            )

    # Fetch first API page
    try:
        result = await asyncio.to_thread(list_operations, env_cfg.project_name, env_cfg.workspace_url, api_version=env_cfg.api_version)
    except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
        error(
            f"Timeout fetching operations. The workspace may have too many jobs. "
            f"Try narrowing results with --limit, --pool, or --user.  ({exc})"
        )
        raise typer.Exit(code=1) from exc
    api_pages_fetched += 1
    # Track position within the current API page to avoid skipping results
    page_offset = 0

    while True:
        # Collect up to page_size matching results
        batch: list[tuple[str, str, str, str | None, str, str]] = []

        while len(batch) < page_size:
            # Check limit on total results searched
            if limit > 0 and total_api_results >= limit:
                break

            # Process current API page from where we left off
            while page_offset < len(result.values):
                if limit > 0 and total_api_results >= limit:
                    break
                op = result.values[page_offset]
                page_offset += 1
                total_api_results += 1
                # Track time window of all results
                if earliest_time is None or op.created_at < earliest_time:
                    earliest_time = op.created_at
                if latest_time is None or op.created_at > latest_time:
                    latest_time = op.created_at

                # Time-based early-exit: results are newest-first, so once
                # we cross ``not_before`` no later op can match.
                if not_before is not None and op.created_at < not_before:
                    early_exit = True
                    debug(
                        f"early-exit: op {op.id} is older than "
                        f"{not_before.isoformat()}; stopping scan"
                    )
                    break

                if filter_fn(op):
                    total_matches += 1
                    if target_ids is not None:
                        matches_seen.add(op.id)
                    local_time = op.created_at.astimezone()
                    formatted_time = local_time.strftime("%m-%d %H:%M")
                    completed_time = ""
                    if op.completed_at:
                        completed_time = op.completed_at.astimezone().strftime("%m-%d %H:%M")
                    # Compute runtime duration
                    if op.completed_at:
                        runtime_str = _format_duration(op.completed_at - op.created_at)
                    else:
                        runtime_str = _format_duration(
                            datetime.now(timezone.utc) - op.created_at,
                            in_progress=True,
                        )
                    # Resolve nodepool_id to friendly sc/pool name
                    raw_pool = op.nodepool_id or ""
                    pool_name = pool_display.get(raw_pool) or pool_display.get(raw_pool.split("/")[-1], raw_pool.split("/")[-1])
                    batch.append((op.id, formatted_time, completed_time, runtime_str, op.created_by, pool_name, op.status))

                    # ID-based early-exit: every target accounted for.
                    if target_ids is not None and matches_seen >= target_ids:
                        early_exit = True
                        debug(
                            f"early-exit: matched all {len(target_ids)} "
                            "target ids; stopping scan"
                        )
                        break

                    if len(batch) >= page_size:
                        break

            if early_exit:
                break

            # Need more results? Fetch next API page
            if len(batch) < page_size and result.next_link and (limit <= 0 or total_api_results < limit):
                # Start spinner when we need to fetch more pages
                if spinner is None:
                    spinner = console.status("Scanning operations...")
                    spinner.start()
                next_link = result.next_link
                try:
                    result = await asyncio.to_thread(list_operations_page, next_link)
                except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
                    if spinner:
                        spinner.stop()
                        spinner = None
                    error(
                        f"Timeout fetching page {api_pages_fetched + 1}. "
                        f"Scanned {total_api_results} operations, found {total_matches} matches so far. "
                        f"Try narrowing with --limit, --pool, or --user.  ({exc})"
                    )
                    raise typer.Exit(code=1) from exc
                api_pages_fetched += 1
                page_offset = 0
                update_spinner()
            else:
                next_link = result.next_link
                break

        # Stop spinner before displaying results
        if spinner:
            spinner.stop()
            spinner = None

        # Nothing to display
        if not batch:
            if total_displayed == 0:
                time_range = ""
                if earliest_time and latest_time:
                    earliest_local = earliest_time.astimezone().strftime("%Y-%m-%d %H:%M")
                    latest_local = latest_time.astimezone().strftime("%Y-%m-%d %H:%M")
                    time_range = f" ({earliest_local} to {latest_local})"
                typer.echo(f"No matching jobs found in latest {total_api_results} results{time_range}")
            break

        # Display collected results
        table = Table(title=f"Operations (Batch {batch_num})")
        table.add_column("Operation ID", style="cyan", no_wrap=True)
        table.add_column("Submitted", style="magenta")
        table.add_column("Completed", style="magenta")
        table.add_column("Runtime", style="bright_cyan")
        table.add_column("Owner", style="bright_black")
        table.add_column("Pool", style="yellow")
        table.add_column("Status", style="green")

        for row in batch:
            table.add_row(*row)

        console.print(table)
        total_displayed += len(batch)
        debug(f"Displayed {len(batch)} operations (total: {total_displayed})")

        # Check if we hit the search limit
        if total_api_results >= limit:
            debug(f"Reached search limit of {limit} results.")
            break

        # Early-exit triggered inside the batch loop (all target ids
        # matched, or we crossed not_before): stop after displaying
        # whatever we've collected.
        if early_exit:
            debug("Early-exit triggered; stopping pagination loop.")
            break

        # Check for more data (either remaining items on current page, or more API pages)
        has_more = page_offset < len(result.values) or next_link
        if not has_more:
            break

        # Only prefetch the next API page if we've exhausted the current one
        if page_offset >= len(result.values) and next_link:
            prefetch_task = asyncio.create_task(asyncio.to_thread(list_operations_page, next_link))
        else:
            prefetch_task = None

        try:
            # Run user prompt in thread (blocking call)
            continue_fetching = await asyncio.to_thread(
                typer.confirm, "Fetch more results?", default=True
            )

            if not continue_fetching:
                if prefetch_task:
                    prefetch_task.cancel()
                break

            # If we prefetched a new API page, use it
            if prefetch_task:
                batch_num += 1
                try:
                    result = await asyncio.wait_for(prefetch_task, timeout=30)
                except asyncio.TimeoutError:
                    info("Prefetch timed out, fetching next page on demand...")
                    result = await asyncio.to_thread(list_operations_page, next_link)
                except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout):
                    info("Prefetch failed, retrying...")
                    result = await asyncio.to_thread(list_operations_page, next_link)
                api_pages_fetched += 1
                page_offset = 0
            else:
                batch_num += 1
        except asyncio.CancelledError:
            if prefetch_task:
                prefetch_task.cancel()
            raise


@app.command("status")
def status_cmd(
    operation_id: str = typer.Argument(None, help="Optional operation id to get status for"),
) -> None:
    """Get the current compute status/usage for the project, or status of a specific operation."""
    debug("status(): entering")
    env_cfg = load_project_config(get_config_file_path())
    emit_env(env_cfg)

    # If operation_id is provided, get operation status instead of cluster status
    if operation_id:
        try:
            # Get current operation status with a single API call
            result = get_operation_status(
                env_cfg.project_name,
                operation_id,
                env_cfg.workspace_url,
                api_version=env_cfg.api_version,
            )
            console = Console()

            # Create a table for operation details
            table = Table(title=f"Operation: {result.id}", show_header=True)
            table.add_column("Created (Local)", style="magenta")
            table.add_column("Completed (Local)", style="magenta")
            table.add_column("Runtime", style="bright_cyan")
            table.add_column("Status", style="green")
            table.add_column("Runtime Details", style="cyan")

            # Get created_at from result if available
            if result.result and result.result.created_at:
                local_time = result.result.created_at.astimezone()
                formatted_time = local_time.strftime("%Y-%m-%d %H:%M:%S")
            else:
                formatted_time = "N/A"

            # Get completed_at from result if available
            completed_time = ""
            if result.result and result.result.completed_at:
                completed_time = result.result.completed_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")

            # Compute runtime duration
            runtime_str = ""
            if result.result and result.result.created_at:
                if result.result.completed_at:
                    runtime_str = _format_duration(result.result.completed_at - result.result.created_at)
                else:
                    runtime_str = _format_duration(
                        datetime.now(timezone.utc) - result.result.created_at,
                        in_progress=True,
                    )

            runtime_details = (
                result.result.runtime_details
                if result.result and result.result.runtime_details
                else ""
            )

            table.add_row(formatted_time, completed_time, runtime_str, result.status, runtime_details)

            console.print(table)

            # Display pods table for Running operations (preview endpoint).
            # Best-effort: silently skip on 404/transport errors so CLIs
            # running against servers without the pods endpoint still work.
            if result.status == AzureCoreOperationState.RUNNING:
                try:
                    pods = get_operation_pods(
                        env_cfg.project_name,
                        operation_id,
                        env_cfg.workspace_url,
                    )
                except OperationNotFoundError as ex:
                    debug(f"Pods endpoint returned 404 for {operation_id}: {ex}")
                    pods = None
                except Exception as ex:  # pragma: no cover - defensive
                    debug(f"Failed to fetch pods for {operation_id}: {ex}")
                    pods = None

                if pods:
                    pods_table = Table(
                        title="Pods",
                        show_header=True,
                        header_style="bold cyan",
                    )
                    pods_table.add_column("Index", style="cyan", justify="right")
                    pods_table.add_column("Role", style="magenta")
                    pods_table.add_column("Phase", style="green")
                    for pod in pods:
                        pods_table.add_row(str(pod.index), pod.role, pod.phase)
                    console.print(pods_table)
                elif pods == []:
                    console.print(
                        "[dim]No pods reported yet for this running operation.[/dim]"
                    )

            is_failed = result.status in ("Failed", "Canceled")

            # Display logs if available
            has_logs = (
                result.result
                and result.result.tool_report
                and result.result.tool_report.logs
            )
            if has_logs:
                log_panel = Panel(
                    result.result.tool_report.logs,  # type: ignore[union-attr]
                    title="[bold cyan]Logs[/bold cyan]",
                    border_style="blue",
                    expand=False,
                )
                console.print(log_panel)
            elif is_failed:
                console.print(
                    Panel(
                        "[dim]No logs were captured for this job.[/dim]",
                        title="[bold cyan]Logs[/bold cyan]",
                        border_style="blue",
                        expand=False,
                    )
                )

            # Display statusInformation from tool_report if available
            if (
                result.result
                and result.result.tool_report
                and result.result.tool_report.status_information
            ):
                status_info = result.result.tool_report.status_information
                if isinstance(status_info, dict):
                    import json
                    status_info = json.dumps(status_info, indent=2)
                console.print(
                    Panel(
                        str(status_info),
                        title="[bold cyan]Status Information[/bold cyan]",
                        border_style="cyan",
                        expand=False,
                    )
                )

            # Display debug info if available (useful for failed jobs)
            if result.result and result.result.debug_info:
                debug_panel = Panel(
                    result.result.debug_info,
                    title="[bold yellow]Debug Info[/bold yellow]",
                    border_style="yellow",
                    expand=False,
                )
                console.print(debug_panel)

            if result.error:
                error_text = render_error_with_details(result.error)
                error_panel = Panel(
                    error_text.strip(),
                    title="[bold red]Error Details[/bold red]",
                    border_style="red",
                    expand=False,
                )
                console.print(error_panel)
        except Exception as ex:
            error(f"Failed to get operation status: {ex}")
            raise typer.Exit(code=1) from ex
        return

    try:
        cluster_result = get_compute_status(env_cfg.project_name, env_cfg.workspace_url, api_version=env_cfg.api_version)

        # Fetch ALL running and pending ops across pages for accurate counts.
        # Server-side status filter keeps payloads small even for 1000s of total ops.
        def _fetch_all_filtered(status_filter: str) -> list:
            """Follow all pages for a status-filtered query."""
            page = list_operations(
                env_cfg.project_name, env_cfg.workspace_url,
                query={"status": status_filter},
                api_version=env_cfg.api_version,
            )
            all_ops = list(page.values)
            while page.next_link:
                page = list_operations_page(page.next_link)
                all_ops.extend(page.values)
            return all_ops

        running_all = _fetch_all_filtered("Running")
        pending_all = _fetch_all_filtered("NotStarted")

        # Count jobs per nodepool from server-filtered results
        active_per_pool: dict[str, int] = {}
        pending_per_pool: dict[str, int] = {}

        for op in running_all:
            if op.nodepool_id:
                pool_name = op.nodepool_id.split("/")[-1]
                active_per_pool[pool_name] = active_per_pool.get(pool_name, 0) + 1

        for op in pending_all:
            if op.nodepool_id:
                pool_name = op.nodepool_id.split("/")[-1]
                pending_per_pool[pool_name] = pending_per_pool.get(pool_name, 0) + 1

        console = Console()

        # Build a map of nodepool info by qualified name for looking up specs
        nodepool_map: dict[str, object] = {}
        for np in env_cfg.nodepools:
            nodepool_map[np.qualified_name] = np
            # Also map by just pool name for matching
            nodepool_map[np.name] = np

        # Display each supercomputer in its own table
        for sc_name, sc_usage in cluster_result.supercomputers.items():
            table = Table(
                title=f"Supercomputer: {sc_name}", show_header=True, header_style="bold cyan"
            )
            table.add_column("Pool", style="cyan", no_wrap=True)
            table.add_column("Active", style="yellow", justify="right")
            table.add_column("Pending", style="magenta", justify="right")
            table.add_column("Nodes", style="green", justify="right")
            table.add_column("Max", style="dim", justify="right")
            table.add_column("Status", style="white")

            # Add a category header row to clarify what each column refers to
            table.add_row("", "[dim]── Jobs ──[/dim]", "", "[dim]── Nodes ──[/dim]", "", "")

            # Display each nodepool
            for pool_name, pool_usage in sc_usage.nodepools.items():
                # Try to find the nodepool info to get GPUs per node
                np_info = nodepool_map.get(f"{sc_name}/{pool_name}") or nodepool_map.get(pool_name)

                nodes_in_use = "?"
                max_nodes = "?"
                status = ""
                active_jobs = str(active_per_pool.get(pool_name, 0))
                pending_jobs = str(pending_per_pool.get(pool_name, 0))

                if np_info and hasattr(np_info, "gpus") and np_info.gpus:
                    try:
                        gpus_per_node = int(np_info.gpus)
                        reserved = int(pool_usage.reserved_gpus) if pool_usage.reserved_gpus else 0
                        allocatable = (
                            int(pool_usage.allocatable_gpus) if pool_usage.allocatable_gpus else 0
                        )

                        if gpus_per_node > 0:
                            nodes_used = reserved / gpus_per_node if gpus_per_node else 0
                            nodes_in_use = str(reserved // gpus_per_node)
                            total_nodes = (
                                allocatable // gpus_per_node if allocatable else np_info.max_nodes
                            )
                            max_nodes = str(total_nodes) if total_nodes else str(np_info.max_nodes)

                            # Show partial node usage (e.g., "0.5" if using 4 of 8 GPUs)
                            if nodes_used == 0:
                                nodes_in_use = "0"
                                status = "[green]Idle[/green]"
                            elif nodes_used == int(nodes_used):
                                nodes_in_use = str(int(nodes_used))
                                if reserved >= allocatable:
                                    status = "[red]Full[/red]"
                                else:
                                    status = "[yellow]In Use[/yellow]"
                            else:
                                # Partial node - show with one decimal
                                nodes_in_use = f"{nodes_used:.1f}"
                                status = "[yellow]In Use[/yellow]"
                        else:
                            # CPU-only pool - use CPU allocation
                            cpus_per_node = int(np_info.cpus) if np_info.cpus else 1
                            reserved = (
                                int(pool_usage.reserved_cpus) if pool_usage.reserved_cpus else 0
                            )
                            allocatable = (
                                int(pool_usage.allocatable_cpus)
                                if pool_usage.allocatable_cpus
                                else 0
                            )

                            # Calculate nodes - use float division for partial nodes
                            nodes_used = reserved / cpus_per_node if cpus_per_node else 0
                            max_nodes = str(np_info.max_nodes) if np_info.max_nodes else "?"

                            if nodes_used == 0:
                                nodes_in_use = "0"
                                status = "[green]Idle[/green]"
                            elif nodes_used == int(nodes_used):
                                nodes_in_use = str(int(nodes_used))
                                if reserved >= allocatable:
                                    status = "[red]Full[/red]"
                                else:
                                    status = "[yellow]In Use[/yellow]"
                            else:
                                nodes_in_use = f"{nodes_used:.1f}"
                                status = "[yellow]In Use[/yellow]"
                    except (ValueError, ZeroDivisionError):
                        pass

                table.add_row(pool_name, active_jobs, pending_jobs, nodes_in_use, max_nodes, status)

            console.print(table)
            console.print()

    except Exception as ex:
        error(f"Failed to get compute status: {ex}")
        raise typer.Exit(code=1) from ex


@app.command("pools")
def list_pools() -> None:
    """List available nodepools from configuration.

    Shows all nodepools discovered during configuration, with their
    resource capacities (CPUs, memory, GPUs) per node and pool totals.
    """
    debug("pools(): entering")
    env_cfg = load_project_config(get_config_file_path())

    if not env_cfg.nodepools:
        info("No nodepools configured. Run 'discovery configure' to discover nodepools.")
        return

    console = Console()

    # Create a rich table for the pools - always show supercomputer since pools come from multiple
    table = Table(title="Available Nodepools", show_header=True, header_style="bold cyan")
    table.add_column("Supercomputer", style="blue")
    table.add_column("Pool", style="green")
    table.add_column("SKU", style="dim")
    table.add_column("Max Nodes", style="cyan", justify="right")
    table.add_column("CPUs/Node", style="cyan", justify="right")
    table.add_column("Mem/Node", style="cyan", justify="right")
    table.add_column("GPUs/Node", style="yellow", justify="right")
    table.add_column("Total GPUs", style="yellow", justify="right")
    table.add_column("Default", style="magenta", justify="center")

    for np in env_cfg.nodepools:
        is_default = "✓" if np.id == env_cfg.nodepool_id else ""
        table.add_row(
            np.supercomputer_name or "-",
            np.name,
            np.sku or "-",
            str(np.max_nodes) if np.max_nodes else "-",
            np.cpus or "-",
            f"{np.memory}GB" if np.memory else "-",
            np.gpus if np.gpus and np.gpus != "0" else "-",
            np.max_gpus if np.max_gpus and np.max_gpus != "0" else "-",
            is_default,
        )

    console.print(table)
    console.print()
    console.print(
        "[dim]Use --pool <supercomputer/poolname> with start/batch/vscode commands to select a pool.[/dim]"
    )


__all__ = [
    "app",
    "list_cmd",
    "list_done",
    "list_pools",
    "list_queued",
    "list_running",
    "status_cmd",
]
