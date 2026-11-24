"""Generate real Foundation-14 function-object output for extractor fixtures (no acceptance path).

The CLI requires --project-root, --results-dir and a new --out export directory.

Runs a short laminar channel (6,000 cells) inside the worker image with surfaceFieldValue,
forces, forceCoeffs, yPlus, probes and volFieldValue quantities through the normal
guarded runner, then copies postProcessing/ and the solver log for tests. This is
health-only fixture generation, never a physical-validation or finalization path.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

from discovery_physics.openfoam import runner
from discovery_physics.openfoam.monitors import set_end_time

if __package__:
    from .live_paths import DEFAULT_BUNDLE, bundle, run_store, work_directory
    from .result_paths import ResultPaths, add_arguments
else:
    from live_paths import DEFAULT_BUNDLE, bundle, run_store, work_directory
    from result_paths import ResultPaths, add_arguments

QUANTITIES = [
    {"name": "p_in", "function": "surfaceFieldValue", "column": "areaAverage(p)",
        "settings": {"select": "patch", "patch": "inlet",
                   "operation": "areaAverage", "fields": "(p)"}},
    {"name": "wall_force", "function": "forces", "column": "total_x",
     "settings": {"patches": "(walls)", "rho": "rhoInf", "rhoInf": "1", "CofR": "(0 0 0)"}},
    {"name": "wall_coeffs", "function": "forceCoeffs", "column": "Cd",
     "settings": {"patches": "(walls)", "rho": "rhoInf", "rhoInf": "1", "CofR": "(0 0 0)",
                  "liftDir": "(0 1 0)", "dragDir": "(1 0 0)", "pitchAxis": "(0 0 1)",
                  "magUInf": "0.01", "lRef": "0.5", "Aref": "0.0005"}},
    {"name": "yplus", "function": "yPlus", "column": "average", "settings": {}},
    {"name": "probe_mid", "function": "probes", "column": "p",
     "settings": {"fields": "(p)", "probeLocations": "((0.25 0.005 0.0005))"}},
    {"name": "u_max", "function": "volFieldValue", "column": "max(U)",
     "settings": {"cellZone": "all", "operation": "max", "fields": "(U)"}},
]


def probe_bundle(source: Path | None = None, *, end_time: float = 3.0) -> dict:
    if not math.isfinite(end_time) or end_time <= 0:
        raise ValueError("fixture end time must be finite and positive")
    b = bundle(1, source)
    if any(o.get("claim", "quantity") != "numerical_health" for o in b["contract"]["objectives"]):
        raise ValueError("fixture bundles must make numerical_health-only claims")
    b["diagnostics"]["quantities"] = [{**q, "settings": dict(q["settings"])} for q in QUANTITIES]
    b["diagnostics"].update({"target_time": end_time, "stationarity_window": None})
    b["files"]["system/controlDict"] = set_end_time(
        b["files"]["system/controlDict"], end_time, False,
    )
    b["budget"].update({"wall_seconds": min(b["budget"].get("wall_seconds", 900), 900),
                        "max_end_time": end_time})
    return b


def generate(out: Path | None = None, *, source: Path | None = None,
             work_root: Path | None = None, end_time: float = 3.0,
             runs_root: Path | None = None) -> dict:
    # Explicit temporary paths remain usable for synthetic plumbing tests. The
    # supported CLI validates every destination before entering this function.
    output = out.expanduser().resolve() if out is not None else None
    if output is not None and (output.exists() or output.is_symlink()):
        raise FileExistsError("Fixture output already exists; choose a fresh export directory")
    b = probe_bundle(source, end_time=end_time)
    work = work_directory("fixtures", work_root)
    with run_store(runs_root if runs_root is not None else work / "runs"):
        prepared = runner.prepare(b)
        run_id = prepared["run_id"]
        summary = runner.execute(run_id)
        verified = runner.verify(run_id)
        path = runner.run_dir(run_id)
    case = path / "output" / "case"
    logs = sorted(case.glob("log.foamRun*"))
    if (not verified["ok"] or summary["not_passing"] or not logs
            or not (case / "postProcessing").is_dir()):
        raise RuntimeError(
            f"Fixture health/output checks failed; native receipts retained at {path}",
        )
    output = output if output is not None else work / "export"
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(case / "postProcessing", output / "postProcessing")
    with logs[-1].open("rb") as source_log, (output / "log.foamRun").open("xb") as target_log:
        shutil.copyfileobj(source_log, target_log)
    receipt = {"fixture_only": True, "physical_validation": False, "finalized": False,
               "run_id": run_id, "work": str(work), "output": str(output),
               "health_verdict": summary["verdict"], "integrity": verified,
               "resource_limits": summary["runtime"].get("resource_limits")}
    with (output / "fixture.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, indent=1) + "\n")
    return receipt


def main(out: Path | None = None, *, source: Path | None = None,
         work_root: Path | None = None, end_time: float = 3.0,
         runs_root: Path | None = None) -> int:
    receipt = generate(out, source=source, work_root=work_root, end_time=end_time,
                       runs_root=runs_root)
    print(json.dumps(receipt, indent=1))
    return 0


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument("--out", type=Path, required=True, help="New results-contained export directory")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--end-time", type=float, default=3.0)
    args = parser.parse_args(argv)
    try:
        paths = ResultPaths(args.project_root, args.results_dir)
        output = paths.output(args.out)
        parent = paths.output(args.work_root or "analysis/fixtures", new=False)
        if parent == output or parent.is_relative_to(output):
            raise ValueError("Fixture exports must not contain their native work directory")
        source = paths.input(args.bundle)
        runs = paths.run_root()
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    return main(output, source=source, work_root=parent, end_time=args.end_time, runs_root=runs)


if __name__ == "__main__":
    sys.exit(cli())
