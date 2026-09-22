#!/usr/bin/env python3
"""Entrypoint for the IQ-TREE Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "iqtree"


def action_build_tree(input_dir, output_dir, params):
    io_utils.log_step("build_tree", "IQ-TREE")
    import os, subprocess, shutil
    files = io_utils.list_input_files(input_dir, ["*.phy", "*.fasta", "*.fa", "*.nex", "*.aln"])
    if not files:
        io_utils.log_error("no alignment files found")
        return False
    os.makedirs(output_dir, exist_ok=True)
    aln = os.path.join(output_dir, os.path.basename(files[0]))
    shutil.copy(files[0], aln)
    bb = str(params.get("bootstrap", 1000))
    exe = shutil.which("iqtree2") or shutil.which("iqtree")
    if not exe:
        io_utils.log_error("iqtree/iqtree2 binary not found on PATH")
        return False
    if exe.endswith("iqtree2"):
        r = subprocess.run([exe, "-s", aln, "-B", bb, "-T", "AUTO", "--redo"],
                           capture_output=True, text=True)
    else:
        r = subprocess.run([exe, "-s", aln, "-bb", bb, "-nt", "AUTO", "-redo"],
                           capture_output=True, text=True)
    io_utils.write_final_results(output_dir, {"returncode": r.returncode}, [os.path.basename(aln) + ".treefile"])
    return r.returncode == 0


ACTIONS = {
    "build_tree": action_build_tree,
}


def main():
    parser = argparse.ArgumentParser(description="IQ-TREE tool")
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
