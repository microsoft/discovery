#!/usr/bin/env python3
"""Entrypoint for the AlphaFold DB Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "alphafold-db"


def action_fetch_structure(input_dir, output_dir, params):
    io_utils.log_step("fetch_structure", "AlphaFold DB")
    import os, requests
    accessions = []
    if params.get("accession"):
        accessions.append(params["accession"])
    for f in io_utils.list_input_files(input_dir, ["*.txt", "*.csv"]):
        with open(f) as fh:
            accessions += [ln.strip().split(",")[0] for ln in fh if ln.strip()]
    if not accessions:
        io_utils.log_error("no UniProt accessions provided")
        return False
    os.makedirs(output_dir, exist_ok=True)
    rows = []
    for acc in accessions:
        meta = requests.get(f"https://alphafold.ebi.ac.uk/api/prediction/{acc}", timeout=60)
        if meta.status_code != 200:
            rows.append({"accession": acc, "error": f"status {meta.status_code}"})
            continue
        entry = meta.json()[0]
        pdb_url = entry.get("pdbUrl")
        pdb = requests.get(pdb_url, timeout=120)
        out = os.path.join(output_dir, f"{acc}.pdb")
        with open(out, "w") as fh:
            fh.write(pdb.text)
        rows.append({"accession": acc, "uniprot_end": entry.get("uniprotEnd"),
                     "file": os.path.basename(out)})
    io_utils.write_json(output_dir, "alphafold.json", rows)
    io_utils.write_final_results(output_dir, {"structures": len(rows)}, ["alphafold.json"])
    return True


ACTIONS = {
    "fetch_structure": action_fetch_structure,
}


def main():
    parser = argparse.ArgumentParser(description="AlphaFold DB tool")
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
