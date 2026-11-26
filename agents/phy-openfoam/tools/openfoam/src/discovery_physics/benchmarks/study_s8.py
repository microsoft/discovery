"""S8 done properly: a three-grid refinement study judged by the GCI, not a single-run claim.

The paper's S8 asked whether the Mach-3 forward-step result depends on the mesh. A single run
cannot answer that (the contract lint now refuses such a claim). This study freezes three grids
(refinement ratio 2) and a GCI criterion before any solve, then drives each member with the same
deterministic fixed rule as the campaign.

    python -m discovery_physics.benchmarks.study_s8 --out <dir>
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..openfoam import runner, study
from ..service import _drive
from .cases import forward_step_bundle
from .output_paths import ResultPaths, add_arguments

GRIDS = {"coarse": (120, 40), "medium": (240, 80), "fine": (480, 160)}


def spec(tut: dict, max_gci_pct: float = 5.0) -> dict:
    members = []
    for name, (nx, ny) in GRIDS.items():
        b = forward_step_bundle(tut, mach=3.0, nx=nx, ny=ny, name=f"S8_{name}")
        b["budget"]["wall_seconds"] = 14400
        members.append({"name": name, "bundle": b, "h": 3.0 / nx, "parameters": {"nx": nx}})
    return {
        "id": "S8_refinement", "title": "Mach-3 forward step: grid convergence of the compression ratios",
        "requested_prompt": "Does the Mach-3 forward-step compression result depend on the mesh?",
        "kind": "refinement", "members": members,
        "criteria": [
            {"id": "all_grids_healthy", "kind": "all_accept",
             "rationale": "Every grid must pass its own frozen health contract before grids are compared."},
            {"id": "gci_p_ratio", "kind": "gci", "metric": "compression.p_ratio", "max_gci_pct": max_gci_pct,
             "rationale": "Fine-grid discretization uncertainty (Celik GCI, Fs=1.25) of the pressure ratio "
                          f"within {max_gci_pct} %."},
            {"id": "gci_T_ratio", "kind": "gci", "metric": "compression.T_ratio", "max_gci_pct": max_gci_pct,
             "rationale": "Same bound for the temperature ratio."},
        ],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    add_arguments(ap)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--parallel", type=int, default=2)
    a = ap.parse_args(argv)
    if a.parallel < 1:
        ap.error("--parallel must be positive")
    try:
        paths = ResultPaths(a.project_root, a.results_dir)
        output = paths.output(a.out)
        paths.run_root()
        output = paths.directory(output)
    except (OSError, ValueError, RuntimeError) as exc:
        ap.error(str(exc))
    with paths.native_store():
        s = spec(runner.tutorial("shockFluid/forwardStep")["files"])
        prep = study.prepare(s)
        print(json.dumps(prep, indent=1), flush=True)
        bundles = {m["name"]: m["bundle"] for m in s["members"]}

        def drive(name):
            t0 = time.time()
            final, trail, leaf = _drive(prep["members"][name], bundles[name])
            print(f"{time.strftime('%H:%M:%S')} {name} {final['final_verdict']} "
                  f"{[t['action'] for t in trail]} {time.time() - t0:.0f}s", flush=True)
            return name, final

        # Fine grid first so the longest solve overlaps the others.
        with ThreadPoolExecutor(max_workers=a.parallel) as pool:
            list(pool.map(drive, ["fine", "medium", "coarse"]))
        res = study.assess(prep["study_id"])
        paths.write_text(output / "S8_study.json", json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": res["verdict"], "criteria": [(c["id"], c["state"]) for c in res["criteria"]]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
