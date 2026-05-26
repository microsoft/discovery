"""Runtime version and build information for the Discovery CLI.

Resolves the package version and git commit hash at import time:
- Base version from ``importlib.metadata`` (single source of truth in pyproject.toml).
- Git commit from ``direct_url.json`` for ``uv tool install`` / ``pip install git+...``
  installs (PEP 610), falling back to ``git rev-parse`` for editable/local dev installs.

The composed ``__version__`` looks like ``0.1.0+g1a2b3c4`` for git installs
or ``0.1.0+dev`` when the commit cannot be determined.
"""

from __future__ import annotations

import json
import subprocess
from importlib.metadata import PackageNotFoundError
from importlib.metadata import distribution as _md_distribution
from importlib.metadata import version as _md_version


def _get_base_version() -> str:
    """Read the package version from installed metadata."""
    try:
        return _md_version("discovery")
    except PackageNotFoundError:
        return "0.0.0"


def _get_commit_from_metadata() -> str | None:
    """Extract git commit SHA from PEP 610 direct_url.json if available."""
    try:
        dist = _md_distribution("discovery")
    except Exception:
        return None

    raw = dist.read_text("direct_url.json")
    if not raw:
        return None

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    vcs_info = data.get("vcs_info")
    if isinstance(vcs_info, dict) and vcs_info.get("vcs") == "git":
        commit = vcs_info.get("commit_id", "")
        if commit:
            return commit[:8]
    return None


def _get_commit_from_git() -> str | None:
    """Fall back to running ``git rev-parse`` for editable / local installs."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def get_build_commit() -> str:
    """Return the short git commit hash or ``'dev'``."""
    return _get_commit_from_metadata() or _get_commit_from_git() or "dev"


def get_version_string() -> str:
    """Return the full version string, e.g. ``'0.1.0+g1a2b3c4'``."""
    base = _get_base_version()
    commit = get_build_commit()
    if commit == "dev":
        return f"{base}+dev"
    return f"{base}+g{commit}"


__all__ = [
    "get_build_commit",
    "get_version_string",
]
