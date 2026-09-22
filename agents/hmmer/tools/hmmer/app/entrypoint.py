#!/usr/bin/env python3
"""Entrypoint for the HMMER Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "hmmer"


def action_hmmbuild(input_dir, output_dir, params):
    io_utils.log_step("hmmbuild", "HMMER")
    import os, subprocess
    files = io_utils.list_input_files(input_dir, ["*.sto", "*.aln", "*.msa", "*.fasta"])
    if not files:
        io_utils.log_error("no alignment files found")
        return False
    os.makedirs(output_dir, exist_ok=True)
    results = []
    for f in files:
        out = os.path.join(output_dir, os.path.splitext(os.path.basename(f))[0] + ".hmm")
        r = subprocess.run(["hmmbuild", out, f], capture_output=True, text=True)
        results.append({"file": os.path.basename(f), "returncode": r.returncode})
    io_utils.write_json(output_dir, "hmmbuild.json", results)
    io_utils.write_final_results(output_dir, {"profiles": len(results)}, ["hmmbuild.json"])
    return all(x["returncode"] == 0 for x in results)


def action_hmmsearch(input_dir, output_dir, params):
    io_utils.log_step("hmmsearch", "HMMER")
    import os, subprocess
    hmm = params.get("hmm")
    seqdb = params.get("seqdb")
    if not (hmm and seqdb):
        hmms = io_utils.list_input_files(input_dir, ["*.hmm"])
        seqs = io_utils.list_input_files(input_dir, ["*.fasta", "*.fa"])
        hmm = hmms[0] if hmms else None
        seqdb = seqs[0] if seqs else None
    if not (hmm and seqdb):
        io_utils.log_error("need hmm and seqdb")
        return False
    hmm = hmm if os.path.isabs(hmm) else os.path.join(input_dir, os.path.basename(hmm))
    seqdb = seqdb if os.path.isabs(seqdb) else os.path.join(input_dir, os.path.basename(seqdb))
    os.makedirs(output_dir, exist_ok=True)
    out = os.path.join(output_dir, "hmmsearch.tbl")
    r = subprocess.run(["hmmsearch", "--tblout", out, hmm, seqdb], capture_output=True, text=True)
    io_utils.write_final_results(output_dir, {"returncode": r.returncode}, ["hmmsearch.tbl"])
    return r.returncode == 0


ACTIONS = {
    "hmmbuild": action_hmmbuild,
    "hmmsearch": action_hmmsearch,
}


def main():
    parser = argparse.ArgumentParser(description="HMMER tool")
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
