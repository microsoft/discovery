#!/usr/bin/env python3
"""Entrypoint for the TM-align / US-align Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "tmalign"


def action_align_structures(input_dir, output_dir, params):
    io_utils.log_step("align_structures", "TM-align / US-align")
    import os, subprocess, re
    files = io_utils.list_input_files(input_dir, ["*.pdb"])
    ref = params.get("reference")
    if not files or len(files) < 2 and not ref:
        io_utils.log_error("need at least two structures or a reference")
        return False
    ref_path = (ref if ref and os.path.isabs(ref) else os.path.join(input_dir, os.path.basename(ref))) if ref else files[0]
    rows = []
    for f in files:
        if f == ref_path:
            continue
        r = subprocess.run(["TMalign", f, ref_path], capture_output=True, text=True)
        scores = re.findall(r"TM-score=\s*([0-9.]+)", r.stdout)
        rmsd = re.findall(r"RMSD=\s*([0-9.]+)", r.stdout)
        rows.append({"query": os.path.basename(f), "reference": os.path.basename(ref_path),
                     "tm_scores": scores, "rmsd": rmsd[0] if rmsd else None})
    io_utils.write_json(output_dir, "tmalign.json", rows)
    io_utils.write_final_results(output_dir, {"alignments": len(rows)}, ["tmalign.json"])
    return True


ACTIONS = {
    "align_structures": action_align_structures,
}


def main():
    parser = argparse.ArgumentParser(description="TM-align / US-align tool")
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
