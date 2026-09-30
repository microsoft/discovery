#!/usr/bin/env python3
"""Entrypoint for the MODELLER Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "modeller"


def action_build_model(input_dir, output_dir, params):
    io_utils.log_step("build_model", "MODELLER")
    import os
    try:
        from modeller import Environ, log
        from modeller.automodel import AutoModel
    except Exception as e:
        io_utils.log_error(f"MODELLER unavailable (license?): {e}")
        return False
    aln = params.get("alignment")
    target = params.get("target")
    template = params.get("template")
    if not (aln and target and template):
        io_utils.log_error("alignment, target, and template params are required")
        return False
    aln_path = aln if os.path.isabs(aln) else os.path.join(input_dir, os.path.basename(aln))
    log.none()
    env = Environ()
    env.io.atom_files_directory = [input_dir]
    cwd = os.getcwd(); os.chdir(output_dir)
    try:
        a = AutoModel(env, alnfile=aln_path, knowns=template, sequence=target)
        a.starting_model = 1; a.ending_model = 1
        a.make()
        outputs = [x["name"] for x in a.outputs]
    finally:
        os.chdir(cwd)
    io_utils.write_final_results(output_dir, {"models": outputs}, outputs)
    return True


ACTIONS = {
    "build_model": action_build_model,
}


def main():
    parser = argparse.ArgumentParser(description="MODELLER tool")
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
