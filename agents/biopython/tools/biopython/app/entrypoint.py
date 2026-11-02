#!/usr/bin/env python3
"""Entrypoint for the Biopython Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "biopython"


def action_parse_sequences(input_dir, output_dir, params):
    io_utils.log_step("parse_sequences", "Biopython")
    import os
    from Bio import SeqIO
    files = io_utils.list_input_files(input_dir, ["*.fasta", "*.fa", "*.gb", "*.gbk", "*.fastq"])
    if not files:
        io_utils.log_error("no sequence files found")
        return False
    records = []
    for path in files:
        fmt = "genbank" if path.endswith((".gb", ".gbk")) else ("fastq" if path.endswith(".fastq") else "fasta")
        for rec in SeqIO.parse(path, fmt):
            records.append({"id": rec.id, "length": len(rec.seq), "description": rec.description})
    io_utils.write_json(output_dir, "records.json", records)
    io_utils.write_final_results(output_dir, {"records": len(records)}, ["records.json"])
    return True


def action_analyze_sequence(input_dir, output_dir, params):
    io_utils.log_step("analyze_sequence", "Biopython")
    import os
    from Bio import SeqIO
    from Bio.SeqUtils import gc_fraction
    files = io_utils.list_input_files(input_dir, ["*.fasta", "*.fa"])
    if not files:
        io_utils.log_error("no fasta files found")
        return False
    out = []
    for path in files:
        for rec in SeqIO.parse(path, "fasta"):
            seq = rec.seq
            entry = {"id": rec.id, "length": len(seq), "gc_fraction": round(gc_fraction(seq), 4)}
            try:
                entry["protein"] = str(seq.translate(to_stop=True))[:200]
            except Exception:
                entry["protein"] = None
            out.append(entry)
    io_utils.write_json(output_dir, "analysis.json", out)
    io_utils.write_final_results(output_dir, {"records": len(out)}, ["analysis.json"])
    return True


ACTIONS = {
    "parse_sequences": action_parse_sequences,
    "analyze_sequence": action_analyze_sequence,
}


def main():
    parser = argparse.ArgumentParser(description="Biopython tool")
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
