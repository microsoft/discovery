#!/usr/bin/env python3
"""Entrypoint for the NCBI BLAST+ Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "blast-plus"


def action_makeblastdb(input_dir, output_dir, params):
    io_utils.log_step("makeblastdb", "NCBI BLAST+")
    import os, subprocess
    files = io_utils.list_input_files(input_dir, ["*.fasta", "*.fa"])
    if not files:
        io_utils.log_error("no fasta files found")
        return False
    os.makedirs(output_dir, exist_ok=True)
    dbtype = params.get("dbtype", "nucl")
    results = []
    for f in files:
        db = os.path.join(output_dir, os.path.splitext(os.path.basename(f))[0])
        r = subprocess.run(["makeblastdb", "-in", f, "-dbtype", dbtype, "-out", db],
                           capture_output=True, text=True)
        results.append({"db": os.path.basename(db), "returncode": r.returncode, "stderr": r.stderr[-500:]})
    io_utils.write_json(output_dir, "makeblastdb.json", results)
    io_utils.write_final_results(output_dir, {"databases": len(results)}, ["makeblastdb.json"])
    return all(x["returncode"] == 0 for x in results)


def action_run_blast(input_dir, output_dir, params):
    io_utils.log_step("run_blast", "NCBI BLAST+")
    import os, subprocess
    program = params.get("program", "blastn")
    db = params.get("db", "")
    queries = io_utils.list_input_files(input_dir, ["*.fasta", "*.fa", "*query*"])
    if not queries or not db:
        io_utils.log_error("need query fasta files and a db parameter")
        return False
    os.makedirs(output_dir, exist_ok=True)
    out = os.path.join(output_dir, "blast_results.tsv")
    r = subprocess.run([program, "-query", queries[0], "-db", db, "-out", out, "-outfmt", "6"],
                       capture_output=True, text=True)
    io_utils.write_final_results(output_dir, {"program": program, "returncode": r.returncode}, ["blast_results.tsv"])
    return r.returncode == 0


ACTIONS = {
    "makeblastdb": action_makeblastdb,
    "run_blast": action_run_blast,
}


def main():
    parser = argparse.ArgumentParser(description="NCBI BLAST+ tool")
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
