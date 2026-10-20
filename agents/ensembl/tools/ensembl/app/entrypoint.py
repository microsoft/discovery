#!/usr/bin/env python3
"""Entrypoint for the Ensembl REST Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "ensembl"


def action_query_ensembl(input_dir, output_dir, params):
    io_utils.log_step("query_ensembl", "Ensembl REST")
    import os, requests
    species = params.get("species", "homo_sapiens")
    symbol = params.get("symbol")
    if not symbol:
        io_utils.log_error("symbol parameter is required")
        return False
    url = f"https://rest.ensembl.org/lookup/symbol/{species}/{symbol}"
    r = requests.get(url, headers={"Content-Type": "application/json"}, timeout=60)
    r.raise_for_status()
    data = r.json()
    io_utils.write_json(output_dir, "ensembl.json", data)
    io_utils.write_final_results(output_dir, {"species": species, "symbol": symbol,
                                              "gene_id": data.get("id")}, ["ensembl.json"])
    return True


ACTIONS = {
    "query_ensembl": action_query_ensembl,
}


def main():
    parser = argparse.ArgumentParser(description="Ensembl REST tool")
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
