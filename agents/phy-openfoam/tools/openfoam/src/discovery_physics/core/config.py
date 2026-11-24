"""Operator configuration. Lives beside the run store, never inside a case bundle.

``%LOCALAPPDATA%/DiscoveryPhysics/config.json`` (or ``DISCOVERY_PHYSICS_CONFIG``)::

    {"allow_unenforced_limits": false, "max_concurrent_runs": 2, "queue_timeout_s": 21600}

Environment variables override the file (``DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS=1``,
``DISCOVERY_PHYSICS_MAX_CONCURRENT``). These are operator decisions; the agent skill
forbids changing them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {"allow_unenforced_limits": False, "max_concurrent_runs": 2, "queue_timeout_s": 21600}
DEFAULT_IMAGE = "localhost/phy-openfoam:0.2.1"
DEFAULTS.update({"image": DEFAULT_IMAGE, "runtime": "auto"})


def home() -> Path:
    override = os.environ.get("DISCOVERY_PHYSICS_HOME")
    if override:
        return Path(override).expanduser()
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DiscoveryPhysics"


def config_path() -> Path:
    env = os.environ.get("DISCOVERY_PHYSICS_CONFIG")
    return Path(env) if env else home() / "config.json"


def load() -> dict:
    cfg = dict(DEFAULTS)
    path = config_path()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        cfg.update({k: data[k] for k in DEFAULTS if k in data})
    if os.environ.get("DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS") is not None:
        cfg["allow_unenforced_limits"] = os.environ["DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS"] == "1"
    if os.environ.get("DISCOVERY_PHYSICS_MAX_CONCURRENT"):
        cfg["max_concurrent_runs"] = int(os.environ["DISCOVERY_PHYSICS_MAX_CONCURRENT"])
    cfg["max_concurrent_runs"] = max(1, min(int(cfg["max_concurrent_runs"]), 64))
    cfg["allow_unenforced_limits"] = cfg["allow_unenforced_limits"] is True
    cfg["queue_timeout_s"] = max(1, int(cfg["queue_timeout_s"]))
    for key in ("image", "runtime"):
        value = cfg[key]
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            raise ValueError(f"operator configuration {key} must be a nonempty string")
        cfg[key] = value.strip()
    return cfg
