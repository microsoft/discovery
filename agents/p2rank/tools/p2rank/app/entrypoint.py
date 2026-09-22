#!/usr/bin/env python3
"""Entrypoint for the P2Rank Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "p2rank"


def action_predict_sites(input_dir, output_dir, params):
    io_utils.log_step("predict_sites", "P2Rank")
    import os, subprocess
    files = io_utils.list_input_files(input_dir, ["*.pdb"])
    if not files:
        io_utils.log_error("no pdb files found")
        return False
    os.makedirs(output_dir, exist_ok=True)
    results = []
    for f in files:
        r = subprocess.run(["prank", "predict", "-f", f, "-o", output_dir],
                           capture_output=True, text=True)
        results.append({"file": os.path.basename(f), "returncode": r.returncode, "stdout": r.stdout[-2000:]})
    io_utils.write_json(output_dir, "p2rank.json", results)
    io_utils.write_final_results(output_dir, {"structures": len(results)}, ["p2rank.json"])
    return all(x["returncode"] == 0 for x in results)


ACTIONS = {
    "predict_sites": action_predict_sites,
}


def main():
    parser = argparse.ArgumentParser(description="P2Rank tool")
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
