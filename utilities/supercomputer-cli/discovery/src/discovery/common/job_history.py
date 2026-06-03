"""Local history of jobs submitted from this machine.

Each ``discovery job start`` / ``discovery job batch`` / ``discovery job
vscode`` call appends a single JSON-Lines record to
``~/.discovery/job-history.jsonl`` so that future invocations can
filter ``discovery job list``-style queries to just *your* submissions
— even when the service still returns jobs from teammates or from
other machines you own.

Why JSON-Lines
--------------
* Append-only, lock-friendly: each line is a complete record that can
  be written atomically with a single ``write()`` (well under the
  POSIX-guaranteed ``PIPE_BUF`` of 512 bytes for tiny records, and we
  serialize bigger ones under an in-process lock for portability).
* Easy to read with ``cat``, ``jq``, ``head -n``, etc.
* No native-dep / DB requirement (this CLI runs in heterogeneous
  environments — Linux laptops, WSL, AKS pods).
* Forward-compatible: unknown keys are ignored by the loader, so we
  can add fields without breaking older releases that read the file.

Privacy
-------
Everything written stays on disk. Records include the command string
the user typed and the local hostname so multi-machine users can tell
where a job originated. Disable the recording entirely with
``DISCOVERY_NO_JOB_HISTORY=1`` (one-shot) or call :func:`clear` to
wipe the file. The recorder *never* fails the submit on I/O error —
recording is opportunistic.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import threading
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from discovery.common.logging import debug
from discovery.common.paths import get_home_dir


HISTORY_DIR_NAME = ".discovery"
HISTORY_FILE_NAME = "job-history.jsonl"
SCHEMA_VERSION = 1

# Truthy values that disable history recording when set on
# ``DISCOVERY_NO_JOB_HISTORY``.
ENV_OPT_OUT = "DISCOVERY_NO_JOB_HISTORY"
ENV_OPT_OUT_TRUTHY = {"1", "true", "True", "TRUE", "yes", "YES", "on", "ON"}

# Submit-mode tags written into each record so downstream readers can
# tell the start / batch / vscode commands apart without re-parsing
# argv.
MODE_START = "start"
MODE_BATCH = "batch"
MODE_VSCODE = "vscode"

# In-process lock that serializes appends from a single Python process.
# ``discovery job batch`` submits via a :class:`ThreadPoolExecutor`, so
# multiple worker threads will land in :func:`record_submission`
# concurrently; without the lock interleaved writes could corrupt the
# JSONL file. We intentionally do *not* take a cross-process file lock
# (no POSIX-portable, dependency-free way to do that reliably) — two
# different ``discovery`` processes writing simultaneously could in
# theory interleave large records, but in practice each line is well
# under the kernel's atomic-write threshold for ``O_APPEND`` writes on
# Linux/macOS/WSL.
_WRITE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Record model
# ---------------------------------------------------------------------------


@dataclass
class JobHistoryEntry:
    """A single ``discovery job <submit>`` invocation record.

    All fields are optional except ``operation_id`` and ``submitted_at``
    so older / newer records can still be deserialized when the schema
    grows.

    Attributes:
        operation_id: Service-side operation UUID returned by
            ``start_tool_run``.
        submitted_at: UTC ISO-8601 timestamp of the local submit call.
        hostname: ``socket.gethostname()`` at submit time. Helps users
            with several machines pointing at the same Discovery
            workspace tell submissions apart.
        command: The user's bash command (the first positional arg to
            ``discovery job start`` / ``batch``).
        tool_id: ``env_cfg.tool_id`` at submit time.
        nodepool_id: Effective nodepool ID (after ``--pool`` resolution).
        project_name: ``env_cfg.project_name`` at submit time.
        workspace_url: ``env_cfg.workspace_url`` at submit time. Used to
            scope queries by workspace so the user doesn't see entries
            from a different Discovery environment.
        mode: One of :data:`MODE_START`, :data:`MODE_BATCH`,
            :data:`MODE_VSCODE`.
        cli_argv: The full ``sys.argv`` at submit time. Useful for
            re-running a job verbatim.
        schema_version: :data:`SCHEMA_VERSION` at write time.
    """

    operation_id: str
    submitted_at: str
    hostname: str = ""
    command: str = ""
    tool_id: str = ""
    nodepool_id: str = ""
    project_name: str = ""
    workspace_url: str = ""
    mode: str = MODE_START
    cli_argv: list[str] = field(default_factory=list)
    # Azure principal that was logged in (``az account show --query
    # user.name``) at submit time. Used by ``discovery job cancel
    # --since`` to avoid cancelling jobs that were submitted from this
    # machine but under a *different* Azure login (e.g., a shared
    # workstation, a build agent that re-authenticates between users).
    # Empty for entries written before this field was added — those
    # are treated as "matches any user" so backwards compatibility is
    # preserved.
    azure_username: str = ""
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> JobHistoryEntry | None:
        """Construct an entry from a JSON-decoded mapping, ignoring unknown keys.

        Returns ``None`` when required fields are missing or malformed
        so callers can simply skip bad lines.
        """
        op_id = data.get("operation_id")
        ts = data.get("submitted_at")
        if not isinstance(op_id, str) or not op_id:
            return None
        if not isinstance(ts, str) or not ts:
            return None
        kwargs: dict[str, Any] = {}
        valid = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key in valid:
                kwargs[key] = value
        try:
            return cls(**kwargs)
        except (TypeError, ValueError) as exc:
            debug(f"job-history: skipping malformed entry {op_id}: {exc}")
            return None


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


def history_path() -> Path:
    """Return the absolute path to ``~/.discovery/job-history.jsonl``."""
    return get_home_dir() / HISTORY_DIR_NAME / HISTORY_FILE_NAME


def _env_opt_out() -> bool:
    """``True`` when the user has set ``DISCOVERY_NO_JOB_HISTORY``."""
    return os.environ.get(ENV_OPT_OUT, "") in ENV_OPT_OUT_TRUTHY


def is_disabled() -> bool:
    """Return ``True`` when history recording is disabled for this process."""
    return _env_opt_out()


def _utc_now_iso() -> str:
    """ISO-8601 UTC timestamp with a trailing ``Z`` (RFC 3339-style)."""
    return (
        datetime.now(tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def record_submission(
    operation_id: str,
    *,
    command: str = "",
    tool_id: str = "",
    nodepool_id: str = "",
    project_name: str = "",
    workspace_url: str = "",
    mode: str = MODE_START,
    cli_argv: list[str] | None = None,
    hostname: str | None = None,
    submitted_at: str | None = None,
    azure_username: str = "",
) -> JobHistoryEntry | None:
    """Append an entry to the local job-history file.

    Returns the entry on success, or ``None`` when recording was
    skipped (opted-out or the operation_id was empty). I/O errors are
    logged at DEBUG and swallowed — recording must never break the
    user's submit.
    """
    if is_disabled():
        debug(f"job-history: opt-out active, not recording {operation_id}")
        return None
    if not operation_id:
        return None

    entry = JobHistoryEntry(
        operation_id=operation_id,
        submitted_at=submitted_at or _utc_now_iso(),
        hostname=hostname if hostname is not None else _safe_hostname(),
        command=command,
        tool_id=tool_id,
        nodepool_id=nodepool_id,
        project_name=project_name,
        workspace_url=workspace_url,
        mode=mode,
        cli_argv=list(cli_argv) if cli_argv is not None else [],
        azure_username=azure_username,
    )

    line = json.dumps(asdict(entry), separators=(",", ":")) + "\n"
    path = history_path()
    try:
        with _WRITE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except OSError as exc:
        debug(f"job-history: failed to append {operation_id}: {exc}")
        return None
    return entry


def _safe_hostname() -> str:
    """Return :func:`socket.gethostname` with an empty-string fallback."""
    try:
        return socket.gethostname() or ""
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def load_history(
    *,
    workspace_url: str | None = None,
    project_name: str | None = None,
    hostname: str | None = None,
    since: datetime | None = None,
) -> list[JobHistoryEntry]:
    """Load all history entries, optionally narrowed by metadata.

    Args:
        workspace_url: When provided, only return entries that match
            this workspace exactly (so a user pointing at a different
            Discovery environment doesn't see unrelated jobs).
        project_name: When provided, narrow further by project name.
        hostname: When provided, narrow to entries written on this
            host. Useful for users who roam between machines.
        since: When provided, only return entries with
            ``submitted_at >= since``. Naive datetimes are interpreted
            as UTC.

    Returns:
        Entries in *write order* (oldest first). Malformed / unreadable
        records are skipped silently.
    """
    path = history_path()
    if not path.is_file():
        return []

    if since is not None and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    out: list[JobHistoryEntry] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                entry = JobHistoryEntry.from_mapping(data)
                if entry is None:
                    continue
                if not _entry_matches(
                    entry,
                    workspace_url=workspace_url,
                    project_name=project_name,
                    hostname=hostname,
                    since=since,
                ):
                    continue
                out.append(entry)
    except OSError as exc:
        debug(f"job-history: failed to read {path}: {exc}")
        return []
    return out


def _entry_matches(
    entry: JobHistoryEntry,
    *,
    workspace_url: str | None,
    project_name: str | None,
    hostname: str | None,
    since: datetime | None,
) -> bool:
    """Apply the optional filter predicates from :func:`load_history`."""
    if workspace_url is not None and entry.workspace_url != workspace_url:
        return False
    if project_name is not None and entry.project_name != project_name:
        return False
    if hostname is not None and entry.hostname != hostname:
        return False
    if since is not None:
        ts = _parse_iso(entry.submitted_at)
        if ts is None or ts < since:
            return False
    return True


def local_operation_ids(
    *,
    workspace_url: str | None = None,
    project_name: str | None = None,
    hostname: str | None = None,
    since: datetime | None = None,
) -> set[str]:
    """Return the set of operation IDs in the local history.

    Convenience wrapper for use as a ``filter_fn`` predicate in the
    ``discovery job list`` family of commands.
    """
    return {
        entry.operation_id
        for entry in load_history(
            workspace_url=workspace_url,
            project_name=project_name,
            hostname=hostname,
            since=since,
        )
    }


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO-8601 timestamp; return ``None`` on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# Supported time-unit suffixes for :func:`parse_since`. Order matters
# only for documentation — the parser looks up by character.
_SINCE_UNITS: dict[str, timedelta] = {
    "s": timedelta(seconds=1),
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "w": timedelta(weeks=1),
}


def parse_since(value: str) -> datetime:
    """Parse a ``--since`` value into a UTC ``datetime`` cutoff.

    Accepts:
      * Absolute date: ``YYYY-MM-DD`` (UTC midnight).
      * Relative shorthand: ``<N><unit>`` where unit is one of
        ``s``/``m``/``h``/``d``/``w`` (seconds / minutes / hours /
        days / weeks). Examples: ``30s``, ``10m``, ``24h``, ``7d``,
        ``2w``.

    Raises:
        ValueError: If ``value`` does not match either format.
    """
    text = (value or "").strip()
    if not text:
        msg = "empty --since value"
        raise ValueError(msg)
    now = datetime.now(tz=timezone.utc)
    if len(text) >= 2 and text[:-1].isdigit() and text[-1] in _SINCE_UNITS:
        n = int(text[:-1])
        return now - n * _SINCE_UNITS[text[-1]]
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        msg = (
            f"Invalid --since value: {value!r}. Expected YYYY-MM-DD or a "
            "duration like '30s', '10m', '24h', '7d', '2w'."
        )
        raise ValueError(msg) from exc


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------


def clear() -> int:
    """Delete the entire history file. Returns the number of entries removed."""
    path = history_path()
    if not path.is_file():
        return 0
    count = sum(1 for _ in path.read_text(encoding="utf-8").splitlines() if _.strip())
    try:
        path.unlink()
    except OSError as exc:
        debug(f"job-history: failed to delete {path}: {exc}")
        return 0
    return count


def prune(
    *, keep_count: int | None = None, keep_since: datetime | None = None
) -> int:
    """Rewrite the history file keeping only the most recent entries.

    Args:
        keep_count: Keep at most this many entries (newest first).
        keep_since: Keep entries with ``submitted_at >= keep_since``.

    Returns:
        Number of entries removed.
    """
    entries = load_history()
    if not entries:
        return 0

    keep: list[JobHistoryEntry] = list(entries)

    if keep_since is not None:
        if keep_since.tzinfo is None:
            keep_since = keep_since.replace(tzinfo=timezone.utc)
        keep = [
            e for e in keep
            if (ts := _parse_iso(e.submitted_at)) is not None and ts >= keep_since
        ]

    if keep_count is not None and len(keep) > keep_count:
        keep = keep[-keep_count:]

    removed = len(entries) - len(keep)
    if removed <= 0:
        return 0

    _rewrite(keep)
    return removed


def _rewrite(entries: Iterable[JobHistoryEntry]) -> None:
    """Atomically replace the history file with ``entries`` (write order)."""
    path = history_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with _WRITE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tmp.open("w", encoding="utf-8") as fh:
                for entry in entries:
                    fh.write(
                        json.dumps(asdict(entry), separators=(",", ":")) + "\n"
                    )
            tmp.replace(path)
    except OSError as exc:
        debug(f"job-history: rewrite failed: {exc}")
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


__all__ = [
    "ENV_OPT_OUT",
    "HISTORY_DIR_NAME",
    "HISTORY_FILE_NAME",
    "MODE_BATCH",
    "MODE_START",
    "MODE_VSCODE",
    "SCHEMA_VERSION",
    "JobHistoryEntry",
    "clear",
    "history_path",
    "is_disabled",
    "load_history",
    "local_operation_ids",
    "parse_since",
    "prune",
    "record_submission",
]
