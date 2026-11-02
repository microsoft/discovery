#!/usr/bin/env python3
"""Entrypoint for the Samtools / BCFtools Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "samtools-suite"


def action_process_alignments(input_dir, output_dir, params):
    io_utils.log_step("process_alignments", "Samtools / BCFtools")
    import os, subprocess
    files = io_utils.list_input_files(input_dir, ["*.bam", "*.cram", "*.sam"])
    if not files:
        io_utils.log_error("no alignment files found")
        return False
    os.makedirs(output_dir, exist_ok=True)
    rows = []
    for f in files:
        fs = subprocess.run(["samtools", "flagstat", f], capture_output=True, text=True)
        rows.append({"file": os.path.basename(f), "flagstat": fs.stdout})
    io_utils.write_json(output_dir, "alignment_stats.json", rows)
    io_utils.write_final_results(output_dir, {"files": len(rows)}, ["alignment_stats.json"])
    return True


def action_process_variants(input_dir, output_dir, params):
    io_utils.log_step("process_variants", "Samtools / BCFtools")
    import os, subprocess
    files = io_utils.list_input_files(input_dir, ["*.vcf", "*.vcf.gz", "*.bcf"])
    if not files:
        io_utils.log_error("no variant files found")
        return False
    os.makedirs(output_dir, exist_ok=True)
    rows = []
    for f in files:
        r = subprocess.run(["bcftools", "stats", f], capture_output=True, text=True)
        out = os.path.join(output_dir, os.path.basename(f) + ".stats.txt")
        with open(out, "w") as fh:
            fh.write(r.stdout)
        rows.append({"file": os.path.basename(f), "returncode": r.returncode, "stats": os.path.basename(out)})
    io_utils.write_json(output_dir, "variant_stats.json", rows)
    io_utils.write_final_results(output_dir, {"files": len(rows)}, ["variant_stats.json"])
    return all(x["returncode"] == 0 for x in rows)


ACTIONS = {
    "process_alignments": action_process_alignments,
    "process_variants": action_process_variants,
}


def main():
    parser = argparse.ArgumentParser(description="Samtools / BCFtools tool")
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
