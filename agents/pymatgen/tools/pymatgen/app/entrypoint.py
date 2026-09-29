#!/usr/bin/env python3
"""Entrypoint for the Pymatgen Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "pymatgen"


def action_analyze_structure(input_dir, output_dir, params):
    io_utils.log_step("analyze_structure", "Pymatgen")
    import os
    from pymatgen.core import Structure
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    files = io_utils.list_input_files(input_dir, ["*.cif", "POSCAR*", "*.vasp"])
    if not files:
        io_utils.log_error("no structure files found")
        return False
    rows = []
    for f in files:
        s = Structure.from_file(f)
        sga = SpacegroupAnalyzer(s)
        rows.append({"file": os.path.basename(f), "formula": s.composition.reduced_formula,
                     "space_group": sga.get_space_group_symbol(), "density_g_cm3": round(float(s.density), 4),
                     "volume_A3": round(float(s.volume), 4), "n_sites": len(s)})
    io_utils.write_json(output_dir, "structures.json", rows)
    io_utils.write_final_results(output_dir, {"structures": len(rows)}, ["structures.json"])
    return True


ACTIONS = {
    "analyze_structure": action_analyze_structure,
}


def main():
    parser = argparse.ArgumentParser(description="Pymatgen tool")
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
