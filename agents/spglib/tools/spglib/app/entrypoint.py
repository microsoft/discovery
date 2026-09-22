#!/usr/bin/env python3
"""Entrypoint for the spglib Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "spglib"


def action_analyze_symmetry(input_dir, output_dir, params):
    io_utils.log_step("analyze_symmetry", "spglib")
    import os
    import spglib
    from ase.io import read
    files = io_utils.list_input_files(input_dir, ["*.cif", "POSCAR*", "*.vasp"])
    if not files:
        io_utils.log_error("no structure files found")
        return False
    symprec = float(params.get("symprec", 1e-5))
    rows = []
    for f in files:
        atoms = read(f)
        cell = (atoms.get_cell()[:], atoms.get_scaled_positions(), atoms.get_atomic_numbers())
        ds = spglib.get_symmetry_dataset(cell, symprec=symprec)
        if ds is None:
            rows.append({"file": os.path.basename(f), "error": "symmetry not found"})
            continue
        rows.append({"file": os.path.basename(f),
                     "international": ds.get("international") if isinstance(ds, dict) else ds.international,
                     "number": ds.get("number") if isinstance(ds, dict) else ds.number})
    io_utils.write_json(output_dir, "symmetry.json", rows)
    io_utils.write_final_results(output_dir, {"structures": len(rows)}, ["symmetry.json"])
    return True


ACTIONS = {
    "analyze_symmetry": action_analyze_symmetry,
}


def main():
    parser = argparse.ArgumentParser(description="spglib tool")
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
