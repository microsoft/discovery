#!/usr/bin/env python3
"""Entrypoint for the PySCF Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "pyscf"


def action_run_scf(input_dir, output_dir, params):
    io_utils.log_step("run_scf", "PySCF")
    import os
    from pyscf import gto, scf
    files = io_utils.list_input_files(input_dir, ["*.xyz"])
    if not files:
        io_utils.log_error("no xyz files found")
        return False
    basis = params.get("basis", "sto-3g")
    results = []
    for f in files:
        mol = gto.M(atom=f, basis=basis)
        mf = scf.RHF(mol)
        e = mf.kernel()
        results.append({"file": os.path.basename(f), "energy_hartree": float(e), "converged": bool(mf.converged)})
    io_utils.write_json(output_dir, "scf_energies.json", results)
    io_utils.write_final_results(output_dir, {"molecules": len(results)}, ["scf_energies.json"])
    return True


def action_run_dft(input_dir, output_dir, params):
    io_utils.log_step("run_dft", "PySCF")
    import os
    from pyscf import gto, dft
    files = io_utils.list_input_files(input_dir, ["*.xyz"])
    if not files:
        io_utils.log_error("no xyz files found")
        return False
    basis = params.get("basis", "6-31g")
    xc = params.get("xc", "b3lyp")
    results = []
    for f in files:
        mol = gto.M(atom=f, basis=basis)
        mf = dft.RKS(mol)
        mf.xc = xc
        e = mf.kernel()
        results.append({"file": os.path.basename(f), "xc": xc, "energy_hartree": float(e), "converged": bool(mf.converged)})
    io_utils.write_json(output_dir, "dft_energies.json", results)
    io_utils.write_final_results(output_dir, {"molecules": len(results), "xc": xc}, ["dft_energies.json"])
    return True


ACTIONS = {
    "run_scf": action_run_scf,
    "run_dft": action_run_dft,
}


def main():
    parser = argparse.ArgumentParser(description="PySCF tool")
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
