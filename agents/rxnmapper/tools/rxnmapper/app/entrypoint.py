#!/usr/bin/env python3
"""Entrypoint for the RXNMapper Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "rxnmapper"


def action_map_reactions(input_dir, output_dir, params):
    io_utils.log_step("map_reactions", "RXNMapper")
    import os
    from rxnmapper import RXNMapper
    files = io_utils.list_input_files(input_dir, ["*.txt", "*.rsmi", "*.smi"])
    if not files:
        io_utils.log_error("no reaction files found")
        return False
    rxns = []
    for f in files:
        with open(f) as fh:
            rxns += [ln.strip() for ln in fh if ln.strip()]
    mapper = RXNMapper()
    rows = []
    for i in range(0, len(rxns), 32):
        batch = rxns[i:i+32]
        for res in mapper.get_attention_guided_atom_maps(batch):
            rows.append({"mapped_rxn": res["mapped_rxn"], "confidence": res["confidence"]})
    io_utils.write_json(output_dir, "mapped_reactions.json", rows)
    io_utils.write_final_results(output_dir, {"reactions": len(rows)}, ["mapped_reactions.json"])
    return True


ACTIONS = {
    "map_reactions": action_map_reactions,
}


def main():
    parser = argparse.ArgumentParser(description="RXNMapper tool")
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
