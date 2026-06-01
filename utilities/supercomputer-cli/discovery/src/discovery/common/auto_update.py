"""Background update checker for the Discovery CLI.

Modeled on the GitHub Copilot CLI's ``/update`` + ``/version`` flow.

How it works
------------
* On every CLI invocation, :func:`schedule_check` reads a small cache
  (``~/.discovery/update-check.json``). If the cache is fresh (default:
  refreshed within the last 24h) nothing happens. Otherwise a *daemon*
  thread is spawned to refresh the cache in the background — it never
  blocks the foreground command and never raises into the user's session.
* :func:`maybe_notify` is registered as an :mod:`atexit` hook by the
  root CLI callback. When the previously-cached check tells us that a
  newer release is available, a single colorized line is printed to
  ``stderr`` *after* the command's own output, so the notice never
  scrolls off the top of the terminal.
* The user-facing ``discovery update`` command (see
  :mod:`discovery.poll.cli_update`) calls :func:`fetch_update_info` and
  :func:`install_update` directly to do a *synchronous* check and apply.

Subdirectory-aware version comparison
-------------------------------------
The CLI ships as a subdirectory of the ``microsoft/discovery`` monorepo,
so the repository's main branch advances for many reasons (catalog
edits, doc updates, other utilities) that do not change the CLI itself.
We therefore query the GitHub *compare* API with
``compare/{current_sha}...main`` and only flag an update when at least
one of the changed files lives under ``utilities/supercomputer-cli/``.
This keeps notifications meaningful and avoids the "upgrade did
nothing" foot-gun that a naive HEAD-vs-HEAD comparison would produce.

Opt-out
-------
* Set ``DISCOVERY_NO_UPDATE_CHECK=1`` (one-shot, e.g. CI).
* Run ``discovery update --disable`` to persist the opt-out on disk.

Following a non-default branch
------------------------------
Set ``DISCOVERY_UPDATE_REF=<ref>`` to compare against a branch, tag, or
commit other than ``main``. Pair with ``DISCOVERY_UPDATE_REPO=owner/name``
to compare against a different repository (e.g. a fork). Useful for
following a release-candidate branch, validating a fork, or end-to-end
testing this checker.

Authentication (optional)
-------------------------
The check works fully unauthenticated against a public repository, but
GitHub limits anonymous traffic to 60 requests/hour per IP. The checker
opportunistically discovers a token from (in order)
``DISCOVERY_GITHUB_TOKEN``, ``GITHUB_TOKEN``, ``GH_TOKEN``, or
``gh auth token`` (if the GitHub CLI is on ``PATH``) and uses it to
raise that limit to 5000/hour. When the limit is exhausted the check
fails silently — the foreground command is never affected.

The check is silently skipped for editable / source installs (i.e. when
:func:`discovery._version.get_build_commit` returns ``"dev"``) because
those installs are not managed by ``uv tool``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.text import Text

from discovery._version import get_build_commit
from discovery.common.logging import debug
from discovery.common.paths import get_home_dir


CACHE_DIR_NAME = ".discovery"
CACHE_FILE_NAME = "update-check.json"
CHECK_INTERVAL_HOURS = 24
REQUEST_TIMEOUT_SECONDS = 5.0

REPO_OWNER = "microsoft"
REPO_NAME = "discovery"
CLI_SUBDIR = "utilities/supercomputer-cli/"
DEFAULT_BRANCH = "main"
GITHUB_COMPARE_URL_TEMPLATE = (
    "https://api.github.com/repos/{owner_repo}/compare/{base}...{head}"
)
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "discovery-cli-update-check",
}

# Override the upstream ref used for the compare. Useful for following
# a pre-release branch, validating a fork, or end-to-end testing the
# update flow without merging to main.
ENV_UPDATE_REF = "DISCOVERY_UPDATE_REF"

# Override the upstream repository (``owner/name``). Pairs with
# ``DISCOVERY_UPDATE_REF`` for fork-based testing or alternate channels.
ENV_UPDATE_REPO = "DISCOVERY_UPDATE_REPO"

# The microsoft/discovery repo is currently private, so unauthenticated
# requests return 404. We try these sources in order to get a token; if
# none of them succeed, the update check fails gracefully with a hint
# about ``gh auth login``.
TOKEN_ENV_VARS = ("DISCOVERY_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")

ENV_OPT_OUT = "DISCOVERY_NO_UPDATE_CHECK"
ENV_OPT_OUT_TRUTHY = {"1", "true", "True", "TRUE", "yes", "YES", "on", "ON"}

UPGRADE_COMMAND = "uv tool upgrade discovery"
DEV_COMMIT_SENTINEL = "dev"

# Categorical reasons reported by :class:`UpdateCheckError`. Defined as
# module constants so callers can match on them by symbol and so linters
# do not treat them as inline error-message strings.
REASON_INELIGIBLE = "ineligible"
REASON_NETWORK = "network"
REASON_PARSE_ERROR = "parse_error"
REASON_RATE_LIMITED = "rate_limited"
REASON_UNAUTHORIZED = "unauthorized"
REASON_NOT_FOUND = "not_found"
REASON_HTTP_ERROR = "http_error"


# ---------------------------------------------------------------------------
# Cache model
# ---------------------------------------------------------------------------


@dataclass
class UpdateCacheState:
    """Persistent state for the update checker.

    Attributes:
        last_checked: ISO-8601 UTC timestamp of the most recent
            successful network check, or ``None`` if the cache has
            never been populated.
        latest_commit: Short SHA (8 chars) of the newest commit on
            ``main`` that touched the CLI subdirectory at the time of
            the last successful check.
        latest_commit_date: ISO-8601 UTC committer date of
            ``latest_commit``.
        current_at_check: Short SHA the CLI binary reported at the time
            of the last successful check. Used to invalidate the cache
            when the user upgrades or downgrades between checks.
        notified_commit: Short SHA the user has already been notified
            about. Prevents the at-exit notice from re-printing the
            *same* update on every invocation while still allowing a
            fresh notice when a newer release appears.
        disabled: Persistent opt-out flag. When ``True`` no checks or
            notifications are performed regardless of cache freshness.
    """

    last_checked: str | None = None
    latest_commit: str | None = None
    latest_commit_date: str | None = None
    current_at_check: str | None = None
    notified_commit: str | None = None
    disabled: bool = False

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> UpdateCacheState:
        """Build a state instance from a JSON-decoded mapping.

        Unknown keys are ignored so older / newer cache files do not
        break compatibility.
        """
        kwargs: dict[str, Any] = {}
        valid = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in valid:
                kwargs[key] = value
        return cls(**kwargs)


@dataclass
class UpdateInfo:
    """Result of a synchronous update check."""

    current_commit: str
    latest_commit: str
    latest_commit_date: str = ""
    update_available: bool = False
    changed_files: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------


def _cache_path() -> Path:
    """Return the absolute path to the update-check cache file."""
    return get_home_dir() / CACHE_DIR_NAME / CACHE_FILE_NAME


def load_cache() -> UpdateCacheState:
    """Load the cached check state, returning an empty state on any error."""
    path = _cache_path()
    if not path.is_file():
        return UpdateCacheState()
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        debug(f"auto-update: ignoring unreadable cache {path}: {exc}")
        return UpdateCacheState()
    if not isinstance(data, dict):
        return UpdateCacheState()
    return UpdateCacheState.from_mapping(data)


def save_cache(state: UpdateCacheState) -> None:
    """Persist ``state`` to the cache file; silently swallow filesystem errors."""
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(state), indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as exc:
        debug(f"auto-update: failed to persist cache {path}: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """Return the current UTC time. Indirected for testability."""
    return datetime.now(tz=timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp, returning ``None`` on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _env_opt_out() -> bool:
    """``True`` when the env-var opt-out is enabled for this process."""
    return os.environ.get(ENV_OPT_OUT, "") in ENV_OPT_OUT_TRUTHY


def is_opted_out(state: UpdateCacheState | None = None) -> bool:
    """Return ``True`` when the user has opted out (env or persistent flag)."""
    if state is None:
        state = load_cache()
    return state.disabled or _env_opt_out()


def cache_is_stale(
    state: UpdateCacheState, *, interval_hours: int = CHECK_INTERVAL_HOURS
) -> bool:
    """``True`` when the cached check is older than ``interval_hours``."""
    last = _parse_iso(state.last_checked)
    if last is None:
        return True
    return _now() - last >= timedelta(hours=interval_hours)


def _should_check() -> bool:
    """Return ``True`` when this installation is eligible for update checks.

    Dev / editable installs are excluded — they're typically maintained
    via ``git pull`` rather than ``uv tool upgrade``, and ``get_build_commit``
    returns the sentinel ``"dev"`` for them.
    """
    return get_build_commit() != DEV_COMMIT_SENTINEL


def set_disabled(value: bool) -> None:
    """Persist the disable flag in the cache file."""
    state = load_cache()
    state.disabled = value
    save_cache(state)


# ---------------------------------------------------------------------------
# Network: fetch update info from GitHub
# ---------------------------------------------------------------------------


def _is_cli_path(filename: str) -> bool:
    """Return ``True`` when ``filename`` lives under the CLI subdirectory."""
    return filename.startswith(CLI_SUBDIR)


def _newest_cli_commit(commits: list[dict[str, Any]]) -> tuple[str, str] | None:
    """Return ``(short_sha, iso_date)`` of the newest CLI-touching commit.

    ``commits`` is the list returned by the GitHub compare endpoint,
    ordered from oldest to newest. We iterate from the end so the first
    match is the newest.
    """
    for entry in reversed(commits):
        files = entry.get("files")
        sha = entry.get("sha", "")
        if not sha:
            continue
        if isinstance(files, list) and any(
            _is_cli_path(str(f.get("filename", ""))) for f in files
        ):
            iso = (
                entry.get("commit", {})
                .get("committer", {})
                .get("date", "")
            )
            return sha[:8], iso
    return None


def _gh_cli_token(*, timeout: float = 3.0) -> str | None:
    """Return a GitHub token from ``gh auth token`` when available."""
    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        result = subprocess.run(
            [gh, "auth", "token"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        debug(f"auto-update: `gh auth token` failed: {exc}")
        return None
    if result.returncode != 0:
        return None
    token = result.stdout.strip()
    return token or None


def _resolve_github_token() -> str | None:
    """Discover a GitHub token from the environment or the ``gh`` CLI."""
    for var in TOKEN_ENV_VARS:
        value = os.environ.get(var)
        if value:
            return value
    return _gh_cli_token()


def _build_headers() -> dict[str, str]:
    """Build the request headers, including ``Authorization`` when available."""
    headers = dict(GITHUB_HEADERS)
    token = _resolve_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class UpdateCheckError(RuntimeError):
    """Raised by :func:`check_for_update` on any check failure.

    The :attr:`reason` attribute is a short machine-readable category
    that callers can switch on to produce tailored user messages:

    * ``"rate_limited"`` — GitHub's anonymous rate limit was exhausted.
      Hint: set ``GITHUB_TOKEN`` or run ``gh auth login``.
    * ``"unauthorized"`` — 401/403 without a rate-limit indicator
      (e.g. the repo is private and no valid token was found).
    * ``"not_found"`` — 404 from the compare endpoint, usually meaning
      the installed commit is no longer reachable from the upstream
      ref (force-push, deleted branch, wrong ``DISCOVERY_UPDATE_REPO``).
    * ``"http_error"`` — Any other non-2xx response.
    * ``"network"`` — Connection / DNS / TLS / timeout failure.
    * ``"parse_error"`` — Successful HTTP but unexpected payload shape.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)
        self.reason = reason
        self.detail = detail


