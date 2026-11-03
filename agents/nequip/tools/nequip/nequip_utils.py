"""Dependency-free execution and result helpers for a Discovery tool scaffold."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    input_dir: Path
    output_dir: Path
    work_dir: Path


def quick_setup(
    input_dir: str | Path = "/input",
    output_dir: str | Path = "/output",
    work_dir: str | Path = "/workdir",
) -> Workspace:
    """Validate mounted inputs and create working/output directories."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    workspace = Workspace(
        Path(input_dir).resolve(), Path(output_dir).resolve(), Path(work_dir).resolve()
    )
    if not workspace.input_dir.is_dir():
        raise FileNotFoundError(f"Input directory is not mounted: {workspace.input_dir}")
    for directory in (workspace.output_dir, workspace.work_dir):
        if directory.is_relative_to(workspace.input_dir):
            raise ValueError("Output and work directories must not be inside the input directory")
        directory.mkdir(parents=True, exist_ok=True)
    if (workspace.output_dir / "final_results.json").exists():
        raise FileExistsError("Use a fresh output directory; a previous result manifest exists")
    logging.info("Workspace initialized: %s", workspace)
    return workspace


def require_files(paths: Sequence[str | Path]) -> list[Path]:
    """Reject absent, directory, and empty inputs or declared output files."""
    resolved = []
    for value in paths:
        path = Path(value).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Required file is missing: {path}")
        if path.stat().st_size == 0:
            raise ValueError(f"Required file is empty: {path}")
        resolved.append(path)
    return resolved


def require_gpu() -> str:
    """Verify NVIDIA driver visibility; the scientific backend needs its own check."""
    executable = shutil.which("nvidia-smi")
    if executable is None:
        raise RuntimeError("GPU runtime is unavailable: nvidia-smi is missing")
    result = subprocess.run(
        [executable, "--query-gpu=name", "--format=csv,noheader"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if not result.stdout.strip():
        raise RuntimeError("GPU runtime is unavailable: no NVIDIA GPU was reported")
    logging.info("Visible GPU hardware: %s", result.stdout.strip())
    return result.stdout.strip()


def run_command(
    argv: Sequence[str],
    *,
    workspace: Workspace,
    log_name: str = "tool.log",
    timeout: float = 3600,
    expected_output_files: Sequence[str | Path],
) -> dict[str, object]:
    """Run explicit argv without a shell and verify declared scientific outputs."""
    if isinstance(argv, (str, bytes)) or not argv or any(not isinstance(a, str) for a in argv):
        raise ValueError("argv must be a nonempty sequence of strings, not a shell command")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", log_name):
        raise ValueError("log_name must be a simple filename")
    if not expected_output_files:
        raise ValueError("At least one expected scientific output must be declared")
    expected_paths = [
        Path(p).resolve() if Path(p).is_absolute() else (workspace.work_dir / p).resolve()
        for p in expected_output_files
    ]
    for path in expected_paths:
        if path.exists():
            raise FileExistsError(f"Use a fresh scientific output path: {path}")
    log_path = workspace.output_dir / log_name
    logging.info("Running command: %s", list(argv))
    with log_path.open("w", encoding="utf-8") as log:
        try:
            process = subprocess.run(
                list(argv), cwd=workspace.work_dir, stdout=log, stderr=subprocess.STDOUT,
                check=True, timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            logging.exception("Tool execution failed; log retained at %s", log_path)
            raise
    outputs = require_files(expected_paths)
    return {
        "command": list(argv),
        "returncode": process.returncode,
        "log_file": str(log_path),
        "output_files": [str(path) for path in outputs],
    }


def save_final_results(
    results: Mapping[str, object],
    output_files: Mapping[str, str | Path] | None = None,
    file_descriptions: Mapping[str, str] | None = None,
    *,
    workspace: Workspace,
    status: str = "completed",
) -> Path:
    """Persist the reference catalog result shape and explicitly declared artifacts."""
    if status not in {"completed", "failed"}:
        raise ValueError("status must be completed or failed")
    if status == "failed" and not results.get("error"):
        raise ValueError("Failed results must include an error")
    if status == "completed" and results.get("error"):
        raise ValueError("An error cannot be labeled completed")
    artifacts = dict(output_files or {})
    descriptions = dict(file_descriptions or {})
    if set(descriptions) - set(artifacts):
        raise ValueError("Every file description must refer to a declared output")
    for name in artifacts:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise ValueError(f"Invalid artifact name: {name}")
    sources = require_files([
        Path(value) if Path(value).is_absolute() else workspace.work_dir / value
        for value in artifacts.values()
    ])
    destinations = {
        name: workspace.output_dir / name / source.name
        for (name, _), source in zip(artifacts.items(), sources)
    }
    payload = {
        "status": status,
        "summary": dict(results),
        "output_files": {name: str(path) for name, path in destinations.items()},
        "file_descriptions": descriptions,
    }
    serialized = json.dumps(payload, indent=2, allow_nan=False)
    for (name, _), source in zip(artifacts.items(), sources):
        destination = destinations[name]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source != destination.resolve():
            shutil.copy2(source, destination)
    path = workspace.output_dir / "final_results.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(serialized + "\n", encoding="utf-8")
    temporary.replace(path)
    logging.info("Saved %s results: %s", status, path)
    return path


def quick_finish(*, workspace: Workspace) -> Path:
    """Ensure the task has explicitly written its final result manifest."""
    path = workspace.output_dir / "final_results.json"
    require_files([path])
    return path
