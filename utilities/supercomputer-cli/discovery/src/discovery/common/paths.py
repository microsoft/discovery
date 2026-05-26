"""Cross-platform home directory and config path resolution.

Handles WSL environments where ``Path.home()`` may resolve to a
Windows-mounted path (``/mnt/c/Users/...``) instead of the native Linux
home (``/home/...``), depending on which Python interpreter is used or
how the CLI is invoked.

The ``DISCOVERY_CONFIG_PATH`` environment variable can always be set to
override automatic resolution.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


CONFIG_FILE_NAME = ".discovery-sc-config"


def _debug(msg: str) -> None:
    """Lazy debug log that avoids import cycles at module init."""
    try:
        from discovery.common.logging import debug

        debug(msg)
    except Exception:  # pragma: no cover
        pass


def _info(msg: str) -> None:
    """Lazy info log that avoids import cycles at module init."""
    try:
        from discovery.common.logging import info

        info(msg)
    except Exception:  # pragma: no cover
        pass


def is_wsl() -> bool:
    """Detect if running inside Windows Subsystem for Linux.

    Checks ``WSL_DISTRO_NAME`` first (set by the WSL init system), then
    falls back to ``/proc/version`` which contains "microsoft" (WSL1) or
    "WSL2" for any WSL kernel, even when the env var is not propagated
    (e.g. python invoked via systemd or a wrapper that scrubs env).
    """
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/version", encoding="utf-8") as f:
            release = f.read().lower()
    except OSError:
        return False
    return "microsoft" in release


def _windows_home_on_wsl() -> Path | None:
    """Resolve the Windows user-profile home as a WSL path, or ``None``.

    Uses ``cmd.exe /c echo %USERPROFILE%`` and ``wslpath -u`` to convert
    the Windows-native path (e.g. ``C:\\Users\\Bob``) into the WSL mount
    path (``/mnt/c/Users/Bob``). Returns ``None`` if WSL interop is
    disabled, either utility is missing, or the conversion fails.
    """
    win_path = _run_capture(["cmd.exe", "/c", "echo %USERPROFILE%"])
    if not win_path or win_path.startswith("%"):
        _debug(f"windows home: cmd.exe returned {win_path!r}, skipping")
        return None
    wsl_path = _run_capture(["wslpath", "-u", win_path])
    if not wsl_path:
        _debug(f"windows home: wslpath -u {win_path!r} failed, skipping")
        return None
    _debug(f"windows home: resolved {win_path!r} -> {wsl_path}")
    return Path(wsl_path)


def _run_capture(cmd: list[str]) -> str | None:
    """Run ``cmd`` with a short timeout; return trimmed stdout or ``None``."""
    try:
        result = subprocess.run(
            cmd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip().strip("\r\n")
    return out or None


def _wsl_home_candidates() -> list[Path]:
    """Return alternative home directories to search on WSL.

    When ``Path.home()`` points at the Windows-mounted home
    (``/mnt/c/Users/...``) the native Linux home from the passwd
    database is the most likely location of an existing config file,
    and vice-versa.
    """
    primary = Path.home()
    seen = {primary}
    candidates: list[Path] = []

    # The passwd database entry gives the "true" Linux home directory.
    # On WSL this is typically /home/<user> even when $HOME or
    # Path.home() has been overridden to a Windows-mounted path.
    try:
        import pwd  # Unix-only; safe because is_wsl() implies Linux

        pw_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        if pw_home not in seen:
            candidates.append(pw_home)
            seen.add(pw_home)
    except Exception:
        pass

    # $HOME may differ from both Path.home() and pwd when set by
    # the caller (e.g. VS Code Remote-WSL, wsl.exe wrapper).
    env_home = os.environ.get("HOME")
    if env_home:
        env_path = Path(env_home)
        if env_path not in seen:
            candidates.append(env_path)
            seen.add(env_path)

    # The Windows-mounted user profile (e.g. /mnt/c/Users/Bob). In a
    # typical Linux-home WSL session, pwd and $HOME both point to
    # /home/<user>, so this is the only way to discover a config file
    # that was written from a Windows-side invocation (wsl.exe,
    # VS Code Remote-WSL on Windows shell, etc.).
    win_home = _windows_home_on_wsl()
    if win_home is not None and win_home not in seen:
        candidates.append(win_home)
        seen.add(win_home)

    return candidates


def get_home_dir() -> Path:
    """Return the preferred home directory, WSL-aware.

    On WSL, if ``Path.home()`` points at a Windows-mounted directory
    (``/mnt/…``) and the native Linux home has a ``.discovery``
    directory, the Linux home is preferred so that config and logs
    stay co-located.

    Returns:
        Resolved home directory :class:`~pathlib.Path`.
    """
    primary = Path.home()
    if not is_wsl():
        return primary

    for candidate in _wsl_home_candidates():
        # Prefer a candidate that already has discovery artefacts.
        if (candidate / CONFIG_FILE_NAME).exists() or (candidate / ".discovery").exists():
            return candidate

    return primary


def get_config_file_path() -> Path:
    """Resolve the discovery configuration file path.

    Resolution order:

    1. ``DISCOVERY_CONFIG_PATH`` environment variable (explicit override).
    2. ``~/.discovery-sc-config`` via ``Path.home()``.
    3. On WSL only: search alternative home directories when the
       primary location does not contain an existing config file.
    4. Fall back to the primary ``Path.home()`` location (will trigger
       the interactive configure flow if the file is absent).

    Returns:
        Resolved :class:`~pathlib.Path` to the config file.
    """
    # 1. Explicit override — always wins.
    override = os.environ.get("DISCOVERY_CONFIG_PATH")
    if override:
        resolved = Path(override)
        _debug(f"config path: DISCOVERY_CONFIG_PATH override -> {resolved}")
        return resolved

    # 2. Primary location.
    primary = Path.home() / CONFIG_FILE_NAME
    if primary.exists():
        _debug(f"config path: primary Path.home() match -> {primary}")
        return primary

    # 3. WSL fallback: check alternative home directories.
    if is_wsl():
        _debug(f"config path: primary {primary} not found; trying WSL candidates")
        for candidate_home in _wsl_home_candidates():
            candidate = candidate_home / CONFIG_FILE_NAME
            if candidate.exists():
                # Info-level so users see which non-primary location
                # actually supplied their config — crucial for diagnosing
                # cross-context write/read mismatches.
                _info(
                    f"Using config at {candidate} "
                    f"(Path.home()={Path.home()} has no {CONFIG_FILE_NAME})"
                )
                return candidate
        _debug("config path: no WSL candidate had a config file")

    # 4. Nothing found — return primary so the configure flow runs.
    _debug(f"config path: no config found; returning primary {primary}")
    return primary


__all__ = [
    "CONFIG_FILE_NAME",
    "get_config_file_path",
    "get_home_dir",
    "is_wsl",
]