def _classify_http_error(exc: httpx.HTTPStatusError) -> UpdateCheckError:
    """Translate an :class:`httpx.HTTPStatusError` into ``UpdateCheckError``."""
    status = exc.response.status_code
    body = ""
    try:
        body = exc.response.text or ""
    except Exception:  # pragma: no cover - defensive
        body = ""
    body_lower = body.lower()
    if status == 403 and (
        "rate limit" in body_lower
        or exc.response.headers.get("x-ratelimit-remaining") == "0"
    ):
        return UpdateCheckError(REASON_RATE_LIMITED, body[:200])
    if status in (401, 403):
        return UpdateCheckError(REASON_UNAUTHORIZED, body[:200])
    if status == 404:
        return UpdateCheckError(REASON_NOT_FOUND, body[:200])
    return UpdateCheckError(REASON_HTTP_ERROR, f"HTTP {status}: {body[:160]}")


def check_for_update(
    current_commit: str, *, timeout: float = REQUEST_TIMEOUT_SECONDS
) -> UpdateInfo:
    """Synchronously query GitHub for available updates.

    Args:
        current_commit: The short SHA of the currently installed build
            (typically :func:`discovery._version.get_build_commit`).
        timeout: HTTP timeout in seconds.

    Returns:
        :class:`UpdateInfo` describing the comparison.

    Raises:
        UpdateCheckError: On any failure to obtain a usable answer.
            Inspect :attr:`UpdateCheckError.reason` for the category.
    """
    if not current_commit or current_commit == DEV_COMMIT_SENTINEL:
        raise UpdateCheckError(
            REASON_INELIGIBLE, "build commit is unknown or local-dev"
        )
    upstream_ref = os.environ.get(ENV_UPDATE_REF) or DEFAULT_BRANCH
    upstream_repo = (
        os.environ.get(ENV_UPDATE_REPO) or f"{REPO_OWNER}/{REPO_NAME}"
    )
    url = GITHUB_COMPARE_URL_TEMPLATE.format(
        owner_repo=upstream_repo, base=current_commit, head=upstream_ref
    )
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url, headers=_build_headers())
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise _classify_http_error(exc) from exc
    except httpx.HTTPError as exc:
        raise UpdateCheckError(REASON_NETWORK, str(exc)) from exc
    except ValueError as exc:
        raise UpdateCheckError(REASON_PARSE_ERROR, str(exc)) from exc

    if not isinstance(data, dict):
        raise UpdateCheckError(
            REASON_PARSE_ERROR, "compare response is not an object"
        )

    ahead_by = data.get("ahead_by", 0)
    if not isinstance(ahead_by, int) or ahead_by <= 0:
        return UpdateInfo(
            current_commit=current_commit,
            latest_commit=current_commit,
            update_available=False,
        )

    changed_files = [
        str(f.get("filename", ""))
        for f in data.get("files", [])
        if isinstance(f, dict)
    ]
    cli_changes = [f for f in changed_files if _is_cli_path(f)]
    if not cli_changes:
        return UpdateInfo(
            current_commit=current_commit,
            latest_commit=current_commit,
            update_available=False,
            changed_files=changed_files,
        )

    commits = data.get("commits", [])
    if not isinstance(commits, list) or not commits:
        raise UpdateCheckError(
            REASON_PARSE_ERROR, "compare response missing 'commits' list"
        )

    newest = _newest_cli_commit(commits)
    if newest is None:
        # ``ahead_by`` and ``files`` disagreed with the per-commit view
        # (rare: GitHub may omit per-commit ``files`` for very large
        # diffs). Fall back to the tip of ``head`` so the user still
        # learns that *something* has changed.
        tip = commits[-1]
        latest_sha = str(tip.get("sha", ""))[:8]
        latest_date = (
            tip.get("commit", {}).get("committer", {}).get("date", "")
        )
    else:
        latest_sha, latest_date = newest

    return UpdateInfo(
        current_commit=current_commit,
        latest_commit=latest_sha,
        latest_commit_date=latest_date or "",
        update_available=latest_sha != current_commit,
        changed_files=cli_changes,
    )


