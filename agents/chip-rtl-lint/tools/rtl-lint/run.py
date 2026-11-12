#!/usr/bin/env python3
"""Single in-container RTL lint operation; no host runtime dependencies."""
import json
import sys
import traceback
from pathlib import Path

import rtl_lint_utils as utils

TOOL = "rtl-lint"
SUPPORTED_SCENARIOS = ("lint_gate", "lint", "format")


def load_params(args):
    if not args:
        args = ["--params-file", "/input/params.json"]
    if len(args) == 1:
        params = json.loads(args[0])
    elif len(args) == 2 and args[0] == "--params-file":
        path = Path(args[1]).resolve()
        if not path.is_relative_to(Path("/input").resolve()):
            raise ValueError("parameter file must be under /input")
        with path.open(encoding="utf-8-sig") as stream:
            params = json.load(stream)
    else:
        raise ValueError("use --params-file /input/params.json or one JSON object")
    if not isinstance(params, dict) or params.get("scenario") not in SUPPORTED_SCENARIOS:
        raise ValueError("scenario must be one of: " + ", ".join(SUPPORTED_SCENARIOS))
    for key in ("source", "sources", "rules_config", "waiver_files"):
        if key not in params:
            continue
        values = params[key] if key in ("sources", "waiver_files") else [params[key]]
        if not isinstance(values, list) or (key == "sources" and not values):
            raise ValueError(key + " must be a nonempty array")
        for value in values:
            if (not isinstance(value, str) or not value.startswith("/input/")
                    or not Path(value).resolve().is_relative_to(Path("/input").resolve())):
                raise ValueError(key + " paths must stay under /input")
    if params.get("source") and params.get("sources"):
        raise ValueError("provide source or sources, not both")
    return params


def _authoritative_exit_code(path="/output/common_design_envelope.json"):
    with open(path, encoding="utf-8") as stream:
        result = json.load(stream)
    return 0 if (result.get("status") == "completed"
                 and result.get("validation", {}).get("verdict") == "pass") else 1


def main(args=None):
    for path in (Path("/output"), Path("/workdir")):
        if path.exists() and any(path.iterdir()):
            print(f"{TOOL}: refusing nonempty {path}; use a fresh operation", file=sys.stderr)
            return 2
    utils.quick_setup(output_dir="/output", work_dir="/workdir")
    params = None
    try:
        params = load_params(sys.argv[1:] if args is None else args)
        results = utils.dispatch(params)
    except Exception as exc:
        # The operation boundary records the exception, never a success fallback.
        traceback.print_exc()
        results = {"tool": TOOL, "status": "failed", "error": str(exc),
                   "validation": {"verdict": "fail", "note": str(exc)},
                   "traceback": traceback.format_exc(), "input_parameters": params}
    utils.save_final_results(results)
    code = _authoritative_exit_code()
    print(f"{TOOL}: persisted CDE exit={code}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
