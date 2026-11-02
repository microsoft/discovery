#!/usr/bin/env python3
"""Entrypoint for the Tellurium Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "tellurium"


def action_simulate_model(input_dir, output_dir, params):
    io_utils.log_step("simulate_model", "Tellurium")
    import os
    import tellurium as te
    files = io_utils.list_input_files(input_dir, ["*.xml", "*.sbml", "*.ant"])
    if not files:
        io_utils.log_error("no model files found")
        return False
    start = float(params.get("start", 0)); end = float(params.get("end", 100))
    points = int(params.get("points", 200))
    rows = []
    for f in files:
        with open(f) as fh:
            content = fh.read()
        r = te.loada(content) if f.endswith(".ant") else te.loadSBMLModel(content)
        result = r.simulate(start, end, points)
        cols = list(result.colnames)
        rows.append({"file": os.path.basename(f), "columns": cols, "final_row": result[-1].tolist()})
    io_utils.write_json(output_dir, "simulation.json", rows)
    io_utils.write_final_results(output_dir, {"models": len(rows)}, ["simulation.json"])
    return True


ACTIONS = {
    "simulate_model": action_simulate_model,
}


def main():
    parser = argparse.ArgumentParser(description="Tellurium tool")
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
