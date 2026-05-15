"""Load testing CLI for stress-testing the supercomputer API.

Provides a framework to test API endpoints with configurable concurrency,
duration, and request patterns. Measures response times, throughput, and
failure rates across multiple endpoint types.
"""

from __future__ import annotations

import asyncio
import random
import statistics
import time
from dataclasses import dataclass, field
from enum import Enum

import typer
from rich.console import Console
from rich.live import Live
from rich.table import Table

from discovery.common.logging import debug, error, info
from discovery.poll.cli_helpers import get_config_file_path, run_configure_if_needed
from discovery.poll.dataplane_api import (
    AuthHeaders,
    create_async_client,
    get_access_token,
    http_get_async,
    http_post_async,
)


app = typer.Typer()
console = Console()


# ---------------------------------------------------------------------------
# Endpoint Definitions
# ---------------------------------------------------------------------------


class Endpoint(str, Enum):
    """API endpoints available for load testing."""

    LIST_OPERATIONS = "list_operations"
    LIST_OPERATIONS_PAGINATED = "list_operations_paginated"
    COMPUTE_STATUS = "compute_status"
    GET_OPERATION = "get_operation"  # Requires an operation ID
    START_TOOL_RUN = "start_tool_run"  # POST - expensive, creates jobs
    ALL = "all"  # Test all endpoints in rotation (excludes expensive ones)


# Endpoints included in ALL rotation (excludes expensive ones)
ALL_ENDPOINTS = [
    Endpoint.LIST_OPERATIONS,
    Endpoint.LIST_OPERATIONS_PAGINATED,
    Endpoint.COMPUTE_STATUS,
    Endpoint.GET_OPERATION,
]

