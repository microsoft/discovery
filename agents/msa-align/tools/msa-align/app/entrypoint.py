#!/usr/bin/env python3
"""Entrypoint for the Multiple Sequence Alignment (MAFFT/MUSCLE/Clustal Omega) Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "msa-align"


def action_align(input_dir, output_dir, params):
    io_utils.log_step("align", "Multiple Sequence Alignment (MAFFT/MUSCLE/Clustal Omega)")
    import os, subprocess
    files = io_utils.list_input_files(input_dir, ["*.fasta", "*.fa"])
    if not files:
        io_utils.log_error("no fasta files found")
        return False
    os.makedirs(output_dir, exist_ok=True)
    method = params.get("method", "mafft")
    f = files[0]
    out = os.path.join(output_dir, "alignment.fasta")
    if method == "mafft":
        r = subprocess.run(["mafft", "--auto", f], capture_output=True, text=True)
        if r.returncode == 0:
            with open(out, "w") as fh:
                fh.write(r.stdout)
    elif method == "muscle":
        r = subprocess.run(["muscle", "-align", f, "-output", out], capture_output=True, text=True)
    else:
        r = subprocess.run(["clustalo", "-i", f, "-o", out, "--force"], capture_output=True, text=True)
    io_utils.write_final_results(output_dir, {"method": method, "returncode": r.returncode}, ["alignment.fasta"])
    return r.returncode == 0


ACTIONS = {
    "align": action_align,
}


def main():
    parser = argparse.ArgumentParser(description="Multiple Sequence Alignment (MAFFT/MUSCLE/Clustal Omega) tool")
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
