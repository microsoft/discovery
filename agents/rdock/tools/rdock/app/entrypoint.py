#!/usr/bin/env python3
"""Entrypoint for the rDock Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "rdock"


def action_dock_ligands(input_dir, output_dir, params):
    io_utils.log_step("dock_ligands", "rDock")
    import os, subprocess
    ligs = io_utils.list_input_files(input_dir, ["*.sd", "*.sdf"])
    prm = params.get("receptor_prm")
    if not ligs or not prm:
        io_utils.log_error("need ligand SD file and receptor_prm")
        return False
    prm = prm if os.path.isabs(prm) else os.path.join(input_dir, os.path.basename(prm))
    os.makedirs(output_dir, exist_ok=True)
    out = os.path.join(output_dir, "docked")
    n = str(params.get("n_runs", 10))
    r = subprocess.run(["rbdock", "-i", ligs[0], "-o", out, "-r", prm,
                        "-p", "dock.prm", "-n", n], capture_output=True, text=True)
    io_utils.write_final_results(output_dir, {"returncode": r.returncode}, ["docked.sd"])
    return r.returncode == 0


ACTIONS = {
    "dock_ligands": action_dock_ligands,
}


def main():
    parser = argparse.ArgumentParser(description="rDock tool")
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
