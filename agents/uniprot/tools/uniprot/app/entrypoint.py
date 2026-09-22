#!/usr/bin/env python3
"""Entrypoint for the UniProt Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "uniprot"


def action_query_uniprot(input_dir, output_dir, params):
    io_utils.log_step("query_uniprot", "UniProt")
    import os, requests
    query = params.get("query")
    if not query:
        io_utils.log_error("query parameter is required")
        return False
    size = int(params.get("size", 25))
    url = "https://rest.uniprot.org/uniprotkb/search"
    r = requests.get(url, params={"query": query, "format": "json", "size": size}, timeout=60)
    r.raise_for_status()
    data = r.json()
    results = [{"accession": e.get("primaryAccession"),
                "id": e.get("uniProtkbId"),
                "protein": e.get("proteinDescription", {}).get("recommendedName", {}).get("fullName", {}).get("value"),
                "organism": e.get("organism", {}).get("scientificName")}
               for e in data.get("results", [])]
    io_utils.write_json(output_dir, "uniprot.json", results)
    io_utils.write_final_results(output_dir, {"query": query, "hits": len(results)}, ["uniprot.json"])
    return True


ACTIONS = {
    "query_uniprot": action_query_uniprot,
}


def main():
    parser = argparse.ArgumentParser(description="UniProt tool")
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
