#!/usr/bin/env python3
"""Entrypoint for the MDAnalysis Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "mdanalysis"


def action_analyze_trajectory(input_dir, output_dir, params):
    io_utils.log_step("analyze_trajectory", "MDAnalysis")
    import os
    import numpy as np
    import MDAnalysis as mda
    from MDAnalysis.analysis import rms
    top = params.get("topology")
    traj = params.get("trajectory")
    sel = params.get("selection", "protein and name CA")
    if not top:
        cands = io_utils.list_input_files(input_dir, ["*.pdb", "*.gro", "*.psf", "*.tpr"])
        top = cands[0] if cands else None
    if not top:
        io_utils.log_error("no topology found")
        return False
    top = top if os.path.isabs(top) else os.path.join(input_dir, os.path.basename(top))
    if traj:
        traj = traj if os.path.isabs(traj) else os.path.join(input_dir, os.path.basename(traj))
        u = mda.Universe(top, traj)
    else:
        u = mda.Universe(top)
    rg = [float(u.select_atoms(sel).radius_of_gyration()) for _ in u.trajectory]
    R = rms.RMSD(u, u, select=sel).run()
    summary = {"frames": len(u.trajectory), "selection": sel,
               "rmsd_final": float(R.results.rmsd[-1][2]) if len(R.results.rmsd) else None,
               "rgyr_mean": float(np.mean(rg)) if rg else None}
    io_utils.write_json(output_dir, "trajectory_metrics.json", {"rgyr": rg, "rmsd": R.results.rmsd.tolist()})
    io_utils.write_final_results(output_dir, summary, ["trajectory_metrics.json"])
    return True


ACTIONS = {
    "analyze_trajectory": action_analyze_trajectory,
}


def main():
    parser = argparse.ArgumentParser(description="MDAnalysis tool")
    parser.add_argument("--action", required=True, choices=list(ACTIONS.keys()))
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--params", default="",
                        help="Optional JSON string of extra parameters")
    args, extra = parser.parse_known_args()

    params = {}
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError:
            params = {}

    # Collect any additional --key value pairs into params (Discovery passes
    # each declared action parameter as its own CLI flag).
    i = 0
    while i < len(extra):
        tok = extra[i]
        if tok.startswith("--"):
            key = tok[2:]
            if i + 1 < len(extra) and not extra[i + 1].startswith("--"):
                params[key] = extra[i + 1]
                i += 2
            else:
                params[key] = True
                i += 1
        else:
            i += 1

    io_utils.setup_session_logger(args.action, args.output)
    fn = ACTIONS[args.action]
    ok = fn(args.input, args.output, params)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
