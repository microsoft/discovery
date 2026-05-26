"""Rich-based lightweight logging facade used by discovery components.

API intentionally tiny and stable:
  info(msg)
  warn(msg)
  error(msg)
  success(msg)
  debug(msg)
  set_level(name)

Design goals:
  - Zero external configuration required.
  - Colorful, structured, timestamped output with Rich.
  - Cheap no-op for debug when level > DEBUG.
  - Thread-safe console re-use.

Environment:
  LOG_LEVEL can preset level (DEBUG, INFO, WARN, ERROR).

Note: success() is a convenience (green) not a standard logging level.
"""
from __future__ import annotations

import logging as _stdlib_logging
import os
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.pretty import Pretty
from rich.text import Text


__all__ = [
    "debug",
    "error",
    "info",
    "is_verbose",
    "pp",
    "pretty_debug",
    "set_level",
    "success",
    "warn",
]

# ---------------- internal state -----------------
@dataclass
class _State:
    level: int = 20  # INFO
    console: Console | None = None
    file_logger: _stdlib_logging.Logger | None = None

_STATE = _State()


def _ensure_file_logger() -> _stdlib_logging.Logger:
    """Lazily create a per-invocation log file under ~/.discovery/logs/.

    Each CLI run gets its own file named ``<timestamp>_<pid>.log``.
    The first line records the full command that was invoked.
    """
    if _STATE.file_logger is not None:
        return _STATE.file_logger

    # Resolve home via the shared WSL-aware helper when available,
    # falling back to Path.home() to avoid circular-import issues
    # during early startup.
    try:
        from discovery.common.paths import get_home_dir

        home = get_home_dir()
    except Exception:
        home = Path.home()
    log_dir = home / ".discovery" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Unique filename per invocation: YYYYMMDDTHHMMSSmmm_<pid>.log
    ts = time.strftime("%Y%m%dT%H%M%S") + f"{time.time() % 1:.3f}"[1:]  # milliseconds
    log_file = log_dir / f"{ts}_{os.getpid()}.log"

    logger = _stdlib_logging.getLogger(f"discovery.file.{os.getpid()}")
    logger.setLevel(_stdlib_logging.DEBUG)
    # Avoid duplicate handlers on repeated calls (e.g. tests)
    if not logger.handlers:
        handler = _stdlib_logging.FileHandler(
            str(log_file),
            encoding="utf-8",
        )
        handler.setLevel(_stdlib_logging.DEBUG)
        handler.setFormatter(
            _stdlib_logging.Formatter(
                "%(asctime)s %(levelname)-5s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
    # Prevent propagation to root logger / console
    logger.propagate = False
    _STATE.file_logger = logger

    # Write the command as the first log line
    cmd_line = shlex.join(sys.argv) if hasattr(shlex, "join") else " ".join(sys.argv)
    start_time = time.strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"=== invocation: {cmd_line}  (started {start_time}) ===")
    return logger

_LEVELS: dict[str, int] = {
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "WARNING": 30,
    "ERROR": 40,
}

_COLOR = {
    10: "dim",      # DEBUG
    20: "cyan",     # INFO
    30: "yellow",   # WARN
    40: "red",      # ERROR
}

_PREFIX = {
    10: "DBG",
    20: "INF",
    30: "WRN",
    40: "ERR",
    99: "SUC",
}

def _ensure_console() -> Console:
    if _STATE.console is None:
        _STATE.console = Console(file=sys.stdout, highlight=False, soft_wrap=True)
    return _STATE.console

def set_level(name: str) -> None:
    """Set global log level (case-insensitive)."""
    lvl = _LEVELS.get(name.upper())
    if lvl is not None:
        _STATE.level = lvl

def _ts() -> str:
    return time.strftime("%H:%M:%S")

_FILE_LOG_LEVEL = {
    10: _stdlib_logging.DEBUG,
    20: _stdlib_logging.INFO,
    30: _stdlib_logging.WARNING,
    40: _stdlib_logging.ERROR,
    99: _stdlib_logging.INFO,   # success -> INFO in file
}

def _log(level: int, message: str, *, style: str | None = None) -> None:
    # Always write to the debug log file regardless of console level
    try:
        file_lvl = _FILE_LOG_LEVEL.get(level, _stdlib_logging.DEBUG)
        _ensure_file_logger().log(file_lvl, message)
    except Exception:  # pragma: no cover - never break CLI for log I/O
        pass

    if level < _STATE.level:
        return
    console = _ensure_console()
    prefix = _PREFIX.get(level, "LOG")
    color = style or _COLOR.get(level, "white")
    text = Text(f"[{_ts()}] {prefix} ", style="bold " + color)
    text.append(message, style=color)
    console.print(text, overflow="ignore")

# Public API wrappers

def info(msg: str) -> None:
    _log(20, msg)

def warn(msg: str) -> None:
    _log(30, msg)

def error(msg: str) -> None:
    _log(40, msg)

def success(msg: str) -> None:
    # treat as level between info and warn for visibility
    _log(99, msg, style="green")

def debug(msg: str) -> None:
    _log(10, msg, style="dim")


def is_verbose() -> bool:
    """Check if logging is at DEBUG level (verbose mode)."""
    return _STATE.level <= 10


def pretty_debug(obj, *, label: str | None = None, expand: bool = False) -> None:
    """Pretty-print a Python object at DEBUG level using Rich's Pretty renderer.

    Only emits to console when global level is DEBUG (<=10) and LOG_PRETTY_DEBUG
    is not disabled.

    Args:
        obj: Object to inspect.
        label: Optional heading prefix line.
        expand: Expand all containers (maps to Pretty(expand_all=...)).
    """
    # Always write to the debug log file
    try:
        file_prefix = f"{label}: " if label else ""
        _ensure_file_logger().debug(f"{file_prefix}{obj}")
    except Exception:  # pragma: no cover
        pass

    if _STATE.level > 10:
        return
    if os.getenv("LOG_PRETTY_DEBUG", "1") in {"0", "false", "False"}:
        return
    console = _ensure_console()
    try:
        if label:
            console.print(Text(f"[{_ts()}] DBG ", style="bold dim") + Text(label, style="dim"))
        console.print(Pretty(obj, expand_all=expand, indent_guides=True))
    except Exception:  # pragma: no cover - defensive fallback
        debug(f"(pretty_debug fallback) {label+': ' if label else ''}{obj}")


# Alias resembling typical pprint usage pattern
pp = pretty_debug

# Initialize from environment
set_level(os.getenv("LOG_LEVEL", "INFO"))

# Optional one-time environment dump when starting at DEBUG for quick triage.
if os.getenv("LOG_PRETTY_DEBUG_INIT") and _STATE.level <= 10:
    pretty_debug({
        "python": sys.version.split()[0],
        "argv": sys.argv,
        "cwd": os.getcwd(),
    }, label="env:init")
