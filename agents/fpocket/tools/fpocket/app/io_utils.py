#!/usr/bin/env python3
"""Lightweight I/O + logging helpers shared by the tool entrypoint."""
import os
import json
import glob
import logging
from datetime import datetime, timezone

_logger = None


def setup_session_logger(action, output_dir):
    global _logger
    os.makedirs(output_dir, exist_ok=True)
    _logger = logging.getLogger(action)
    _logger.setLevel(logging.INFO)
    if not _logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        _logger.addHandler(h)
        fh = logging.FileHandler(os.path.join(output_dir, "run.log"))
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        _logger.addHandler(fh)
    return _logger


def log_message(msg):
    (_logger or logging).info(msg)


def log_step(title, detail=""):
    log_message(f"== {title} == {detail}")


def log_error(msg):
    (_logger or logging).error(msg)


def list_input_files(input_dir, patterns):
    files = []
    if os.path.isfile(input_dir):
        return [input_dir]
    for pat in patterns:
        files.extend(glob.glob(os.path.join(input_dir, pat)))
    return sorted(set(files))


def write_json(output_dir, name, data):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def write_final_results(output_dir, summary, artifacts=None):
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "artifacts": artifacts or [],
    }
    return write_json(output_dir, "final_results.json", payload)
