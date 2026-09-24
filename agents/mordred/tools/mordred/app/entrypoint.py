#!/usr/bin/env python3
"""Entrypoint for the Mordred Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "mordred"


def action_compute_descriptors(input_dir, output_dir, params):
    io_utils.log_step("compute_descriptors", "Mordred")
    import os, csv
    from rdkit import Chem
    from mordred import Calculator, descriptors
    files = io_utils.list_input_files(input_dir, ["*.smi", "*.csv", "*.txt"])
    if not files:
        io_utils.log_error("no input files found")
        return False
    col = params.get("column_name")
    smiles = []
    for f in files:
        if f.endswith(".csv"):
            with open(f) as fh:
                for r in csv.DictReader(fh):
                    s = r.get(col) if col else next(iter(r.values()))
                    if s:
                        smiles.append(s)
        else:
            with open(f) as fh:
                smiles += [ln.split()[0] for ln in fh if ln.strip()]
    calc = Calculator(descriptors, ignore_3D=True)
    rows = []
    for s in smiles:
        mol = Chem.MolFromSmiles(s)
        if mol is None:
            continue
        d = calc(mol)
        rows.append({"smiles": s, "n_descriptors": len(d.asdict()),
                     "MW": float(d.asdict().get("MW")) if d.asdict().get("MW") is not None else None})
    io_utils.write_json(output_dir, "descriptors.json", rows)
    io_utils.write_final_results(output_dir, {"molecules": len(rows)}, ["descriptors.json"])
    return True


ACTIONS = {
    "compute_descriptors": action_compute_descriptors,
}


def main():
    parser = argparse.ArgumentParser(description="Mordred tool")
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
