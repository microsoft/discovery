#!/usr/bin/env python3
"""Entrypoint for the Matminer Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "matminer"


def action_featurize(input_dir, output_dir, params):
    io_utils.log_step("featurize", "Matminer")
    import os
    from pymatgen.core import Composition
    from matminer.featurizers.composition import ElementProperty
    files = io_utils.list_input_files(input_dir, ["*.txt", "*.csv"])
    if not files:
        io_utils.log_error("no input files found")
        return False
    formulas = []
    for f in files:
        with open(f) as fh:
            formulas += [ln.strip().split(",")[0] for ln in fh if ln.strip()]
    ep = ElementProperty.from_preset("magpie")
    labels = ep.feature_labels()
    rows = []
    for formula in formulas:
        try:
            feats = ep.featurize(Composition(formula))
            rows.append({"formula": formula, "n_features": len(feats),
                         "features": dict(zip(labels[:10], [float(x) for x in feats[:10]]))})
        except Exception as e:
            rows.append({"formula": formula, "error": str(e)})
    io_utils.write_json(output_dir, "features.json", rows)
    io_utils.write_final_results(output_dir, {"compositions": len(rows), "n_features": len(labels)}, ["features.json"])
    return True


ACTIONS = {
    "featurize": action_featurize,
}


def main():
    parser = argparse.ArgumentParser(description="Matminer tool")
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
