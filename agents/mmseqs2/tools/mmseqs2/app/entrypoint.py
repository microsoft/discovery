#!/usr/bin/env python3
"""Entrypoint for the MMseqs2 Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "mmseqs2"


def action_search(input_dir, output_dir, params):
    io_utils.log_step("search", "MMseqs2")
    import os, subprocess, tempfile
    queries = io_utils.list_input_files(input_dir, ["*query*", "*.fasta", "*.fa"])
    target = params.get("target")
    if not queries:
        io_utils.log_error("no query fasta found")
        return False
    q = queries[0]
    t = (target if os.path.isabs(target) else os.path.join(input_dir, os.path.basename(target))) if target else queries[-1]
    os.makedirs(output_dir, exist_ok=True)
    out = os.path.join(output_dir, "search.m8")
    tmp = tempfile.mkdtemp()
    r = subprocess.run(["mmseqs", "easy-search", q, t, out, tmp], capture_output=True, text=True)
    io_utils.write_final_results(output_dir, {"returncode": r.returncode}, ["search.m8"])
    return r.returncode == 0


def action_cluster(input_dir, output_dir, params):
    io_utils.log_step("cluster", "MMseqs2")
    import os, subprocess, tempfile
    files = io_utils.list_input_files(input_dir, ["*.fasta", "*.fa"])
    if not files:
        io_utils.log_error("no fasta files found")
        return False
    os.makedirs(output_dir, exist_ok=True)
    prefix = os.path.join(output_dir, "clusters")
    tmp = tempfile.mkdtemp()
    mid = str(params.get("min_seq_id", 0.5))
    r = subprocess.run(["mmseqs", "easy-cluster", files[0], prefix, tmp, "--min-seq-id", mid],
                       capture_output=True, text=True)
    io_utils.write_final_results(output_dir, {"returncode": r.returncode}, ["clusters_cluster.tsv"])
    return r.returncode == 0


ACTIONS = {
    "search": action_search,
    "cluster": action_cluster,
}


def main():
    parser = argparse.ArgumentParser(description="MMseqs2 tool")
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
