"""Optional execution-path checks, not physical validation or Azure dispatch evidence.

The default is the self-contained health-only channel example. MPI uses the normal
guarded runner. The local service check requires container CPU/memory/PID limits;
it never silently retries without them. The CLI requires explicit marked project
results and a new --out receipt; optional work roots must be inside those results.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from discovery_physics.openfoam import runner

if __package__:
    from .result_paths import ResultPaths, add_arguments
else:
    from result_paths import ResultPaths, add_arguments

DEFAULT_BUNDLE = Path(__file__).resolve().parents[1] / "examples" / "channel-path-check.json"


def bundle(ranks: int, source: Path | None = None) -> dict:
    """Load public input, retaining its checks and assumptions rather than weakening them."""
    if not 1 <= ranks <= 64:
        raise ValueError("MPI ranks must be between 1 and 64")
    path = source if source is not None else DEFAULT_BUNDLE
    b = json.loads(path.expanduser().read_text(encoding="utf-8"))
    budget = b.setdefault("budget", {})
    budget.update({"cpus": max(budget.get("cpus", 2), ranks), "mpi_ranks": ranks})
    return b


def work_directory(kind: str, root: Path | None = None) -> Path:
    if root is None:
        raise ValueError("An explicit work root is required; no CWD or AppData output fallback")
    parent = root.expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{kind}-", dir=parent)).resolve()


@contextmanager
def run_store(path: Path):
    previous = os.environ.get("DISCOVERY_PHYSICS_RUNS")
    os.environ["DISCOVERY_PHYSICS_RUNS"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DISCOVERY_PHYSICS_RUNS", None)
        else:
            os.environ["DISCOVERY_PHYSICS_RUNS"] = previous


def run(b: dict) -> dict:
    p = runner.prepare(b)
    s = runner.execute(p["run_id"])
    return {
        "run_id": p["run_id"], "verdict": s["verdict"],
        "not_passing": [c["id"] for c in s["not_passing"]],
        "flux_out": s["metrics"].get("conservation.final_outlet_flux"),
        "p_max": s["metrics"].get("fields.p.final_max"),
        "steps": s["metrics"].get("solver.steps"), "ranks": s["runtime"].get("mpi_ranks"),
        "timings": s["runtime"].get("timings_s"),
        "resource_limits": s["runtime"].get("resource_limits"),
        "verify": runner.verify(p["run_id"])["ok"],
    }


def cloud(b: dict, work: Path, *, runs: Path | None = None) -> dict:
    """Exercise the local service entry point with enforced limits and no shell."""
    if runner.in_container():
        raise RuntimeError("The bounded local service check must be launched from the host")
    frozen, _ = runner.freeze(b)
    budget = frozen.budget
    output = work / "output"
    output.mkdir()
    with (work / "bundle.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(b, indent=1) + "\n")
    encoded = base64.b64encode(gzip.compress(json.dumps(b).encode("utf-8"))).decode("ascii")
    command = [
        runner.container_runtime(), "run", "--rm", "--network", "none", "--read-only",
        "--tmpfs", "/tmp:rw,size=1g", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "4096", "--cpus", str(budget.cpus), "--memory", f"{budget.memory_mb}m",
        "-e", "HOME=/tmp", "-v", f"{output}:/output:rw",
    ]
    if runs is not None:
        runs.mkdir(parents=True, exist_ok=True)
        (output / "runs").mkdir()  # Nested bind mountpoint must exist on Windows hosts.
        command.extend(["-e", "DISCOVERY_PHYSICS_RUNS=/output/runs",
                        "-v", f"{runs}:/output/runs:rw"])
    command.extend([
        runner.image(),
        "python", "-m", "discovery_physics.service", "evaluate", "--bundle-b64gz", encoded,
        "--confirmations-b64", "W10=",
    ])
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          timeout=budget.wall_seconds * budget.max_attempts + 600, check=False)
    for name, text in (("stdout.log", proc.stdout), ("stderr.log", proc.stderr)):
        with (work / name).open("x", encoding="utf-8") as stream:
            stream.write(text)
    receipt = output / "result.json"
    res = json.loads(receipt.read_text(encoding="utf-8")) if receipt.is_file() else {}
    return {
        "rc": proc.returncode, "final": res.get("final"), "trail": res.get("trail"),
        "integrity": res.get("integrity"),
        "limits": (res.get("summary") or {}).get("runtime", {}).get("resource_limits"),
        "error": res.get("error"), "detail": res.get("detail"),
        "stdout_tail": proc.stdout[-300:], "stderr_tail": proc.stderr[-1000:],
    }


def main(argv: list[str] | str | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("mpi", "cloud"))
    add_arguments(parser)
    parser.add_argument("--out", type=Path, required=True, help="New JSON receipt inside results")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--work-root", type=Path, help="Results-contained parent for new work")
    args = parser.parse_args([argv] if isinstance(argv, str) else argv)
    try:
        paths = ResultPaths(args.project_root, args.results_dir)
        output = paths.output(args.out)
        parent = paths.output(args.work_root or "analysis/path-checks", new=False)
        if parent == output or parent.is_relative_to(output):
            raise ValueError("The JSON output cannot be the work directory or one of its parents")
        source = paths.input(args.bundle)
        runs = paths.run_root()
        work = work_directory("path-checks", parent)
        paths.output(work, new=False)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    if args.action == "mpi":
        with paths.native_store():
            out = {"serial": run(bundle(1, source)), "mpi2": run(bundle(2, source))}
        a = (out["serial"]["p_max"] or [None])[0]
        b = (out["mpi2"]["p_max"] or [None])[0]
        out["p_max_rel_diff"] = (
            abs(a - b) / abs(a) if a is not None and b is not None and a != 0
            else 0.0 if a == b == 0 else None
        )
        ok = all(out[key]["verify"] and not out[key]["not_passing"]
                 for key in ("serial", "mpi2"))
    else:
        with paths.native_store():
            out = cloud(bundle(1, source), work, runs=runs)
        ok = (out["rc"] == 0 and not out["error"]
              and (out["integrity"] or {}).get("ok") is True)
    out.update({"work": str(work),
                "scope": "Execution-path check only; not physical validation or Azure dispatch"})
    paths.write_text(output, json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