ENDPOINT_DESCRIPTIONS = {
    Endpoint.LIST_OPERATIONS: "List operations for project (single page)",
    Endpoint.LIST_OPERATIONS_PAGINATED: "List operations with pagination (follows nextLink)",
    Endpoint.COMPUTE_STATUS: "Get compute usage/status",
    Endpoint.GET_OPERATION: "Get specific operation details",
    Endpoint.START_TOOL_RUN: "Start a tool run (POST, EXPENSIVE - creates jobs)",
    Endpoint.ALL: "Rotate through all endpoints (excludes expensive)",
}


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class RequestResult:
    """Result of a single request."""

    endpoint: str
    success: bool
    duration: float  # seconds
    status_code: int | None = None
    error: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class EndpointStats:
    """Statistics for a single endpoint."""

    results: list[RequestResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def successful(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.success)

    @property
    def success_rate(self) -> float:
        return (self.successful / self.total * 100) if self.total else 0.0

    @property
    def durations(self) -> list[float]:
        return [r.duration for r in self.results if r.success]

    @property
    def mean_duration(self) -> float:
        return statistics.mean(self.durations) if self.durations else 0.0

    @property
    def p95_duration(self) -> float:
        if not self.durations:
            return 0.0
        sorted_d = sorted(self.durations)
        idx = int(len(sorted_d) * 0.95)
        return sorted_d[min(idx, len(sorted_d) - 1)]


@dataclass
class LoadTestStats:
    """Aggregate statistics for a load test run."""

    by_endpoint: dict[str, EndpointStats] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None

    # Breaking point tracking
    first_failure_request_num: int | None = None
    first_failure_time: float | None = None
    first_failure_concurrency: int | None = None
    first_failure_rps: float | None = None
    breaking_point_concurrency: int | None = None  # Concurrency when failure rate exceeded threshold
    _request_counter: int = field(default=0, repr=False)

    def record(self, result: RequestResult, concurrency: int | None = None) -> None:
        """Record a request result."""
        self._request_counter += 1

        if result.endpoint not in self.by_endpoint:
            self.by_endpoint[result.endpoint] = EndpointStats()
        self.by_endpoint[result.endpoint].results.append(result)

        # Track first failure
        if not result.success and self.first_failure_request_num is None:
            self.first_failure_request_num = self._request_counter
            self.first_failure_time = result.timestamp
            self.first_failure_concurrency = concurrency
            # Calculate RPS at time of first failure
            elapsed = result.timestamp - self.start_time
            if elapsed > 0:
                self.first_failure_rps = self._request_counter / elapsed

    @property
    def time_to_first_failure(self) -> float | None:
        """Seconds from start until first failure."""
        if self.first_failure_time is None:
            return None
        return self.first_failure_time - self.start_time

    @property
    def all_results(self) -> list[RequestResult]:
        results = []
        for stats in self.by_endpoint.values():
            results.extend(stats.results)
        return results

    @property
    def total_requests(self) -> int:
        return sum(s.total for s in self.by_endpoint.values())

    @property
    def successful_requests(self) -> int:
        return sum(s.successful for s in self.by_endpoint.values())

    @property
    def failed_requests(self) -> int:
        return sum(s.failed for s in self.by_endpoint.values())

    @property
    def success_rate(self) -> float:
        if not self.total_requests:
            return 0.0
        return self.successful_requests / self.total_requests * 100

    @property
    def durations(self) -> list[float]:
        return [r.duration for r in self.all_results if r.success]

    @property
    def min_duration(self) -> float:
        return min(self.durations) if self.durations else 0.0

    @property
    def max_duration(self) -> float:
        return max(self.durations) if self.durations else 0.0

    @property
    def mean_duration(self) -> float:
        return statistics.mean(self.durations) if self.durations else 0.0

    @property
    def median_duration(self) -> float:
        return statistics.median(self.durations) if self.durations else 0.0

    @property
    def stdev_duration(self) -> float:
        return statistics.stdev(self.durations) if len(self.durations) > 1 else 0.0

    @property
    def p95_duration(self) -> float:
        if not self.durations:
            return 0.0
        sorted_d = sorted(self.durations)
        idx = int(len(sorted_d) * 0.95)
        return sorted_d[min(idx, len(sorted_d) - 1)]

    @property
    def p99_duration(self) -> float:
        if not self.durations:
            return 0.0
        sorted_d = sorted(self.durations)
        idx = int(len(sorted_d) * 0.99)
        return sorted_d[min(idx, len(sorted_d) - 1)]

    @property
    def elapsed_time(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def requests_per_second(self) -> float:
        if self.elapsed_time == 0:
            return 0.0
        return self.total_requests / self.elapsed_time

    def get_error_summary(self) -> dict[str, int]:
        """Get count of each error type."""
        errors: dict[str, int] = {}
        for result in self.all_results:
            if not result.success and result.error:
                key = result.error[:60]  # Truncate long errors
                errors[key] = errors.get(key, 0) + 1
        return errors


# ---------------------------------------------------------------------------
# Display Helpers
# ---------------------------------------------------------------------------


def create_stats_table(stats: LoadTestStats, concurrency: int, target_rps: float | None) -> Table:
    """Create a rich table showing current load test statistics."""
    table = Table(title="Load Test - Live Statistics", show_header=True)
    table.add_column("Metric", style="cyan", width=25)
    table.add_column("Value", style="green", width=15)
    table.add_column("Endpoint", style="yellow", width=20)
    table.add_column("Req", style="white", width=8)
    table.add_column("OK%", style="green", width=8)
    table.add_column("Avg(ms)", style="white", width=10)

    # Overall stats
    table.add_row("Elapsed Time", f"{stats.elapsed_time:.1f}s", "", "", "", "")
    table.add_row("Total Requests", str(stats.total_requests), "", "", "", "")
    table.add_row("Successful", f"{stats.successful_requests}", "", "", "", "")
    table.add_row("Failed", str(stats.failed_requests), "", "", "", "")
    table.add_row("Requests/sec", f"{stats.requests_per_second:.1f}", "", "", "", "")
    table.add_row("Concurrency", str(concurrency), "", "", "", "")
    table.add_row("Mean (ms)", f"{stats.mean_duration * 1000:.1f}", "", "", "", "")
    table.add_row("P95 (ms)", f"{stats.p95_duration * 1000:.1f}", "", "", "", "")

    # Per-endpoint stats
    table.add_row("", "", "", "", "", "")
    table.add_row("[bold]By Endpoint[/bold]", "", "", "", "", "")
    for endpoint, ep_stats in sorted(stats.by_endpoint.items()):
        table.add_row(
            "",
            "",
            endpoint,
            str(ep_stats.total),
            f"{ep_stats.success_rate:.0f}%",
            f"{ep_stats.mean_duration * 1000:.1f}",
        )

    return table


def print_final_summary(stats: LoadTestStats) -> None:
    """Print the final test summary."""
    console.print("\n" + "=" * 70)
    console.print("[bold]Load Test Results[/bold]")
    console.print("=" * 70)

    console.print(f"\n[cyan]Duration:[/cyan] {stats.elapsed_time:.1f}s")
    console.print(f"[cyan]Total Requests:[/cyan] {stats.total_requests}")
    console.print(f"[cyan]Successful:[/cyan] {stats.successful_requests} ({stats.success_rate:.1f}%)")
    console.print(f"[cyan]Failed:[/cyan] {stats.failed_requests}")
    console.print(f"[cyan]Throughput:[/cyan] {stats.requests_per_second:.2f} req/s")

    if stats.durations:
        console.print("\n[bold]Response Times (all endpoints):[/bold]")
        console.print(f"  Min:    {stats.min_duration * 1000:.1f}ms")
        console.print(f"  Max:    {stats.max_duration * 1000:.1f}ms")
        console.print(f"  Mean:   {stats.mean_duration * 1000:.1f}ms")
        console.print(f"  Median: {stats.median_duration * 1000:.1f}ms")
        console.print(f"  StdDev: {stats.stdev_duration * 1000:.1f}ms")
        console.print(f"  P95:    {stats.p95_duration * 1000:.1f}ms")
        console.print(f"  P99:    {stats.p99_duration * 1000:.1f}ms")

    # Breaking point analysis
    if stats.failed_requests > 0:
        console.print("\n[bold yellow]Breaking Point Analysis:[/bold yellow]")
        if stats.first_failure_request_num:
            console.print(f"  First failure at request #: {stats.first_failure_request_num}")
        if stats.time_to_first_failure is not None:
            console.print(f"  Time to first failure: {stats.time_to_first_failure:.2f}s")
        if stats.first_failure_concurrency:
            console.print(f"  Concurrency at first failure: {stats.first_failure_concurrency}")
        if stats.first_failure_rps:
            console.print(f"  RPS at first failure: {stats.first_failure_rps:.1f}")
        if stats.breaking_point_concurrency:
            console.print(f"  Breaking point concurrency: {stats.breaking_point_concurrency}")

        # Calculate failure rate progression (first vs second half)
        all_results = stats.all_results
        if len(all_results) > 10:
            mid = len(all_results) // 2
            first_half_failures = sum(1 for r in all_results[:mid] if not r.success)
            second_half_failures = sum(1 for r in all_results[mid:] if not r.success)
            first_half_rate = first_half_failures / mid * 100
            second_half_rate = second_half_failures / (len(all_results) - mid) * 100
            console.print(f"  Failure rate (first half): {first_half_rate:.1f}%")
            console.print(f"  Failure rate (second half): {second_half_rate:.1f}%")
    else:
        console.print("\n[bold green]No failures detected - API remained stable[/bold green]")

    # Per-endpoint breakdown
    if stats.by_endpoint:
        console.print("\n[bold]By Endpoint:[/bold]")
        for endpoint, ep_stats in sorted(stats.by_endpoint.items()):
            console.print(
                f"  {endpoint}: {ep_stats.total} requests, "
                f"{ep_stats.success_rate:.1f}% success, "
                f"avg {ep_stats.mean_duration * 1000:.1f}ms, "
                f"p95 {ep_stats.p95_duration * 1000:.1f}ms"
            )

    # Error summary
    errors = stats.get_error_summary()
    if errors:
        console.print("\n[bold red]Errors:[/bold red]")
        for err, count in sorted(errors.items(), key=lambda x: -x[1]):
            console.print(f"  [{count}x] {err}")

    console.print("")


# ---------------------------------------------------------------------------
# Request Execution
# ---------------------------------------------------------------------------


class EndpointConfig:
    """Configuration for making requests to various endpoints."""

    def __init__(
        self,
        workspace_url: str,
        project_name: str,
        token: str,
        tool_id: str | None = None,
        storage_id: str | None = None,
        nodepool_id: str | None = None,
    ):
        self.workspace_url = workspace_url.rstrip("/")
        self.project_name = project_name
        self.token = token
        self.headers = AuthHeaders(Authorization=f"Bearer {token}")
        self.operation_ids: list[str] = []  # Populated during test
        self.next_links: list[str] = []  # Pagination links discovered during test
        # For start_tool_run tests
        self.tool_id = tool_id
        self.storage_id = storage_id
        self.nodepool_id = nodepool_id

    def get_url_and_params(self, endpoint: Endpoint) -> tuple[str, dict[str, str] | None]:
        """Get URL and params for an endpoint."""
        base = f"{self.workspace_url}/tools/projects/{self.project_name}"

        if endpoint == Endpoint.LIST_OPERATIONS:
            return f"{base}/operations", {"reverse": "true", "maxpagesize": "10"}
        elif endpoint == Endpoint.LIST_OPERATIONS_PAGINATED:
            # Use a stored next_link if available, otherwise start fresh with small page
            if self.next_links:
                # Pop a next_link to use (will be replenished by response)
                return self.next_links.pop(0), None
            # Start with small page size to ensure pagination
            return f"{base}/operations", {"reverse": "true", "maxpagesize": "5"}
        elif endpoint == Endpoint.COMPUTE_STATUS:
            return f"{base}/computeUsage", None
        elif endpoint == Endpoint.GET_OPERATION:
            if self.operation_ids:
                op_id = random.choice(self.operation_ids)
                return f"{base}/operations/{op_id}", None
            # Fall back to list if no operation IDs known
            return f"{base}/operations", {"reverse": "true", "maxpagesize": "1"}
        elif endpoint == Endpoint.START_TOOL_RUN:
            return f"{base}:run", None
        else:
            raise ValueError(f"Unknown endpoint: {endpoint}")

    def get_tool_run_payload(self) -> dict:
        """Get minimal payload for start_tool_run test."""
        if not self.tool_id or not self.storage_id:
            raise ValueError("tool_id and storage_id required for start_tool_run test")
        payload = {
            "toolId": self.tool_id,
            "storageId": self.storage_id,
            "command": "echo 'smoke test' && sleep 1",
            "inlineFiles": [],
            "inputData": [],
            "outputData": [],
            "nodePoolIds": [self.nodepool_id] if self.nodepool_id else [],
        }
        return payload


async def make_request(
    client,
    config: EndpointConfig,
    endpoint: Endpoint,
) -> RequestResult:
    """Make a single async request and return the result."""
    url, params = config.get_url_and_params(endpoint)
    start = time.perf_counter()

    try:
        # POST endpoints
        if endpoint == Endpoint.START_TOOL_RUN:
            payload = config.get_tool_run_payload()
            data = await http_post_async(
                client=client, url=url, headers=config.headers, json=payload, params=params
            )
        else:
            # GET endpoints
            data = await http_get_async(
                client=client, url=url, headers=config.headers, params=params
            )
        duration = time.perf_counter() - start

        # Extract data from list operations responses
        if endpoint in (Endpoint.LIST_OPERATIONS, Endpoint.LIST_OPERATIONS_PAGINATED) and isinstance(data, dict):
            # Extract operation IDs for future GET_OPERATION requests
            for op in data.get("value", data.get("values", []))[:5]:
                op_id = op.get("id")
                if op_id and op_id not in config.operation_ids:
                    config.operation_ids.append(op_id)
                    if len(config.operation_ids) > 20:
                        config.operation_ids.pop(0)

            # Extract nextLink for pagination testing
            next_link = data.get("nextLink")
            if next_link and next_link not in config.next_links:
                config.next_links.append(next_link)
                # Keep a reasonable number of links
                if len(config.next_links) > 10:
                    config.next_links.pop(0)

        return RequestResult(
            endpoint=endpoint.value, success=True, duration=duration, status_code=200
        )
    except Exception as e:
        duration = time.perf_counter() - start
        error_msg = str(e)
        # Try to extract status code
        status_code = None
        if "status" in error_msg.lower():
            import re
            match = re.search(r"(\d{3})", error_msg)
            if match:
                status_code = int(match.group(1))
        return RequestResult(
            endpoint=endpoint.value,
            success=False,
            duration=duration,
            status_code=status_code,
            error=error_msg,
        )


def get_next_endpoint(
    endpoint_type: Endpoint,
    available_endpoints: list[Endpoint],
    counter: int,
) -> Endpoint:
    """Get the next endpoint to test based on configuration."""
    if endpoint_type == Endpoint.ALL:
        # Round-robin through available endpoints
        return available_endpoints[counter % len(available_endpoints)]
    return endpoint_type


async def run_load_test(
    config: EndpointConfig,
    endpoint_type: Endpoint,
    concurrency: int,
    max_requests: int | None,
    max_duration: float | None,
    stop_on_failure_count: int | None,
    target_rps: float | None,
) -> LoadTestStats:
    """Run the load test with specified parameters."""
    stats = LoadTestStats()

    # Endpoints to test (excluding ALL which is a meta-option)
    available_endpoints = [e for e in Endpoint if e != Endpoint.ALL]

    # Calculate delay between request batches for rate limiting
    batch_delay = concurrency / target_rps if target_rps else 0

    request_counter = 0

    async with create_async_client() as client:
        with Live(
            create_stats_table(stats, concurrency, target_rps),
            refresh_per_second=2,
            console=console,
        ) as live:
            while True:
                # Check stop conditions
                if max_requests and stats.total_requests >= max_requests:
                    break
                if max_duration and stats.elapsed_time >= max_duration:
                    break
                if stop_on_failure_count and stats.failed_requests >= stop_on_failure_count:
                    break

                # Launch concurrent requests
                batch_start = time.perf_counter()
                tasks = []
                for _ in range(concurrency):
                    endpoint = get_next_endpoint(
                        endpoint_type, available_endpoints, request_counter
                    )
                    request_counter += 1
                    tasks.append(make_request(client, config, endpoint))

                results = await asyncio.gather(*tasks)
                for result in results:
                    stats.record(result, concurrency=concurrency)

                # Update display
                live.update(create_stats_table(stats, concurrency, target_rps))

                # Rate limiting
                if batch_delay > 0:
                    batch_elapsed = time.perf_counter() - batch_start
                    sleep_time = batch_delay - batch_elapsed
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)

    stats.end_time = time.time()
    return stats


async def run_ramp_up_test(
    config: EndpointConfig,
    endpoint_type: Endpoint,
    initial_concurrency: int,
    ramp_step: int,
    ramp_interval: float,
    max_duration: float | None,
    stop_on_failures: int,
) -> LoadTestStats:
    """Run a ramp-up test that increases concurrency until failures occur."""
    combined_stats = LoadTestStats()
    current_concurrency = initial_concurrency
    start_time = time.time()

    console.print("[bold]Starting ramp-up test...[/bold]\n")

    available_endpoints = [e for e in Endpoint if e != Endpoint.ALL]
    request_counter = 0

    async with create_async_client() as client:
        while True:
            # Check duration limit
            if max_duration and (time.time() - start_time) >= max_duration:
                console.print("\n[yellow]Max duration reached[/yellow]")
                break

            console.print(f"\n[cyan]Testing with concurrency: {current_concurrency}[/cyan]")

            # Run requests at current concurrency for ramp_interval seconds
            batch_stats = LoadTestStats()
            batch_start = time.time()

            while (time.time() - batch_start) < ramp_interval:
                tasks = []
                for _ in range(current_concurrency):
                    endpoint = get_next_endpoint(
                        endpoint_type, available_endpoints, request_counter
                    )
                    request_counter += 1
                    tasks.append(make_request(client, config, endpoint))

                results = await asyncio.gather(*tasks)
                for result in results:
                    batch_stats.record(result, concurrency=current_concurrency)
                    combined_stats.record(result, concurrency=current_concurrency)

                # Check failure threshold
                if batch_stats.failed_requests >= stop_on_failures:
                    break

            # Report this level's stats
            console.print(
                f"  Requests: {batch_stats.total_requests}, "
                f"Success: {batch_stats.success_rate:.1f}%, "
                f"Avg: {batch_stats.mean_duration * 1000:.1f}ms, "
                f"RPS: {batch_stats.total_requests / ramp_interval:.1f}"
            )

            # Check if we hit failure threshold - record breaking point
            if batch_stats.failed_requests >= stop_on_failures:
                combined_stats.breaking_point_concurrency = current_concurrency
                console.print(
                    f"\n[red]Hit failure threshold ({batch_stats.failed_requests} failures) "
                    f"at concurrency {current_concurrency}[/red]"
                )
                break

            # Increase concurrency
            current_concurrency += ramp_step

    combined_stats.end_time = time.time()
    return combined_stats


# ---------------------------------------------------------------------------
# CLI Command
# ---------------------------------------------------------------------------


@app.command()
def load(
    concurrency: int = typer.Option(
        1, "--concurrency", "-c", help="Number of concurrent requests per batch"
    ),
    max_requests: int | None = typer.Option(
        None, "--max-requests", "-n", help="Maximum total requests (default: unlimited)"
    ),
    max_duration: float | None = typer.Option(
        60.0, "--duration", "-d", help="Maximum test duration in seconds"
    ),
    stop_on_failures: int | None = typer.Option(
        None, "--stop-on-failures", "-f", help="Stop after this many failures"
    ),
    target_rps: float | None = typer.Option(
        None, "--rps", "-r", help="Target requests per second (default: unlimited)"
    ),
    endpoint: Endpoint = typer.Option(
        Endpoint.ALL, "--endpoint", "-e", help="Endpoint to test (or 'all' for rotation)"
    ),
    ramp_up: bool = typer.Option(
        False, "--ramp-up", help="Gradually increase concurrency until failures"
    ),
    ramp_step: int = typer.Option(
        1, "--ramp-step", help="Concurrency increase per ramp step"
    ),
    ramp_interval: float = typer.Option(
        10.0, "--ramp-interval", help="Seconds between ramp-up steps"
    ),
    tool_id: str | None = typer.Option(
        None, "--tool-id", help="Tool ID for start_tool_run tests (required for that endpoint)"
    ),
    storage_id: str | None = typer.Option(
        None, "--storage-id", help="Storage ID for start_tool_run tests (required for that endpoint)"
    ),
    nodepool_id: str | None = typer.Option(
        None, "--nodepool-id", help="Nodepool ID for start_tool_run tests (optional)"
    ),
) -> None:
    """Run load test against the supercomputer API.

    Tests API endpoints with configurable concurrency and measures response times,
    throughput, and failure rates. By default, rotates through all available endpoints.

    Examples:

        # Test all endpoints with 5 concurrent requests for 60 seconds
        discovery smoke load -c 5 -d 60

        # Test only list_operations endpoint with 10 concurrent, max 1000 requests
        discovery smoke load -c 10 -n 1000 -e list_operations

        # Ramp up concurrency until 10 failures occur
        discovery smoke load --ramp-up -f 10

        # Test with rate limiting (100 requests/second target)
        discovery smoke load -c 20 --rps 100

        # Test start_tool_run (expensive - creates actual jobs)
        discovery smoke load -e start_tool_run --tool-id <id> --storage-id <id> -n 5

    Available endpoints:
        - list_operations: List operations for project (single page)
        - list_operations_paginated: List with pagination (follows nextLink)
        - compute_status: Get compute usage/status
        - get_operation: Get specific operation details (uses IDs from list)
        - start_tool_run: Start a tool run (EXPENSIVE - creates actual jobs)
        - all: Rotate through standard endpoints (excludes expensive ones)
    """
    env_cfg = run_configure_if_needed(get_config_file_path())

    if not env_cfg.workspace_url or not env_cfg.project_name:
        error("Workspace URL and project name required. Run 'discovery configure' first.")
        raise typer.Exit(code=1)

    # Validate start_tool_run requirements
    if endpoint == Endpoint.START_TOOL_RUN:
        if not tool_id or not storage_id:
            error("--tool-id and --storage-id are required for start_tool_run tests")
            raise typer.Exit(code=1)

    # Get token
    try:
        token = get_access_token()
    except Exception as ex:
        error(f"Failed to get access token: {ex}")
        raise typer.Exit(code=1) from ex

    config = EndpointConfig(
        workspace_url=env_cfg.workspace_url,
        project_name=env_cfg.project_name,
        token=token,
        tool_id=tool_id,
        storage_id=storage_id,
        nodepool_id=nodepool_id,
    )

    # Print configuration
    console.print("\n[bold]Load Test Configuration[/bold]")
    console.print(f"  Workspace: {env_cfg.workspace_url}")
    console.print(f"  Project: {env_cfg.project_name}")
    console.print(f"  Endpoint: {endpoint.value}")
    console.print(f"  Concurrency: {concurrency}")
    if max_requests:
        console.print(f"  Max Requests: {max_requests}")
    if max_duration:
        console.print(f"  Max Duration: {max_duration}s")
    if stop_on_failures:
        console.print(f"  Stop on Failures: {stop_on_failures}")
    if target_rps:
        console.print(f"  Target RPS: {target_rps}")
    if ramp_up:
        console.print(f"  Ramp-up: enabled (step={ramp_step}, interval={ramp_interval}s)")
    console.print("")

    # Run the test
    if ramp_up:
        stats = asyncio.run(
            run_ramp_up_test(
                config=config,
                endpoint_type=endpoint,
                initial_concurrency=concurrency,
                ramp_step=ramp_step,
                ramp_interval=ramp_interval,
                max_duration=max_duration,
                stop_on_failures=stop_on_failures or 10,
            )
        )
    else:
        stats = asyncio.run(
            run_load_test(
                config=config,
                endpoint_type=endpoint,
                concurrency=concurrency,
                max_requests=max_requests,
                max_duration=max_duration,
                stop_on_failure_count=stop_on_failures,
                target_rps=target_rps,
            )
        )

    # Print final summary
    print_final_summary(stats)

    if stats.failed_requests > 0:
        raise typer.Exit(code=1)


__all__ = [
    "Endpoint",
    "EndpointStats",
    "LoadTestStats",
    "RequestResult",
    "app",
    "load",
]
