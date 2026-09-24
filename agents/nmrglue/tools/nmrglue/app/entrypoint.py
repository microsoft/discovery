#!/usr/bin/env python3
"""Entrypoint for the nmrglue Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "nmrglue"


def action_process_nmr(input_dir, output_dir, params):
    io_utils.log_step("process_nmr", "nmrglue")
    import os
    import numpy as np
    import nmrglue as ng
    files = io_utils.list_input_files(input_dir, ["*.ft", "*.ft2", "*.fid", "*.dat"])
    rows = []
    if files:
        for f in files:
            try:
                dic, data = ng.pipe.read(f)
                rows.append({"file": os.path.basename(f), "shape": list(np.asarray(data).shape),
                             "max_intensity": float(np.max(np.abs(data)))})
            except Exception as e:
                rows.append({"file": os.path.basename(f), "error": str(e)})
    else:
        try:
            dic, data = ng.bruker.read(input_dir)
            rows.append({"dir": os.path.basename(input_dir.rstrip("/")),
                         "shape": list(np.asarray(data).shape)})
        except Exception as e:
            io_utils.log_error(f"no readable NMR data: {e}")
            return False
    io_utils.write_json(output_dir, "nmr_summary.json", rows)
    io_utils.write_final_results(output_dir, {"datasets": len(rows)}, ["nmr_summary.json"])
    return True


ACTIONS = {
    "process_nmr": action_process_nmr,
}


def main():
    parser = argparse.ArgumentParser(description="nmrglue tool")
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
