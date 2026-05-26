"""Discovery poll utilities replicating legacy shell `poll-utils.sh` functionality.

Features:
  - Start tool run (POST) with payload file
  - Extract operation id from start response
  - Poll status endpoint until terminal state
  - Auto tagging hook placeholders
  - Safe JSON validation & extraction
  - Optional log extraction / display
"""

from __future__ import annotations

import atexit
import itertools
import json as _json
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


# httpx transport-level errors that indicate transient network issues
_TRANSIENT_NETWORK_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.WriteError,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
)

from discovery.common.logging import debug, info
from discovery.poll.models.auth import AuthHeaders
from discovery.poll.models.compute import ComputeUsageModel
from discovery.poll.models.tool_response import (
    OperationsListResponse,
    ToolExecutionResponse,
    ToolReport,
)
from discovery.poll.models.tool_run import ToolRunRequest


T = TypeVar("T")


@dataclass
class ResponseTimeStats:
    """Statistics for response times of HTTP requests."""

    times: list[float] = field(default_factory=list)
    queries: set[str] = field(default_factory=set)

    def record(self, elapsed: float, query: str | None = None) -> None:
        """Record a response time and optional query string."""
        self.times.append(elapsed)
        if query:
            self.queries.add(query)

    @property
    def count(self) -> int:
        return len(self.times)

    @property
    def total(self) -> float:
        return sum(self.times) if self.times else 0.0

    @property
    def min(self) -> float:
        return min(self.times) if self.times else 0.0

    @property
    def max(self) -> float:
        return max(self.times) if self.times else 0.0

    @property
    def mean(self) -> float:
        return statistics.mean(self.times) if self.times else 0.0

    @property
    def stdev(self) -> float:
        return statistics.stdev(self.times) if len(self.times) > 1 else 0.0


def _parse_url(url: str) -> tuple[str, str | None]:
    """Parse URL into base (scheme+netloc+path) and query string.

    Returns:
        Tuple of (base_url, query_string or None)
    """
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    query = parsed.query if parsed.query else None
    return base, query


