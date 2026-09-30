#!/usr/bin/env python3
"""Entrypoint for the DFTB+ Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "dftbplus"


def action_run_dftb(input_dir, output_dir, params):
    io_utils.log_step("run_dftb", "DFTB+")
    import os, subprocess, shutil, glob
    hsd = glob.glob(os.path.join(input_dir, "dftb_in.hsd"))
    if not hsd:
        io_utils.log_error("dftb_in.hsd not found in input directory")
        return False
    os.makedirs(output_dir, exist_ok=True)
    for f in glob.glob(os.path.join(input_dir, "*")):
        if os.path.isfile(f):
            shutil.copy(f, output_dir)
    r = subprocess.run(["dftb+"], cwd=output_dir, capture_output=True, text=True)
    io_utils.write_final_results(output_dir, {"returncode": r.returncode,
                                              "stdout_tail": r.stdout[-2000:]}, ["detailed.out"])
    return r.returncode == 0


ACTIONS = {
    "run_dftb": action_run_dftb,
}


def main():
    parser = argparse.ArgumentParser(description="DFTB+ tool")
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
