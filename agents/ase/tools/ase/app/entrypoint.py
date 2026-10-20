#!/usr/bin/env python3
"""Entrypoint for the ASE (Atomic Simulation Environment) Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "ase"


def action_optimize_structure(input_dir, output_dir, params):
    io_utils.log_step("optimize_structure", "ASE (Atomic Simulation Environment)")
    import os
    from ase.io import read, write
    from ase.calculators.emt import EMT
    from ase.optimize import BFGS
    files = io_utils.list_input_files(input_dir, ["*.xyz", "*.cif", "*.traj", "POSCAR*"])
    if not files:
        io_utils.log_error("no structure files found")
        return False
    os.makedirs(output_dir, exist_ok=True)
    fmax = float(params.get("fmax", 0.05))
    rows = []
    for f in files:
        atoms = read(f)
        atoms.calc = EMT()
        e0 = float(atoms.get_potential_energy())
        opt = BFGS(atoms, logfile=None)
        opt.run(fmax=fmax, steps=200)
        e1 = float(atoms.get_potential_energy())
        out = os.path.join(output_dir, os.path.splitext(os.path.basename(f))[0] + "_opt.xyz")
        write(out, atoms)
        rows.append({"file": os.path.basename(f), "e_initial_eV": e0, "e_final_eV": e1})
    io_utils.write_json(output_dir, "optimization.json", rows)
    io_utils.write_final_results(output_dir, {"structures": len(rows)}, ["optimization.json"])
    return True


ACTIONS = {
    "optimize_structure": action_optimize_structure,
}


def main():
    parser = argparse.ArgumentParser(description="ASE (Atomic Simulation Environment) tool")
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