@dataclass
class HTTPStats:
    """Aggregate HTTP response time statistics per method and URL (domain+path)."""

    _get_stats: dict[str, ResponseTimeStats] = field(
        default_factory=lambda: defaultdict(ResponseTimeStats)
    )
    _post_stats: dict[str, ResponseTimeStats] = field(
        default_factory=lambda: defaultdict(ResponseTimeStats)
    )

    def record_get(self, url: str, elapsed: float) -> None:
        """Record a GET request response time, grouped by domain+path."""
        base_url, query = _parse_url(url)
        self._get_stats[base_url].record(elapsed, query)

    def record_post(self, url: str, elapsed: float) -> None:
        """Record a POST request response time, grouped by domain+path."""
        base_url, query = _parse_url(url)
        self._post_stats[base_url].record(elapsed, query)

    def _format_endpoint_stats(self, url: str, stats: ResponseTimeStats) -> list[str]:
        """Format statistics for a single endpoint."""
        lines = []
        lines.append(f"  URL: {url}")
        lines.append(
            f"    Count: {stats.count}, Total: {stats.total:.2f}s, "
            f"Min: {stats.min:.3f}s, Max: {stats.max:.3f}s, "
            f"Mean: {stats.mean:.3f}s, StdDev: {stats.stdev:.3f}s"
        )
        if stats.queries:
            lines.append("    Queries seen:")
            for q in sorted(stats.queries):
                lines.append(f"      ?{q}")
        return lines

    def get_summary(self) -> str:
        """Generate a formatted summary of all statistics."""
        lines = []
        lines.append("\n" + "=" * 80)
        lines.append("HTTP Response Time Statistics (grouped by domain+path)")
        lines.append("=" * 80)

        if self._get_stats:
            lines.append("\nGET Requests:")
            lines.append("-" * 40)
            for url, stats in sorted(self._get_stats.items()):
                lines.extend(self._format_endpoint_stats(url, stats))

        if self._post_stats:
            lines.append("\nPOST Requests:")
            lines.append("-" * 40)
            for url, stats in sorted(self._post_stats.items()):
                lines.extend(self._format_endpoint_stats(url, stats))

        if not self._get_stats and not self._post_stats:
            lines.append("\nNo HTTP requests recorded.")

        lines.append("=" * 80 + "\n")
        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all recorded statistics."""
        self._get_stats.clear()
        self._post_stats.clear()


# Global HTTP statistics tracker
_http_stats = HTTPStats()


def get_http_stats() -> HTTPStats:
    """Get the global HTTP statistics tracker."""
    return _http_stats


def print_http_stats_summary() -> None:
    """Print HTTP statistics summary as debug output."""
    if _http_stats._get_stats or _http_stats._post_stats:
        debug(_http_stats.get_summary())


# Register atexit handler to print stats on program exit in verbose mode
atexit.register(print_http_stats_summary)


# ---------------------------------------------------------------------------
# httpx event hooks for timing instrumentation
# ---------------------------------------------------------------------------

_START_TIME_KEY = "_stats_start_time"


def _on_request(request: httpx.Request) -> None:
    """Event hook called before each request is sent."""
    request.extensions[_START_TIME_KEY] = time.perf_counter()


def _on_response(response: httpx.Response) -> None:
    """Event hook called after each response is received."""
    start_time = response.request.extensions.get(_START_TIME_KEY)
    if start_time is None:
        return
    elapsed = time.perf_counter() - start_time
    url = str(response.request.url)
    method = response.request.method

    debug(f"HTTP {method} {url}: {elapsed:.2f}s")

    if method == "GET":
        _http_stats.record_get(url, elapsed)
    elif method == "POST":
        _http_stats.record_post(url, elapsed)


# Async versions of event hooks for AsyncClient
async def _on_request_async(request: httpx.Request) -> None:
    """Async event hook called before each request is sent."""
    request.extensions[_START_TIME_KEY] = time.perf_counter()


async def _on_response_async(response: httpx.Response) -> None:
    """Async event hook called after each response is received."""
    start_time = response.request.extensions.get(_START_TIME_KEY)
    if start_time is None:
        return
    elapsed = time.perf_counter() - start_time
    url = str(response.request.url)
    method = response.request.method

    debug(f"HTTP {method} {url}: {elapsed:.2f}s")

    if method == "GET":
        _http_stats.record_get(url, elapsed)
    elif method == "POST":
        _http_stats.record_post(url, elapsed)


def _create_client() -> httpx.Client:
    """Create an httpx client with timing instrumentation."""
    return httpx.Client(
        timeout=30,
        follow_redirects=True,
        event_hooks={"request": [_on_request], "response": [_on_response]},
    )


# Persistent client for connection reuse (DNS + TLS amortised across calls)
_persistent_client: httpx.Client | None = None


def _get_persistent_client() -> httpx.Client:
    """Return a long-lived httpx client that reuses TCP/TLS connections."""
    global _persistent_client
    if _persistent_client is None or _persistent_client.is_closed:
        _persistent_client = _create_client()
    return _persistent_client


def _create_async_client() -> httpx.AsyncClient:
    """Create an async httpx client with timing instrumentation."""
    return httpx.AsyncClient(
        timeout=60,
        follow_redirects=True,
        event_hooks={"request": [_on_request_async], "response": [_on_response_async]},
    )


DEFAULT_POLL_INTERVAL = 5
DEFAULT_SCOPE = "https://discovery.azure.com/access_as_user"


class PollError(RuntimeError):
    pass


class JsonValidationError(PollError):
    pass


class TransientHTTPError(PollError):
    """Represents a transient HTTP/network issue suitable for retry."""


_token_cache: dict[str, tuple[float, str]] = {}
_TOKEN_REFRESH_MARGIN = 120  # refresh 2 min before actual expiry


def invalidate_token_cache(scope: str = DEFAULT_SCOPE) -> None:
    """Evict a cached token, e.g. after receiving a 401 response."""
    _token_cache.pop(scope, None)


def get_access_token(scope: str = DEFAULT_SCOPE) -> str:
    """Get an Azure access token, caching to avoid repeated subprocess calls.

    The ``az account get-access-token`` subprocess takes ~1.7-2.5 s on every
    invocation.  We cache the token until 2 minutes before its actual expiry
    (typically ~60 min lifetime) to eliminate redundant calls during paginated
    listings while ensuring we never send an expired token.
    """
    now = time.time()
    cached = _token_cache.get(scope)
    if cached is not None:
        expires_at, token = cached
        if now < expires_at - _TOKEN_REFRESH_MARGIN:
            return token

    cmd = [
        "az",
        "account",
        "get-access-token",
        "--scope",
        scope,
        "--output",
        "json",
    ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        msg = f"Failed to get access token: {result.stderr.strip()}"
        raise PollError(msg)
    data = _json.loads(result.stdout)
    token = data["accessToken"]

    # Use actual expiry from az CLI; fall back to 5-min TTL if unavailable
    expires_at = now + 300
    expires_on = data.get("expiresOn")
    if expires_on:
        try:
            from datetime import datetime, timezone

            # az CLI returns "2026-05-01 01:30:00.000000" (local time)
            dt = datetime.strptime(expires_on, "%Y-%m-%d %H:%M:%S.%f")
            dt = dt.astimezone(timezone.utc)
            expires_at = dt.timestamp()
        except (ValueError, OSError):
            pass  # keep 5-min fallback

    _token_cache[scope] = (expires_at, token)
    return token


def start_tool_run(
    project_name: str, toolrun: ToolRunRequest, workspace_url: str, api_version: str
) -> ToolExecutionResponse:
    token = get_access_token()
    url = f"{workspace_url.rstrip('/')}/tools/projects/{project_name}:run"
    params = {"api-version": api_version}
    info(f"POST {url}")
    resp = _http_post(
        url=url,
        headers=AuthHeaders(  # type: ignore
            Authorization=f"Bearer {token}"
        ),
        data=toolrun,
        params=params,
    )
    return ToolExecutionResponse.model_validate(resp)


def _log_diff(old_logs: list[str], new_logs: list[str]) -> list[str]:
    return new_logs[len(old_logs) :]


def get_operation_status(
    project_name: str,
    operation_id: str,
    workspace_url: str,
    api_version: str,
) -> ToolExecutionResponse:
    """Get the current status of an operation with a single API call.

    Args:
        project_name: The project name
        operation_id: The operation ID to query
        workspace_url: The workspace URL
        api_version: API version to send as query param

    Returns:
        ToolExecutionResponse with current operation status
    """
    url = f"{workspace_url.rstrip('/')}/tools/projects/{project_name}/operations/{operation_id}"
    params = {"api-version": api_version}
    debug(f"Getting status for operation {operation_id}")
    token = get_access_token()
    resp = _http_get(
        url=url,
        headers=AuthHeaders(  # type: ignore
            Authorization=f"Bearer {token}"
        ),
        params=params,
    )
    return ToolExecutionResponse.model_validate(resp)


def poll_operation(
    project_name: str,
    operation_id: str,
    workspace_url: str,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout_seconds: int = 3600,
    api_version: str = "2025-07-01-preview",
) -> ToolExecutionResponse:
    """Poll an operation until it reaches a terminal state.

    Args:
        project_name: The project name
        operation_id: The operation ID to poll
        workspace_url: The workspace URL
        poll_interval: Seconds between polls
        timeout_seconds: Maximum time to poll before timing out
        api_version: API version to send as query param

    Returns:
        ToolExecutionResponse when operation reaches terminal state

    Raises:
        PollError: If polling exceeds timeout_seconds
    """
    info(f"Polling operation {operation_id}")
    start_time = time.time()
    attempt = 0
    old_logs: list[str] = []
    spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])

    while True:
        attempt += 1
        if time.time() - start_time > timeout_seconds:
            msg = "Polling timeout exceeded"
            raise PollError(msg)

        # Use the single-call status function
        data = get_operation_status(project_name, operation_id, workspace_url, api_version=api_version)
        debug(f"Attempt {attempt} status={data.status}")

        logs = _extract_tool_report_logs(data.result.tool_report)  # type: ignore
        new_logs = _log_diff(old_logs, logs)
        if new_logs:
            # Clear spinner line before printing logs
            sys.stdout.write("\r\033[K")
            print("\n".join(new_logs))
        else:
            # Show spinner while waiting
            sys.stdout.write(f"\r{next(spinner)} Waiting for output...")
            sys.stdout.flush()
        old_logs = logs

        if data.status not in ("Active", "Pending", "NotStarted", "Running"):
            # Clear spinner line on completion
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
            return data
        time.sleep(poll_interval)


def run_and_poll(
    project_name: str,
    payload: ToolRunRequest,
    workspace_url: str,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout_seconds: int = 3600,
    api_version: str = "2025-07-01-preview",
) -> ToolExecutionResponse:
    start_resp = start_tool_run(project_name, payload, workspace_url, api_version=api_version)
    return poll_operation(
        project_name,
        start_resp.id,
        workspace_url,
        poll_interval=poll_interval,
        timeout_seconds=timeout_seconds,
        api_version=api_version,
    )


def cancel_operation(
    project_name: str,
    operation_id: str,
    workspace_url: str,
    api_version: str,
) -> None:
    """Request cancellation of a running operation.

    Posts to the Tools cancel endpoint. Returns parsed JSON body if present,
    otherwise an empty dict. Raises PollError for non-2xx responses or token issues.
    """
    if not project_name or not operation_id:
        msg = "project_name and operation_id required"
        raise PollError(msg)
    token = get_access_token()
    url = (
        f"{workspace_url.rstrip('/')}/tools/projects/{project_name}"
        f"/operations/{operation_id}:cancel"
    )
    params = {"api-version": api_version}
    info(f"POST {url}")

    class _EmptyBody(BaseModel):  # local throwaway model (no fields)
        pass

    _http_post(
        url=url,
        headers=AuthHeaders(  # type: ignore
            Authorization=f"Bearer {token}"
        ),
        data=_EmptyBody(),
        params=params,
    )


def list_operations(
    project_name: str,
    workspace_url: str,
    query: dict[str, str] | None = None,
    api_version: str = "2025-07-01-preview",
    *,
    page_size: int = 128,
) -> OperationsListResponse:
    """List operations for a project (single page).

    Args:
        project_name: Name of the project
        workspace_url: Base URL of the workspace
        query: Optional query parameters (e.g. {"status": "Running"})
        api_version: API version to send as query param
        page_size: Number of results per page (server default is 128)

    Returns:
        OperationsListResponse containing list of operations and optional next link

    Raises:
        PollError: If request fails or authentication issues occur
    """
    if query is None:
        query = {"reverse": "true"}
    query = {**query, "api-version": api_version}
    if "$top" not in query:
        query["$top"] = str(page_size)

    token = get_access_token()
    url = f"{workspace_url.rstrip('/')}/tools/projects/{project_name}/operations"
    debug(f"GET {url}")

    try:
        resp = _http_get(
            url=url,
            headers=AuthHeaders(Authorization=f"Bearer {token}"),  # type: ignore
            params=query,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            invalidate_token_cache()
            token = get_access_token()
            resp = _http_get(
                url=url,
                headers=AuthHeaders(Authorization=f"Bearer {token}"),  # type: ignore
                params=query,
            )
        else:
            raise

    return OperationsListResponse.model_validate(resp)


def list_operations_page(next_link: str) -> OperationsListResponse:
    """Fetch the next page of operations using a pagination link.

    Args:
        next_link: The nextLink URL from a previous OperationsListResponse

    Returns:
        OperationsListResponse containing the next page of operations

    Raises:
        PollError: If request fails or authentication issues occur
    """
    debug(f"Fetching next page from {next_link}")
    token = get_access_token()

    try:
        resp = _http_get(
            url=next_link,
            headers=AuthHeaders(Authorization=f"Bearer {token}"),  # type: ignore
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            invalidate_token_cache()
            token = get_access_token()
            resp = _http_get(
                url=next_link,
                headers=AuthHeaders(Authorization=f"Bearer {token}"),  # type: ignore
            )
        else:
            raise
    return OperationsListResponse.model_validate(resp)


def get_compute_status(
    project_name: str, workspace_url: str, api_version: str = "2025-07-01-preview"
) -> ComputeUsageModel:
    """Get the compute status/usage for the specified project.

    Args:
        project_name: Name of the project
        workspace_url: Workspace API endpoint URL
        api_version: API version to send as query param

    Returns:
        ComputeUsageModel containing usage information

    Raises:
        PollError: If the API call fails or authentication issues occur
    """

    token = get_access_token()
    url = f"{workspace_url.rstrip('/')}/tools/projects/{project_name}/computeUsage"
    params = {"api-version": api_version}
    info(f"GET {url}")

    resp = _http_get(
        url=url,
        headers=AuthHeaders(Authorization=f"Bearer {token}"),  # type: ignore
        params=params,
    )
    return ComputeUsageModel.model_validate(resp)


__all__ = [
    "JsonValidationError",
    "PollError",
    "cancel_operation",
    "get_compute_status",
    "list_operations",
    "list_operations_page",
    "poll_operation",
    "run_and_poll",
    "start_tool_run",
]


# ---------------------------------------------------------------------------
# Retry-enabled HTTP helpers
# ---------------------------------------------------------------------------


def _debug_http_response(label: str, resp: httpx.Response) -> None:
    """Dump HTTP response details at DEBUG level (safe for tests without full attrs).

    Truncates body if excessively large to avoid log flooding.
    """
    try:
        status = getattr(resp, "status_code", "?")
        ok = getattr(resp, "ok", "?")
        headers = getattr(resp, "headers", {}) or {}
        body = resp.text if hasattr(resp, "text") else "<no text>"
        body_out = body.strip("'\"")
        debug(f"{label}: status={status} ok={ok} headers={headers}\nBody:\n{body_out}")
    except Exception as ex:  # pragma: no cover - defensive
        debug(f"{label}: failed to dump response: {ex}")


_RETRYABLE_ERRORS = (TransientHTTPError, *_TRANSIENT_NETWORK_ERRORS)


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
)
def _http_get(
    *,
    url: str,
    headers: AuthHeaders,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    client = _get_persistent_client()
    resp = client.get(url, headers=headers.model_dump(), params=params)
    _debug_http_response(f"GET url: {url}", resp)
    resp.raise_for_status()
    return resp.json()


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(min=1, max=10),
    retry=retry_if_exception_type(_RETRYABLE_ERRORS),
)
def _http_post(
    *, url: str, headers: AuthHeaders, data: BaseModel, params: dict[str, str] | None = None
) -> dict[str, Any]:
    client = _get_persistent_client()
    resp = client.post(
        url,
        headers=headers.model_dump(),
        content=data.model_dump_json(exclude_none=True),
        params=params,
    )
    _debug_http_response(f"POST url: {url}", resp)
    resp.raise_for_status()

    # Handle empty responses (e.g., cancel operation returns no body)
    if not resp.content or not resp.content.strip():
        return {}

    return resp.json()


async def http_get_async(
    *,
    client: httpx.AsyncClient,
    url: str,
    headers: AuthHeaders,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Async GET request with timing instrumentation."""
    resp = await client.get(url, headers=headers.model_dump(), params=params)
    resp.raise_for_status()
    return resp.json()