def fetch_update_info(
    current_commit: str, *, timeout: float = REQUEST_TIMEOUT_SECONDS
) -> UpdateInfo | None:
    """Silent-failure wrapper around :func:`check_for_update`.

    Returns ``None`` on any error. Use :func:`check_for_update` directly
    when you need the failure category (e.g. to prompt for authentication
    on rate-limit failures).
    """
    try:
        return check_for_update(current_commit, timeout=timeout)
    except UpdateCheckError as exc:
        debug(f"auto-update: check failed [{exc.reason}]: {exc.detail}")
        return None


# ---------------------------------------------------------------------------
# Background scheduling
# ---------------------------------------------------------------------------


def _refresh_cache_worker() -> None:
    """Daemon-thread worker: refresh the cache and never raise."""
    try:
        current = get_build_commit()
        info = fetch_update_info(current)
        if info is None:
            return
        state = load_cache()
        # Invalidate the "already-notified" memo when the user has
        # upgraded since the last check, so we don't suppress new
        # legitimate notifications for the *next* release.
        if state.current_at_check != current:
            state.notified_commit = None
        state.last_checked = _now().isoformat()
        state.latest_commit = info.latest_commit
        state.latest_commit_date = info.latest_commit_date or None
        state.current_at_check = current
        save_cache(state)
    except Exception as exc:  # pragma: no cover - defensive
        debug(f"auto-update: background refresh crashed: {exc}")


