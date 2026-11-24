"""Render explicit campaign inputs to a new, project-owned Markdown report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..openfoam import runner
from .output_paths import ResultPaths, add_arguments

PAPER_DECISION = {
    "N1": "ACCEPT", "N2": "ACCEPT", "N3": "ACCEPT", "N6": "ACCEPT (after CONTINUE_RUN)",
    "S1": "ACCEPT (corrected reanalysis)", "S2": "ACCEPT", "S3": "ACCEPT", "S4": "ACCEPT",
    "S5": "REJECT", "S6": "ACCEPT", "S7": "ACCEPT (supervised)", "S8": "INCONCLUSIVE",
}
REQUEST = {
    "N1": "nozzle reference, p0 200 kPa", "N2": "nozzle r_e 37 mm", "N3": "nozzle p0 220 kPa",
    "N6": "nozzle from 1 ms, continuation", "S1": "step M2.5 h0.15", "S2": "step M2 h0.2 (canonical)",
    "S3": "step M3.5 h0.2", "S4": "step M3 h0.1", "S5": "step M3 h0.3 x0.6", "S6": "step M3 h0.3 x1.0",
    "S7": "step M3 staged 0.5->4", "S8": "step M3 sensitivity (refine)",
}
PAPER_NUM = {
    "N1": {"nozzle.exit_mach": 1.5133, "nozzle.exit_p": 53140, "nozzle.mass_flow": 1.541, "nozzle.throat_mach": 1.029,
           "solver.steps": 30471},
    "N2": {"nozzle.exit_mach": 1.652, "nozzle.exit_p": 43290, "nozzle.mass_flow": 1.541},
    "N3": {"nozzle.exit_mach": 1.513, "nozzle.mass_flow": 1.6951},
    "S2": {"compression.front_x": 0.113, "compression.p_ratio": 5.18, "compression.rho_ratio": 2.87,
           "compression.T_ratio": 1.81, "solver.steps": 5428, "conservation.mass_closure_max_rel": 5.7e-11,
           "flow.inlet_mach_min": 2.000006},
}


def _f(v):
    return f"{v:.4g}" if isinstance(v, float) else str(v)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument("--results", type=Path, required=True, help="Existing campaign JSON directory")
    parser.add_argument("--comparison", type=Path, help="Optional existing comparison summary JSON")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        paths = ResultPaths(args.project_root, args.results_dir)
        output = paths.output(args.out)
        root = paths.input(args.results)
        comp = paths.input(args.comparison) if args.comparison is not None else None
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    lines = ["# Benchmark results: CFD Forge campaign recreated on Discovery", "",
             "Read-only rendering of the explicitly selected campaign receipts. Missing cases "
             "are marked not run; generating this report performs no new solves and does not "
             "independently validate a recorded scientific decision. The campaign controller "
             "is the fixed-rule arm A through the native prepare/execute/propose/finalize gates.", "",
             "| Case | Request | Paper decision | Our final verdict | Trail (verdict -> action, ruling) |",
             "|---|---|---|---|---|"]
    numbers = []
    for cid in PAPER_DECISION:
        f = root / f"{cid}.json"
        if not f.exists():
            lines.append(f"| {cid} | {REQUEST[cid]} | {PAPER_DECISION[cid]} | not run | |")
            continue
        r = json.loads(f.read_text(encoding="utf-8"))
        if "error" in r:
            lines.append(f"| {cid} | {REQUEST[cid]} | {PAPER_DECISION[cid]} | ERROR | {r['error'][:80]} |")
            continue
        trail = "; ".join(f"{t['verdict']}->{t['action']} ({'A' if t['approved'] else 'R'})" for t in r["trail"])
        lines.append(f"| {cid} | {REQUEST[cid]} | {PAPER_DECISION[cid]} | **{r['final']['final_verdict']}** | {trail} |")
        last = r["trail"][-1]["run_id"]
        ev = json.loads((runner.run_dir(last) / "evidence.json").read_text(encoding="utf-8"))["metrics"]
        for k, pv in PAPER_NUM.get(cid, {}).items():
            ov = ev.get(k, {}).get("value")
            diff = f"{100 * (ov / pv - 1):+.2f}%" if isinstance(ov, (int, float)) and pv else ""
            numbers.append(f"| {cid} | `{k}` | {_f(pv)} | {_f(ov)} | {diff} |")
    lines += ["", "## Quantitative comparison", "", "| Case | Metric | Paper | Ours | Diff |", "|---|---|---|---|---|",
              *numbers]
    if comp is not None:
        s = json.loads(comp.read_text(encoding="utf-8"))
        lines += ["", "## Controller comparison (deterministic arms)", "",
                  "| Group / arm | Points | Correct | False accepts |", "|---|---|---|---|"]
        lines += [f"| {k} | {v['points']} | {v['correct']} | {v['false_accept']} |" for k, v in s.items()]
    paths.write_text(output, "\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