async def http_post_async(
    *,
    client: httpx.AsyncClient,
    url: str,
    headers: AuthHeaders,
    json: dict[str, Any],
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Async POST request with timing instrumentation."""
    resp = await client.post(url, headers=headers.model_dump(), json=json, params=params)
    resp.raise_for_status()
    return resp.json()


__all__.extend(
    [
        "AuthHeaders",
        "HTTPStats",
        "ResponseTimeStats",
        "TransientHTTPError",
        "create_async_client",
        "get_http_stats",
        "http_get_async",
        "http_post_async",
        "print_http_stats_summary",
    ]
)


def create_async_client() -> httpx.AsyncClient:
    """Create an async httpx client with timing instrumentation.

    Use as async context manager:
        async with create_async_client() as client:
            ...
    """
    return _create_async_client()


def _extract_tool_report_logs(data: ToolReport) -> list[str]:
    """Extract and normalize tool report logs from a poll response.

    Accepts both array and newline-delimited string formats returned by the
    service. Empty or whitespace-only lines are removed. Non-dict inputs or
    missing structures yield an empty list.

    Args:
        data: Parsed JSON poll response.

    Returns:
        List of individual log lines (possibly empty).
    """
    if not data:
        return []
    # Accept dict or model instance
    logs_field: Any = data.get("logs", "") if isinstance(data, dict) else getattr(data, "logs", "")
    if isinstance(logs_field, list):
        raw_lines = [str(line) for line in logs_field]
    else:
        raw_lines = str(logs_field).splitlines()
    return [line for line in (entry.strip() for entry in raw_lines) if line]