def schedule_check() -> threading.Thread | None:
    """Spawn a background refresh if the cache is stale and not opted out.

    Returns the worker thread (mainly for tests) or ``None`` when no
    check was scheduled.
    """
    if not _should_check():
        return None
    state = load_cache()
    if is_opted_out(state):
        return None
    if not cache_is_stale(state):
        return None
    thread = threading.Thread(
        target=_refresh_cache_worker,
        name="discovery-update-check",
        daemon=True,
    )
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------


def _pending_update(state: UpdateCacheState) -> tuple[str, str] | None:
    """Return ``(latest_sha, latest_date)`` when an update is pending, else ``None``."""
    if not state.latest_commit:
        return None
    current = get_build_commit()
    if state.latest_commit == current:
        return None
    # Only suppress when we've already notified about *this exact*
    # upstream commit; if a newer upstream commit appears we want to
    # re-notify.
    if state.notified_commit == state.latest_commit:
        return None
    return state.latest_commit, state.latest_commit_date or ""


def format_notification(
    current_commit: str, latest_commit: str, latest_date: str
) -> str:
    """Return the plain-text notification body (used by tests)."""
    date_part = ""
    if latest_date:
        date_part = f" ({latest_date.split('T')[0]})"
    return (
        "A new version of the Discovery CLI is available"
        f"{date_part}: {current_commit} -> {latest_commit}. "
        f"Run `{UPGRADE_COMMAND}` or `discovery update` to upgrade."
    )


