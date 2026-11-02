#!/usr/bin/env python3
"""Entrypoint for the ViennaRNA Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "viennarna"


def action_fold_rna(input_dir, output_dir, params):
    io_utils.log_step("fold_rna", "ViennaRNA")
    import os
    import RNA
    from Bio import SeqIO
    files = io_utils.list_input_files(input_dir, ["*.fasta", "*.fa"])
    if not files:
        io_utils.log_error("no fasta files found")
        return False
    rows = []
    for path in files:
        for rec in SeqIO.parse(path, "fasta"):
            seq = str(rec.seq).upper().replace("T", "U")
            structure, mfe = RNA.fold(seq)
            rows.append({"id": rec.id, "length": len(seq), "structure": structure, "mfe_kcal_mol": round(mfe, 2)})
    io_utils.write_json(output_dir, "folds.json", rows)
    io_utils.write_final_results(output_dir, {"sequences": len(rows)}, ["folds.json"])
    return True


ACTIONS = {
    "fold_rna": action_fold_rna,
}


def main():
    parser = argparse.ArgumentParser(description="ViennaRNA tool")
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
