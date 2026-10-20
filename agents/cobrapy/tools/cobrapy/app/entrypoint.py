#!/usr/bin/env python3
"""Entrypoint for the COBRApy Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "cobrapy"


def action_flux_balance_analysis(input_dir, output_dir, params):
    io_utils.log_step("flux_balance_analysis", "COBRApy")
    import os
    import cobra
    files = io_utils.list_input_files(input_dir, ["*.xml", "*.sbml", "*.json", "*.mat"])
    if not files:
        io_utils.log_error("no model files found")
        return False
    rows = []
    for f in files:
        if f.endswith(".json"):
            model = cobra.io.load_json_model(f)
        elif f.endswith(".mat"):
            model = cobra.io.load_matlab_model(f)
        else:
            model = cobra.io.read_sbml_model(f)
        sol = model.optimize()
        rows.append({"file": os.path.basename(f), "status": sol.status,
                     "objective_value": float(sol.objective_value),
                     "n_reactions": len(model.reactions), "n_metabolites": len(model.metabolites)})
    io_utils.write_json(output_dir, "fba.json", rows)
    io_utils.write_final_results(output_dir, {"models": len(rows)}, ["fba.json"])
    return True


ACTIONS = {
    "flux_balance_analysis": action_flux_balance_analysis,
}


def main():
    parser = argparse.ArgumentParser(description="COBRApy tool")
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
