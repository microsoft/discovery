#!/usr/bin/env python3
"""Entrypoint for the OPSIN Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "opsin"


def action_name_to_structure(input_dir, output_dir, params):
    io_utils.log_step("name_to_structure", "OPSIN")
    import os
    from py2opsin import py2opsin
    files = io_utils.list_input_files(input_dir, ["*.txt", "*.names", "*.csv"])
    if not files:
        io_utils.log_error("no name files found")
        return False
    fmt = params.get("output_format", "SMILES")
    rows = []
    for f in files:
        with open(f) as fh:
            for line in fh:
                name = line.strip()
                if not name:
                    continue
                result = py2opsin(name, output_format=fmt)
                rows.append({"name": name, fmt.lower(): result})
    io_utils.write_json(output_dir, "structures.json", rows)
    io_utils.write_final_results(output_dir, {"names": len(rows)}, ["structures.json"])
    return True


ACTIONS = {
    "name_to_structure": action_name_to_structure,
}


def main():
    parser = argparse.ArgumentParser(description="OPSIN tool")
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
