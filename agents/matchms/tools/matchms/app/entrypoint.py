#!/usr/bin/env python3
"""Entrypoint for the matchms Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "matchms"


def action_compare_spectra(input_dir, output_dir, params):
    io_utils.log_step("compare_spectra", "matchms")
    import os
    import numpy as np
    from matchms.importing import load_from_mgf, load_from_msp
    from matchms.similarity import CosineGreedy
    from matchms import calculate_scores
    files = io_utils.list_input_files(input_dir, ["*.mgf", "*.msp"])
    if not files:
        io_utils.log_error("no spectra files found")
        return False
    spectra = []
    for f in files:
        loader = load_from_mgf if f.endswith(".mgf") else load_from_msp
        spectra += list(loader(f))
    if len(spectra) < 2:
        io_utils.log_error("need at least two spectra")
        return False
    scores = calculate_scores(spectra, spectra, CosineGreedy(), is_symmetric=True)
    arr = scores.scores.to_array()
    sim = np.array([[float(arr[i][j][0]) for j in range(len(spectra))] for i in range(len(spectra))])
    io_utils.write_json(output_dir, "similarity.json", {"n_spectra": len(spectra), "matrix": sim.tolist()})
    io_utils.write_final_results(output_dir, {"spectra": len(spectra)}, ["similarity.json"])
    return True


ACTIONS = {
    "compare_spectra": action_compare_spectra,
}


def main():
    parser = argparse.ArgumentParser(description="matchms tool")
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
