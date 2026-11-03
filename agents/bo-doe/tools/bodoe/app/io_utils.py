"""Discovery platform I/O conventions: /input -> /workdir -> /output."""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from typing import Optional

import numpy as np

__all__ = ["quick_setup", "quick_finish", "save_final_results",
           "load_table", "save_table", "JSONSafeEncoder"]

_STATE = {"input": "/input", "output": "/output", "work": "/workdir"}


class JSONSafeEncoder(json.JSONEncoder):
    """JSON encoder that understands NumPy scalars and arrays."""

    def default(self, o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            v = float(o)        # float32/float16 reach here; float64 does not
            return v if np.isfinite(v) else None
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, (np.bool_,)):
            return bool(o)
        return super().default(o)


def _json_safe(o):
    """Recursively replace non-finite floats with ``None``.

    ``json.JSONEncoder.default`` is never called for ``float`` or its subclass
    ``np.float64``, so NaN/inf must be removed before encoding; otherwise the
    file contains bare ``NaN`` tokens that strict JSON parsers reject.
    """
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    if isinstance(o, np.ndarray):
        return _json_safe(o.tolist())
    if isinstance(o, (float, np.floating)):
        v = float(o)
        return v if np.isfinite(v) else None
    return o


def quick_setup(input_dir: str = "/input", output_dir: str = "/output",
                work_dir: str = "/workdir", session_name: str = "bodoe") -> dict:
    """Prepare directories and logging. Call once at the top of every script."""
    for d in (output_dir, work_dir):
        os.makedirs(d, exist_ok=True)
    _STATE.update(input=input_dir, output=output_dir, work=work_dir)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(os.path.join(output_dir, f"{session_name}.log"),
                                      mode="w", encoding="utf-8"),
                  logging.StreamHandler()])
    try:
        os.chdir(work_dir)
    except OSError:
        pass
    logging.info("bodoe session started at %s", datetime.now().isoformat())
    logging.info("input=%s output=%s work=%s", input_dir, output_dir, work_dir)
    return dict(_STATE)


def save_final_results(results: dict, output_files: Optional[dict] = None,
                       file_descriptions: Optional[dict] = None) -> str:
    """Write ``final_results.json`` -- MANDATORY at the end of every job.

    Non-finite numbers (NaN, inf) are written as ``null`` so the file is
    strict JSON.
    """
    payload = _json_safe({
        "results": results or {},
        "output_files": output_files or {},
        "file_descriptions": file_descriptions or {},
        "generated_at": datetime.now().isoformat(),
    })
    path = os.path.join(_STATE["work"], "final_results.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, cls=JSONSafeEncoder, allow_nan=False)
    logging.info("wrote %s", path)
    return path


def quick_finish() -> list[str]:
    """Copy every artefact from the working directory to ``/output``."""
    out, work = _STATE["output"], _STATE["work"]
    copied = []
    if os.path.abspath(out) == os.path.abspath(work):
        return copied
    for name in os.listdir(work):
        src = os.path.join(work, name)
        dst = os.path.join(out, name)
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            copied.append(name)
        except OSError as exc:  # pragma: no cover
            logging.warning("could not copy %s: %s", name, exc)
    logging.info("copied %d artefacts to %s", len(copied), out)
    return copied


def load_table(path: str, columns: Optional[list[str]] = None):
    """Load a CSV/TSV/NPY/JSON table into a pandas DataFrame."""
    import pandas as pd
    ext = os.path.splitext(path)[1].lower()
    if ext == ".npy":
        arr = np.load(path)
        df = pd.DataFrame(arr, columns=columns)
    elif ext in (".tsv", ".tab"):
        df = pd.read_csv(path, sep="\t")
    elif ext == ".json":
        df = pd.read_json(path)
    elif ext in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)
    if columns is not None and ext != ".npy":
        df = df[columns]
    return df


def save_table(df, path: str) -> str:
    """Save a DataFrame as CSV in the working directory."""
    full = path if os.path.isabs(path) else os.path.join(_STATE["work"], path)
    df.to_csv(full, index=False)
    return full
