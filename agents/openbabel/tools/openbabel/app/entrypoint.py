#!/usr/bin/env python3
"""Entrypoint for the Open Babel Discovery tool. CPU-only."""
import os
import sys
import json
import argparse

sys.path.insert(0, "/app")
import io_utils

TOOL_NAME = "openbabel"


def action_convert_formats(input_dir, output_dir, params):
    io_utils.log_step("convert_formats", "Open Babel")
    import os
    from openbabel import pybel
    out_fmt = params.get("output_format", "smi")
    gen3d = bool(params.get("gen3d", False))
    files = io_utils.list_input_files(input_dir, ["*.smi", "*.sdf", "*.mol", "*.mol2", "*.pdb", "*.xyz"])
    if not files:
        io_utils.log_error("no chemistry files found")
        return False
    os.makedirs(output_dir, exist_ok=True)
    written = []
    count = 0
    for path in files:
        in_fmt = os.path.splitext(path)[1].lstrip(".") or "smi"
        out_path = os.path.join(output_dir, os.path.splitext(os.path.basename(path))[0] + "." + out_fmt)
        out = pybel.Outputfile(out_fmt, out_path, overwrite=True)
        for mol in pybel.readfile(in_fmt, path):
            if gen3d:
                mol.make3D()
            out.write(mol)
            count += 1
        out.close()
        written.append(os.path.basename(out_path))
    io_utils.write_final_results(output_dir, {"molecules": count, "files": len(written)}, written)
    return True


def action_generate_descriptors(input_dir, output_dir, params):
    io_utils.log_step("generate_descriptors", "Open Babel")
    import os
    from openbabel import pybel
    files = io_utils.list_input_files(input_dir, ["*.smi", "*.sdf", "*.mol", "*.mol2"])
    if not files:
        io_utils.log_error("no chemistry files found")
        return False
    rows = []
    for path in files:
        in_fmt = os.path.splitext(path)[1].lstrip(".") or "smi"
        for mol in pybel.readfile(in_fmt, path):
            d = mol.calcdesc()
            rows.append({"title": mol.title, "MW": d.get("MW"), "logP": d.get("logP"),
                         "TPSA": d.get("TPSA"), "HBD": d.get("HBD"), "HBA1": d.get("HBA1")})
    io_utils.write_json(output_dir, "descriptors.json", rows)
    io_utils.write_final_results(output_dir, {"molecules": len(rows)}, ["descriptors.json"])
    return True


ACTIONS = {
    "convert_formats": action_convert_formats,
    "generate_descriptors": action_generate_descriptors,
}


def main():
    parser = argparse.ArgumentParser(description="Open Babel tool")
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
