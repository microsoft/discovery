"""Shared helper functions for CLI commands."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx
import typer

from discovery.common.logging import debug, error, info, pretty_debug
from discovery.common.paths import get_config_file_path  # re-exported for backward compat
from discovery.poll.models.config import EnvConfig

from .selection import select_archive, select_project_and_related, select_tool
from .vscode_layer import build_named_tunnel_command


DEFAULT_INTERVAL = 5
DEFAULT_TIMEOUT = 3600


def format_service_error(exc: httpx.HTTPStatusError) -> str:
    """Format an HTTP error from the service into a human-readable message.

    Extracts details from the JSON response body when available (Azure-style
    ``{"error": {"code": "...", "message": "..."}}`` or plain ``{"message": "..."}``)
    and falls back to the raw response text.
    """
    resp = exc.response
    status = resp.status_code
    url = str(exc.request.url)

    parts: list[str] = [f"Service request failed (HTTP {status}) for {url}"]

    body = resp.text.strip() if resp.text else ""
    if body:
        try:
            data = json.loads(body)
            # Azure-style: {"error": {"code": "...", "message": "...", "details": [...]}}
            err_obj = data.get("error", data)
            code = err_obj.get("code", "")
            message = err_obj.get("message", "")
            if code:
                parts.append(f"  Code: {code}")
            if message:
                parts.append(f"  Message: {message}")
            # Render nested details if present
            details = err_obj.get("details")
            if details and isinstance(details, list):
                for detail in details:
                    d_code = detail.get("code", "")
                    d_msg = detail.get("message", "")
                    line = f"    - {d_code}: {d_msg}" if d_code else f"    - {d_msg}"
                    parts.append(line)
        except (json.JSONDecodeError, AttributeError):
            # Not JSON - include raw body (truncated to keep output manageable)
            truncated = body[:500] + ("..." if len(body) > 500 else "")
            parts.append(f"  Response: {truncated}")

    return "\n".join(parts)



def render_error_with_details(err: dict) -> str:
    """Render error with nested details."""
    stack = [(err, 0)]
    sb = []

    while len(stack) > 0:
        e, i = stack.pop()

        if i == 0:
            sb.append("\n")
            sb.append(" " * (len(stack) * 2))
            sb.append(e["message"])

        if not e["details"] or not i < len(e["details"]):
            continue

        stack.append((e, i + 1))
        stack.append((e["details"][i], 0))

    return "".join(sb)


_MAX_NAME_LENGTH = 24
_HASH_LENGTH = 8


def sanitize_username(username: str) -> str:
    """Sanitize a username for use as resource names.

    If the username contains '@' (email format), the full username is hashed and
    appended. The result is capped at 24 characters (Azure storage account name
    limit); excess username characters are rolled into the hash for uniqueness.

    Args:
        username: Raw username (email or plain string)

    Returns:
        Sanitized username suitable for resource names (e.g., 'user-a1b2c3d4'),
        guaranteed to be at most 24 characters.

    Raises:
        ValueError: If username contains no valid alphanumeric characters
    """
    if "@" in username:
        local_part, domain = username.split("@", 1)
        # Sanitize local part (keep alphanumeric only)
        sanitized_local = "".join(c for c in local_part if c.isalnum())
        if not sanitized_local:
            msg = f"Username local part '{local_part}' contains no alphanumeric characters."
            raise ValueError(msg)
        max_local = _MAX_NAME_LENGTH - 1 - _HASH_LENGTH
        if len(sanitized_local) <= max_local:
            # Fits without truncation – use domain-only hash (backward compatible)
            domain_hash = hashlib.sha256(domain.encode()).hexdigest()[:_HASH_LENGTH]
            return f"{sanitized_local}-{domain_hash}".lower()
        # Must truncate – hash full username so excess chars contribute to uniqueness
        username_hash = hashlib.sha256(username.encode()).hexdigest()[:_HASH_LENGTH]
        sanitized_local = sanitized_local[:max_local]
        return f"{sanitized_local}-{username_hash}".lower()

    # No '@' found, treat as plain username
    sanitized = "".join(c for c in username if c.isalnum() or c == "-")
    if not sanitized:
        msg = f"Username '{username}' contains no valid characters."
        raise ValueError(msg)
    sanitized = sanitized.lower()
    if len(sanitized) <= _MAX_NAME_LENGTH:
        return sanitized
    # Truncate and add hash so excess characters contribute to uniqueness
    username_hash = hashlib.sha256(username.encode()).hexdigest()[:_HASH_LENGTH]
    max_prefix = _MAX_NAME_LENGTH - 1 - _HASH_LENGTH
    return f"{sanitized[:max_prefix]}-{username_hash}"


def get_raw_azure_username() -> str:
    """Get the raw Azure CLI logged-in user's email/username.

    Returns:
        Raw username (e.g. 'user@domain.com') as returned by Azure CLI.

    Raises:
        RuntimeError: If unable to get the Azure username.
    """
    cmd = ["az", "account", "show", "--query", "user.name", "-o", "tsv"]
    debug(f"Getting Azure username: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            error(f"Failed to get Azure username: {result.stderr.strip()}")
            msg = "Could not determine Azure username. Ensure you are logged in with 'az login'."
            raise RuntimeError(msg)

        username = result.stdout.strip()
        if not username:
            msg = "Azure username is empty. Ensure you are logged in with 'az login'."
            raise RuntimeError(msg)

        return username
    except OSError as exc:
        error(f"Azure CLI 'az' not found: {exc}")
        msg = "Azure CLI not found. Please install it to continue."
        raise RuntimeError(msg) from exc


def get_azure_username() -> str:
    """Get the Azure CLI logged-in user's username, sanitized for resource names.

    Returns:
        Sanitized Azure username (e.g. 'user-a1b2c3d4').

    Raises:
        RuntimeError: If unable to get the Azure username.
    """
    username = get_raw_azure_username()
    try:
        sanitized_username = sanitize_username(username)
        debug(f"Using Azure username: {username} -> sanitized: {sanitized_username}")
        return sanitized_username
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def get_location_from_supercomputer(env_cfg: EnvConfig) -> str | None:
    """Get the Azure location from the nodepool's supercomputer resource.

    Args:
        env_cfg: Environment configuration with nodepool_id

    Returns:
        Location string if found, None otherwise
    """
    if not env_cfg.nodepool_id:
        return None

    # Extract supercomputer ID from nodepool ID
    # Nodepool ID format: .../supercomputers/{sc}/nodepools/{np}
    if "/supercomputers/" not in env_cfg.nodepool_id:
        return None

    idx = env_cfg.nodepool_id.find("/nodepools/")
    if idx == -1:
        return None
    supercomputer_id = env_cfg.nodepool_id[:idx]

    try:
        cmd = [
            "az",
            "resource",
            "show",
            "--ids",
            supercomputer_id,
            "--query",
            "location",
            "-o",
            "tsv",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            location = result.stdout.strip()
            debug(f"Using location '{location}' from supercomputer")
            return location
    except Exception as ex:
        debug(f"Could not determine location from supercomputer: {ex}")

    return None


def _load_with_migration(env_file: Path) -> EnvConfig:
    """Load an EnvConfig from disk, re-saving if the model normalised the input.

    Migration of fields removed by past CLI upgrades happens inside the
    pydantic validator (``EnvConfig._strip_removed_fields`` and
    ``NodepoolInfo._strip_removed_fields``) — they silently scrub a known
    allowlist of historical field names while leaving ``extra='forbid'``
    strict for unknown names (so typos still surface as ``ValidationError``).

    This helper just persists the cleaned form back to disk when it differs
    from the on-disk content, so subsequent loads are silent.
    """
    raw = env_file.read_text(encoding="utf-8")
    env_cfg = EnvConfig.model_validate_json(raw)
    cleaned = env_cfg.model_dump_json(by_alias=True, indent=4)
    if cleaned.strip() != raw.strip():
        try:
            env_file.write_text(cleaned, encoding="utf-8")
        except OSError as e:
            debug(f"could not rewrite cleaned config to {env_file}: {e}")
    return env_cfg


def run_configure_if_needed(env_file: Path | None = None) -> EnvConfig:
    """Load config from file, or run configure if file doesn't exist.

    Args:
        env_file: Path to the configuration file. If None, uses ~/.discovery-sc-config

    Returns:
        Loaded or newly created EnvConfig
    """
    if env_file is None:
        env_file = get_config_file_path()
    if not env_file.exists() or env_file.stat().st_size == 0:
        info("No configuration found. Running initial setup...")
        # Import configure command and invoke it - avoid circular import
        from .cli_configure import configure

        configure()
        # After configure completes, the file should exist
        if not env_file.exists():
            error("Configuration was not saved. Please run 'discovery configure' manually.")
            raise typer.Exit(code=1)
    env_cfg = _load_with_migration(env_file)
    # Re-anchor the path: JSON may embed a stale path recorded in a
    # different WSL/Windows context. Subsequent save() calls must write
    # back to the file we actually loaded from.
    if env_cfg.path != env_file:
        debug(f"re-anchoring env_cfg.path from {env_cfg.path} to {env_file}")
        env_cfg.path = env_file
    return env_cfg


def load_project_config(env_file: Path | None = None) -> EnvConfig:
    """Load project config, running configure if needed.

    Args:
        env_file: Path to the configuration file. If None, uses ~/.discovery-sc-config
    """
    if env_file is None:
        env_file = get_config_file_path()
    env_cfg = run_configure_if_needed(env_file)
    if not env_cfg.project_ready:
        debug("load_project_config: project not ready, running selection")
        select_project_and_related(env_cfg)
        # Persist the completed selection so the user isn't re-prompted
        # on the next invocation.
        info(f"Persisting updated project selection to {env_cfg.path}")
        env_cfg.save()
    else:
        debug("start(): using project from env (complete set present)")
    return env_cfg


def load_tool_config(config_tool: bool, env_cfg: EnvConfig) -> None:
    """Load tool config, prompting if needed."""
    if not env_cfg.tool_id or config_tool:
        select_tool(env_cfg)
    else:
        debug("start(): using tool from env")


def prepare_command(
    command: str,
    env_cfg: EnvConfig,
    vscode: bool,
    additional_ports: list[str],
    tunnel_name: str | None = None,
    provider: str | None = None,
) -> str:
    """Return the effective command, optionally prefixing with tunnel info.

    When *tunnel_name* is provided the ``code tunnel --name`` mode is used.
    By default this authenticates via GitHub device-flow; pass
    ``provider="microsoft"`` to authenticate with a Microsoft account
    instead.
    """
    if not vscode:
        return command

    if not tunnel_name:
        msg = "--tunnel-name is required for VS Code tunnel mode"
        raise ValueError(msg)

    debug(
        f"prepare_command(): using named tunnel mode, name={tunnel_name} "
        f"provider={provider or '<default>'}"
    )
    return build_named_tunnel_command(command, tunnel_name, provider=provider)


def emit_env(env_cfg: EnvConfig) -> None:
    """Emit environment config for debugging."""
    # JSON mode: preserve existing behavior (always emit env object) regardless of verbosity
    pretty_debug(env_cfg)


def ensure_archive(env_cfg: EnvConfig) -> None:
    """Ensure the Archive blob container is configured for tool-run I/O persistence.

    Dispatches by API version (V1 datacontainer / V2 storagecontainer); only
    prompts when the relevant ID is unset.
    """
    from discovery.poll.models.api_version import ApiVersion

    is_legacy = ApiVersion.parse(env_cfg.api_version).uses_dataassets_uri
    needed_id = env_cfg.datacontainer_id if is_legacy else env_cfg.storagecontainer_id
    if not needed_id:
        select_archive(env_cfg)
        env_cfg.save()


# Back-compat shim: existing call sites use the older name.
ensure_datacontainer = ensure_archive


__all__ = [
    "DEFAULT_INTERVAL",
    "DEFAULT_TIMEOUT",
    "emit_env",
    "ensure_archive",
    "ensure_datacontainer",
    "format_service_error",
    "get_azure_username",
    "get_config_file_path",
    "get_location_from_supercomputer",
    "get_raw_azure_username",
    "load_project_config",
    "load_tool_config",
    "prepare_command",
    "render_error_with_details",
    "run_configure_if_needed",
    "sanitize_username",
]
