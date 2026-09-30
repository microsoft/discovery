#!/usr/bin/env python3
"""Entrypoint for the Phonopy Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "phonopy"


def action_compute_phonons(input_dir, output_dir, params):
    io_utils.log_step("compute_phonons", "Phonopy")
    import os
    import numpy as np
    from phonopy import Phonopy
    from phonopy.interface.calculator import read_crystal_structure
    files = io_utils.list_input_files(input_dir, ["POSCAR*", "*.cif", "*.vasp"])
    if not files:
        io_utils.log_error("no structure files found")
        return False
    sc = [int(x) for x in params.get("supercell", "2 2 2").split()]
    unitcell, _ = read_crystal_structure(files[0], interface_mode="vasp")
    phonon = Phonopy(unitcell, supercell_matrix=np.diag(sc))
    phonon.generate_displacements(distance=0.01)
    supercells = phonon.supercells_with_displacements
    summary = {"file": os.path.basename(files[0]), "n_atoms_unitcell": len(unitcell),
               "supercell_matrix": sc, "n_displacements": len(supercells)}
    io_utils.write_json(output_dir, "phonons.json", summary)
    io_utils.write_final_results(output_dir, summary, ["phonons.json"])
    return True


ACTIONS = {
    "compute_phonons": action_compute_phonons,
}


def main():
    parser = argparse.ArgumentParser(description="Phonopy tool")
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