def maybe_notify() -> None:
    """Emit the at-exit update notification when one is pending.

    Safe to call at any time: silently no-ops when checks are disabled,
    when no update is cached, or when the cached update has already
    been announced to the user.
    """
    if not _should_check():
        return
    state = load_cache()
    if is_opted_out(state):
        return
    pending = _pending_update(state)
    if pending is None:
        return
    latest_sha, latest_date = pending

    # Build a Rich-styled message but degrade gracefully if rendering
    # fails (e.g. during interpreter shutdown when stderr is gone).
    try:
        console = Console(stderr=True, highlight=False, soft_wrap=True)
        text = Text()
        text.append("\n🔔 ", style="bold yellow")
        text.append(
            "A new version of the Discovery CLI is available",
            style="yellow",
        )
        if latest_date:
            text.append(f" ({latest_date.split('T')[0]})", style="dim")
        text.append("\n   Current: ", style="dim")
        text.append(get_build_commit(), style="cyan")
        text.append("  ->  Latest: ", style="dim")
        text.append(latest_sha, style="green")
        text.append("\n   Run ", style="dim")
        text.append(UPGRADE_COMMAND, style="bold")
        text.append(" or ", style="dim")
        text.append("discovery update", style="bold")
        text.append(" to upgrade.\n", style="dim")
        console.print(text)
    except Exception:  # pragma: no cover - defensive
        try:
            sys.stderr.write(
                "\n"
                + format_notification(get_build_commit(), latest_sha, latest_date)
                + "\n"
            )
        except Exception:
            return

    state.notified_commit = latest_sha
    save_cache(state)


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


class UpgradeError(RuntimeError):
    """Raised when the upgrade subprocess cannot be launched."""


def install_update(*, dry_run: bool = False) -> int:
    """Run ``uv tool upgrade discovery``.

    Args:
        dry_run: If ``True``, return ``0`` without invoking ``uv``.

    Returns:
        The subprocess exit status (``0`` on success).

    Raises:
        UpgradeError: If the ``uv`` binary is not on ``PATH``.
    """
    if shutil.which("uv") is None:
        msg = "`uv` is not installed or not on PATH; cannot self-upgrade."
        raise UpgradeError(msg)
    cmd = ["uv", "tool", "upgrade", "discovery"]
    if dry_run:
        return 0
    proc = subprocess.run(cmd, check=False)
    return proc.returncode


__all__ = [
    "CACHE_DIR_NAME",
    "CACHE_FILE_NAME",
    "CHECK_INTERVAL_HOURS",
    "DEV_COMMIT_SENTINEL",
    "ENV_OPT_OUT",
    "ENV_UPDATE_REF",
    "ENV_UPDATE_REPO",
    "UPGRADE_COMMAND",
    "UpdateCacheState",
    "UpdateCheckError",
    "UpdateInfo",
    "UpgradeError",
    "cache_is_stale",
    "check_for_update",
    "fetch_update_info",
    "format_notification",
    "install_update",
    "is_opted_out",
    "load_cache",
    "maybe_notify",
    "save_cache",
    "schedule_check",
    "set_disabled",
]
