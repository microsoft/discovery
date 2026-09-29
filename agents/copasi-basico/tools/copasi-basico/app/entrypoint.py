#!/usr/bin/env python3
"""Entrypoint for the COPASI (basico) Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "copasi-basico"


def action_run_timecourse(input_dir, output_dir, params):
    io_utils.log_step("run_timecourse", "COPASI (basico)")
    import os
    import basico
    files = io_utils.list_input_files(input_dir, ["*.xml", "*.sbml", "*.cps"])
    if not files:
        io_utils.log_error("no model files found")
        return False
    duration = float(params.get("duration", 100))
    rows = []
    for f in files:
        if f.endswith(".cps"):
            basico.load_model(f)
        else:
            basico.load_model(f)
        tc = basico.run_time_course(duration=duration)
        rows.append({"file": os.path.basename(f), "columns": list(tc.columns),
                     "n_steps": int(len(tc))})
    io_utils.write_json(output_dir, "timecourse.json", rows)
    io_utils.write_final_results(output_dir, {"models": len(rows)}, ["timecourse.json"])
    return True


ACTIONS = {
    "run_timecourse": action_run_timecourse,
}


def main():
    parser = argparse.ArgumentParser(description="COPASI (basico) tool")
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
