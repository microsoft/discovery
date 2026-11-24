"""Container entry point: mesh, solve, and measure a frozen, pre-validated case.

Invoked as ``python -m discovery_physics.worker /input /output``. Executes only
allowlisted OpenFOAM binaries as argument vectors (no shell), then writes
``/output/evidence.json``. It never decides acceptance.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .core.hashing import sha256_json, sha256_text
from .core.models import Command, Diagnostics
from .openfoam.extract import extract

DERIVED_ZERO = {"C", "Ccx", "Ccy", "Ccz", "Vc"}


def frozen_files(case: Path) -> dict[str, str]:
    """Text of every input that defines the problem, with run-horizon keys normalized."""
    out: dict[str, str] = {}
    for root in ("0", "constant", "system"):
        base = case / root
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(case).as_posix()
            if not p.is_file() or rel.startswith("constant/polyMesh/") or (
                root == "0" and p.name in DERIVED_ZERO
            ):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            if rel == "system/controlDict":
                text = re.sub(r"(?m)^\s*(endTime|startFrom)\s+[^;]*;\s*$", "", text)
            out[rel] = text
    return out


def frozen_sha256(case: Path) -> str:
    return sha256_json({k: sha256_text(v) for k, v in frozen_files(case).items()})


def _run(argv: list[str], case: Path, log: Path, timeout: float) -> int:
    with log.open("w", encoding="utf-8") as fh:
        try:
            proc = subprocess.run(argv, cwd=case, stdout=fh, stderr=subprocess.STDOUT,
                                  timeout=max(1.0, timeout), check=False)
            return proc.returncode
        except subprocess.TimeoutExpired:
            fh.write("\nWORKER: wall-clock budget exhausted; process killed\n")
            return -9


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    inp, out = Path(args[0]), Path(args[1])
    plan = json.loads((inp / "plan.json").read_text(encoding="utf-8"))
    diagnostics = Diagnostics.model_validate(plan["diagnostics"])
    deadline = time.monotonic() + float(plan["budget"]["wall_seconds"])
    case = out / "case"
    if case.exists():
        raise SystemExit("output case already exists; refusing to overwrite")
    # Content-only copy: host bind mounts (Windows/9p) refuse chmod/utime metadata.
    for src in sorted((inp / "case").rglob("*")):
        dst = case / src.relative_to(inp / "case")
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    timings: dict[str, float] = {}
    mesh_ok = True
    if plan["mode"] == "fresh":
        for i, raw in enumerate(plan["mesh"]):
            cmd = Command.model_validate(raw)
            t0 = time.monotonic()
            rc = _run([cmd.executable, *cmd.args], case, case / f"log.{i:02d}.{cmd.executable}",
                      deadline - time.monotonic())
            timings[f"mesh.{i}.{cmd.executable}"] = time.monotonic() - t0
            mesh_ok &= rc == 0
            if rc:
                break
        rc = _run(["checkMesh"], case, case / "log.checkMesh", deadline - time.monotonic())
        mesh_ok &= rc == 0
    observed = frozen_sha256(case)
    exit_code = None
    ranks = int(plan["budget"].get("mpi_ranks", 1))
    attempt = int(plan["attempt"])
    if mesh_ok and ranks > 1:
        dec = ["decomposePar", "-force"] + (["-latestTime"] if plan["mode"] == "continue" else [])
        t0 = time.monotonic()
        mesh_ok &= _run(dec, case, case / f"log.decomposePar.{attempt:02d}", deadline - time.monotonic()) == 0
        timings["decompose"] = time.monotonic() - t0
    if mesh_ok:
        t0 = time.monotonic()
        argv = ["foamRun"] if ranks == 1 else [
            "mpirun", "--oversubscribe", "-np", str(ranks), "foamRun", "-parallel"]
        exit_code = _run(argv, case, case / f"log.foamRun.{attempt:02d}", deadline - time.monotonic())
        timings["solve"] = time.monotonic() - t0
        if ranks > 1:
            t0 = time.monotonic()
            rc = _run(["reconstructPar", "-newTimes"], case, case / f"log.reconstructPar.{attempt:02d}",
                      max(60.0, deadline - time.monotonic()))
            timings["reconstruct"] = time.monotonic() - t0
            if rc:
                exit_code = exit_code or 97  # results not recoverable as a single-domain case
            for proc_dir in case.glob("processor*"):
                shutil.rmtree(proc_dir, ignore_errors=True)
    for func in ("writeCellCentres", "writeCellVolumes"):
        if not (case / "0" / ("C" if func == "writeCellCentres" else "Vc")).exists():
            _run(["foamPostProcess", "-func", func, "-time", "0"], case, case / f"log.{func}", 600)
    metrics = extract(case, diagnostics, exit_code, float(plan["end_time"]), mesh_ok)
    metrics.put("setup.case_hash_matches", observed == plan["frozen_sha256"], source="worker re-hash")
    if plan.get("reference_hashes"):
        files = frozen_files(case)
        metrics.put("setup.reference_files_match", all(
            rel in files and sha256_text(files[rel]) == digest
            for rel, digest in plan["reference_hashes"].items()), source="worker re-hash")
    build = ""
    for log in sorted(case.glob("log.foamRun*")):
        m = re.search(r"^Build\s*:\s*(\S+)", log.read_text(encoding="utf-8", errors="replace"), re.M)
        build = m.group(1) if m else build
    figures: list[str] = []
    figures_error = None
    try:
        from .openfoam.figures import render

        figures = render(case, diagnostics, out / "figures")
    except Exception as exc:  # illustrative only; never an evidence error
        figures_error = f"{type(exc).__name__}: {exc}"[:300]
    evidence = {
        "metrics": {k: v.model_dump(mode="json") for k, v in metrics.values.items()},
        "errors": metrics.errors,
        "runtime": {"openfoam_build": build, "distribution": "OpenFOAM Foundation",
                    "timings_s": timings, "observed_frozen_sha256": observed, "figures": figures,
                    "figures_error": figures_error, "mpi_ranks": ranks,
                    "worker_uid": os.getuid() if hasattr(os, "getuid") else None},
    }
    (out / "evidence.json").write_text(json.dumps(evidence, indent=1, allow_nan=False), encoding="utf-8")
    (out / "evidence.sha256").write_text(sha256_json(evidence), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
