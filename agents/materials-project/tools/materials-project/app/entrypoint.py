#!/usr/bin/env python3
"""Entrypoint for the Materials Project Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "materials-project"


def action_query_materials(input_dir, output_dir, params):
    io_utils.log_step("query_materials", "Materials Project")
    import os
    from mp_api.client import MPRester
    formula = params.get("formula")
    api_key = params.get("api_key") or os.environ.get("MP_API_KEY")
    if not formula:
        io_utils.log_error("formula parameter is required")
        return False
    if not api_key:
        io_utils.log_error("Materials Project API key required (api_key or MP_API_KEY)")
        return False
    with MPRester(api_key) as mpr:
        docs = mpr.materials.summary.search(
            formula=formula,
            fields=["material_id", "formula_pretty", "formation_energy_per_atom",
                    "band_gap", "energy_above_hull"])
    rows = [{"material_id": str(d.material_id), "formula": d.formula_pretty,
             "formation_energy_per_atom": d.formation_energy_per_atom,
             "band_gap": d.band_gap, "energy_above_hull": d.energy_above_hull} for d in docs]
    io_utils.write_json(output_dir, "materials.json", rows)
    io_utils.write_final_results(output_dir, {"formula": formula, "hits": len(rows)}, ["materials.json"])
    return True


ACTIONS = {
    "query_materials": action_query_materials,
}


def main():
    parser = argparse.ArgumentParser(description="Materials Project tool")
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
