#!/usr/bin/env python3
"""Entrypoint for the Cantera Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "cantera"


def action_equilibrate(input_dir, output_dir, params):
    io_utils.log_step("equilibrate", "Cantera")
    import os
    import cantera as ct
    mech = params.get("mechanism", "gri30.yaml")
    mech_files = io_utils.list_input_files(input_dir, ["*.yaml", "*.cti"])
    if mech_files and not os.path.isabs(mech):
        mech = mech_files[0]
    T = float(params.get("temperature", 1500))
    P = float(params.get("pressure", 101325))
    comp = params.get("composition", "CH4:1, O2:2, N2:7.52")
    gas = ct.Solution(mech)
    gas.TPX = T, P, comp
    gas.equilibrate("TP")
    fractions = gas.mole_fraction_dict()
    major = {sp: float(x) for sp, x in fractions.items() if x > 1e-4}
    io_utils.write_json(output_dir, "equilibrium.json",
                        {"T": T, "P": P, "adiabatic_none": True, "major_species": major})
    io_utils.write_final_results(output_dir, {"species_tracked": len(major)}, ["equilibrium.json"])
    return True


ACTIONS = {
    "equilibrate": action_equilibrate,
}


def main():
    parser = argparse.ArgumentParser(description="Cantera tool")
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
