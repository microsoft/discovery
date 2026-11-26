"""Recreate the CFD Forge benchmark campaign with new Foundation 14 solves.

The proposer here is the paper's *fixed-rule* controller (arm A): it maps the
deterministic verdict to an action with no model call. It drives exactly the
same prepare/execute/propose/finalize gates that CLIO uses, so this campaign
validates the tools end to end; it does not measure model behaviour.

Requires an explicit project, marked results container and new --out directory.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..openfoam import runner
from .cases import forward_step_bundle, nozzle_bundle
from .output_paths import ResultPaths, add_arguments

# Published outcomes (paper Table 12 / README results; archived family status → decision).
PAPER = {
    "N1": {"decision": "ACCEPT", "exit_mach": 1.5133, "exit_p_kPa": 53.14, "mass_flow": 1.541,
           "throat_mach": 1.029, "steps": 30471},
    "N2": {"decision": "ACCEPT", "exit_mach": 1.652, "exit_p_kPa": 43.29, "mass_flow": 1.541},
    "N3": {"decision": "ACCEPT", "exit_mach": 1.513, "mass_flow": 1.541 * 1.1},
    "N6": {"decision": "ACCEPT", "sequence": "CONTINUE_RUN -> ACCEPT", "first": "CORRECT_AND_RERUN"},
    "S1": {"decision": "ACCEPT (after corrected reanalysis; archived REJECT from false fatal check)"},
    "S2": {"decision": "ACCEPT", "front_x": 0.113, "p_ratio": 5.18, "rho_ratio": 2.87, "T_ratio": 1.81,
           "steps": 5428, "courant_max": 0.202, "mass_closure": 5.7e-11, "inlet_mach": 2.000006},
    "S3": {"decision": "ACCEPT"},
    "S4": {"decision": "ACCEPT"},
    "S5": {"decision": "REJECT (no measurable compression front)"},
    "S6": {"decision": "ACCEPT"},
    "S7": {"decision": "ACCEPT (after supervised resumption + validator fix)"},
    "S8": {"decision": "INCONCLUSIVE (REFINE_MESH approved; ACCEPT refused)"},
}


def _step(tut, **kw):
    return lambda: forward_step_bundle(tut, **kw)


def cases(tut: dict) -> dict[str, dict]:
    return {
        "N1": {"bundle": lambda: nozzle_bundle(name="N1_reference")},
        "N2": {"bundle": lambda: nozzle_bundle(exit_radius=0.037, name="N2_exit37")},
        "N3": {"bundle": lambda: nozzle_bundle(total_pressure=220000.0, name="N3_p0_220")},
        "N6": {"bundle": lambda: nozzle_bundle(end_time=0.001, name="N6_continuation")},
        "S1": {"bundle": _step(tut, mach=2.5, step_height=0.15, name="S1_M2p5_h0p15")},
        "S2": {"bundle": _step(tut, mach=2.0, name="S2_M2_canonical")},
        "S3": {"bundle": _step(tut, mach=3.5, name="S3_M3p5")},
        "S4": {"bundle": _step(tut, mach=3.0, step_height=0.1, name="S4_M3_h0p1")},
        "S5": {"bundle": _step(tut, mach=3.0, step_height=0.3, name="S5_M3_h0p3_x0p6")},
        "S6": {"bundle": _step(tut, mach=3.0, step_height=0.3, step_x=1.0, name="S6_M3_h0p3_x1")},
        "S7": {"bundle": _step(tut, mach=3.0, end_time=0.5, name="S7_staged"), "stages": [1.0, 2.0, 4.0]},
        "S8": {"bundle": _step(tut, mach=3.0, nx=120, ny=40, sensitivity_request=True, name="S8_sensitivity"),
               "refine": True},
    }


def fixed_rule(summary: dict, case: dict, stage: int) -> dict:
    v = summary["verdict"]
    if v == "ACCEPT":
        return {"action": "ACCEPT", "rationale": "All registered checks pass (fixed rule)."}
    if v == "CORRECT_AND_RERUN":
        stages = case.get("stages")
        end = stages[stage] if stages and stage < len(stages) else None
        if end is None:
            final = summary["metrics"].get("solver.final_time", [0.0])[0]
            target = case["target"]
            # Reach the registered horizon first; once there, continue by one third of it
            # (bounded by the frozen max_end_time in the bundle budget).
            end = target if final < target * (1 - 1e-9) else final + target / 3
        return {"action": "CONTINUE_RUN", "end_time": end,
                "rationale": "Healthy but incomplete: development/horizon checks fail (fixed rule)."}
    if v == "INCONCLUSIVE" and case.get("refine") and stage == 0:
        return {"action": "REFINE_MESH", "refinement_factor": 2.0,
                "rationale": "Sensitivity requested; refine once under the bounded policy (fixed rule)."}
    if v == "INCONCLUSIVE":
        return {"action": "ACCEPT", "rationale": "Both grids healthy; propose acceptance (paper S8 replay)."}
    return {"action": "FAIL_SAFELY", "rationale": "Hard failure; stop and preserve evidence (fixed rule)."}


def run_case(cid: str, case: dict, log) -> dict:
    t0 = time.time()
    bundle = case["bundle"]()
    case["target"] = bundle["diagnostics"]["target_time"]
    trail = []
    prep = runner.prepare(bundle)
    run_id = prep["run_id"]
    stage = 0
    while True:
        s = runner.execute(run_id)
        log(f"{cid} {run_id} verdict={s['verdict']} failing={[c['id'] for c in s['not_passing']]}")
        proposal = fixed_rule(s, case, stage)
        ruling = runner.propose(run_id, proposal)
        trail.append({"run_id": run_id, "verdict": s["verdict"], "action": proposal["action"],
                      "approved": ruling["approved"], "reasons": ruling["reasons"]})
        stage += 1
        if ruling.get("child_run_id"):
            run_id = ruling["child_run_id"]
            continue
        if ruling["approved"] and proposal["action"] == "REFINE_MESH":
            refined = forward_step_bundle(TUT, mach=3.0, nx=240, ny=80, sensitivity_request=True,
                                          name="S8_sensitivity")
            run_id = runner.prepare(refined, parent_run_id=run_id)["run_id"]
            continue
        break
    final = runner.finalize(run_id)
    return {"case": cid, "trail": trail, "final": final, "summary": runner.summary(run_id),
            "wall_s": round(time.time() - t0, 1), "paper": PAPER.get(cid)}


TUT: dict = {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    add_arguments(ap)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--parallel", type=int, default=4)
    a = ap.parse_args(argv)
    if a.parallel < 1:
        ap.error("--parallel must be positive")
    try:
        paths = ResultPaths(a.project_root, a.results_dir)
        output = paths.output(a.out)  # Refuse bad output before tutorial discovery or a solve.
        paths.run_root()
        output = paths.directory(output)
    except (OSError, ValueError, RuntimeError) as exc:
        ap.error(str(exc))
    with paths.native_store():
        TUT.clear()
        TUT.update(runner.tutorial("shockFluid/forwardStep")["files"])
        all_cases = cases(TUT)
        chosen = [c for c in all_cases if not a.only or c in a.only.split(",")]
        with paths.output(output / "campaign.log").open("x", encoding="utf-8") as logf:
            def log(msg: str) -> None:
                line = time.strftime("%H:%M:%S ") + msg
                print(line, flush=True)
                logf.write(line + "\n")
                logf.flush()

            def safe(cid):
                try:
                    return run_case(cid, all_cases[cid], log)
                except Exception as exc:  # record, do not hide
                    log(f"{cid} ERROR {type(exc).__name__}: {exc}")
                    return {"case": cid, "error": f"{type(exc).__name__}: {exc}"}

            with ThreadPoolExecutor(max_workers=a.parallel) as pool:
                results = list(pool.map(safe, chosen))
            for result in results:
                paths.write_text(output / f"{result['case']}.json",
                                 json.dumps(result, indent=1, default=str) + "\n")
            log("done: " + ", ".join(
                f"{r['case']}={r.get('final', {}).get('final_verdict', 'ERROR')}" for r in results
            ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
