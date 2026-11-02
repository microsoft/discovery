#!/usr/bin/env python3
"""Entrypoint for the KEGG Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "kegg"


def action_query_kegg(input_dir, output_dir, params):
    io_utils.log_step("query_kegg", "KEGG")
    import os, requests
    op = params.get("operation", "get")
    db = params.get("database", "compound")
    query = params.get("query")
    if not query:
        io_utils.log_error("query parameter is required")
        return False
    if op == "find":
        url = f"https://rest.kegg.jp/find/{db}/{query}"
    else:
        url = f"https://rest.kegg.jp/get/{query}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    text = r.text
    out = os.path.join(output_dir, "kegg_result.txt")
    os.makedirs(output_dir, exist_ok=True)
    with open(out, "w") as fh:
        fh.write(text)
    io_utils.write_final_results(output_dir, {"operation": op, "database": db, "bytes": len(text)}, ["kegg_result.txt"])
    return True


ACTIONS = {
    "query_kegg": action_query_kegg,
}


def main():
    parser = argparse.ArgumentParser(description="KEGG tool")
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
