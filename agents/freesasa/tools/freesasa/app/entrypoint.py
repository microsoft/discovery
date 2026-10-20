#!/usr/bin/env python3
"""Entrypoint for the FreeSASA Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "freesasa"


def action_compute_sasa(input_dir, output_dir, params):
    io_utils.log_step("compute_sasa", "FreeSASA")
    import os, freesasa
    files = io_utils.list_input_files(input_dir, ["*.pdb"])
    if not files:
        io_utils.log_error("no pdb files found")
        return False
    rows = []
    for f in files:
        structure = freesasa.Structure(f)
        result = freesasa.calc(structure)
        classes = freesasa.classifyResults(result, structure)
        rows.append({"file": os.path.basename(f), "total_sasa_A2": round(result.totalArea(), 2),
                     "classes": {k: round(v, 2) for k, v in classes.items()}})
    io_utils.write_json(output_dir, "sasa.json", rows)
    io_utils.write_final_results(output_dir, {"structures": len(rows)}, ["sasa.json"])
    return True


ACTIONS = {
    "compute_sasa": action_compute_sasa,
}


def main():
    parser = argparse.ArgumentParser(description="FreeSASA tool")
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
