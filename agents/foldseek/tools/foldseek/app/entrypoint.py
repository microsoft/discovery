#!/usr/bin/env python3
"""Entrypoint for the Foldseek Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "foldseek"


def action_structure_search(input_dir, output_dir, params):
    io_utils.log_step("structure_search", "Foldseek")
    import os, subprocess, tempfile
    queries = io_utils.list_input_files(input_dir, ["*.pdb", "*.cif"])
    target = params.get("target_dir", input_dir)
    if not queries:
        io_utils.log_error("no query structures found")
        return False
    os.makedirs(output_dir, exist_ok=True)
    out = os.path.join(output_dir, "aln.m8")
    tmp = tempfile.mkdtemp()
    r = subprocess.run(["foldseek", "easy-search", input_dir, target, out, tmp,
                        "--format-mode", "0"], capture_output=True, text=True)
    io_utils.write_final_results(output_dir, {"returncode": r.returncode, "queries": len(queries)}, ["aln.m8"])
    return r.returncode == 0


ACTIONS = {
    "structure_search": action_structure_search,
}


def main():
    parser = argparse.ArgumentParser(description="Foldseek tool")
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
