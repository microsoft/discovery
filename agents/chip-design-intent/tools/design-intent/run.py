#!/usr/bin/env python3
"""One deterministic design-intent operation on immutable mounted parameters."""
import json
import math
import sys
import traceback
from pathlib import Path

import design_intent_utils as utils

TOOL = "design-intent"
SUPPORTED_SCENARIOS = ("normalize", "ppa_budget")
INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
WORK_DIR = Path("/workdir")


def _reject_constant(value):
    raise ValueError("non-finite JSON value is not allowed: " + value)


def _validate_params(params):
    if not isinstance(params, dict) or params.get("scenario") not in SUPPORTED_SCENARIOS:
        raise ValueError("scenario must be one of: " + ", ".join(SUPPORTED_SCENARIOS))
    for key in ("pdk_binding", "deck_vars", "interpretation", "targets"):
        if key in params and not isinstance(params[key], dict):
            raise ValueError(key + " must be an inline object")
    for key in ("requirements", "reqs", "blocks"):
        if key not in params:
            continue
        value = params[key]
        if not isinstance(value, (list, str)) or not value:
            raise ValueError(key + " must be a nonempty array or text")
        if isinstance(value, list):
            if any(not isinstance(item, (str, dict)) for item in value):
                raise ValueError(key + " entries must be strings or objects")
            for item in value:
                if not isinstance(item, dict):
                    continue
                for field in ("text", "statement", "category", "name"):
                    if field in item and not isinstance(item[field], str):
                        raise ValueError(field + " must be a string")
                if key == "blocks" and "name" not in item:
                    raise ValueError("block objects require name")
                if key == "blocks" and "weight" in item:
                    _finite_number(item["weight"], "weight")
    if "id_prefix" in params and (not isinstance(params["id_prefix"], str)
                                  or not params["id_prefix"].strip()):
        raise ValueError("id_prefix must be a nonempty string")
    if "integration_reserve_pct" in params:
        _finite_number(params["integration_reserve_pct"], "integration_reserve_pct")
    for key, value in params.get("targets", {}).items():
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("target " + key + " must be a number or unit-bearing string")
        if isinstance(value, (int, float)):
            _finite_number(value, key)
    return params


def _finite_number(value, key):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(key + " must be a finite number")
    try:
        finite = math.isfinite(float(value))
    except (ValueError, OverflowError):
        finite = False
    if not finite:
        raise ValueError(key + " must be a finite number")


def load_params(args):
    if not args:
        args = ["--params-file", str(INPUT_DIR / "params.json")]
    if len(args) == 1:
        params = json.loads(args[0], parse_constant=_reject_constant)
    elif len(args) == 2 and args[0] == "--params-file":
        path = Path(args[1]).resolve()
        if not path.is_relative_to(INPUT_DIR.resolve()):
            raise ValueError("parameter file must stay under /input")
        with path.open(encoding="utf-8-sig") as stream:
            params = json.load(stream, parse_constant=_reject_constant)
    else:
        raise ValueError("use --params-file /input/params.json or one JSON object")
    return _validate_params(params)


def _authoritative_exit_code(path=None):
    try:
        with Path(path or OUTPUT_DIR / "common_design_envelope.json").open(
                encoding="utf-8") as stream:
            result = json.load(stream)
        # Review and caveats are valid authoring outcomes, not engineering signoff.
        return 0 if (result.get("status") == "completed"
                     and result.get("validation", {}).get("verdict")
                     in ("pass", "pass_with_caveats", "review")) else 1
    except (OSError, ValueError, TypeError, AttributeError):
        return 1


def main(args=None):
    for path in (OUTPUT_DIR, WORK_DIR):
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            print(f"{TOOL}: refusing nonempty {path}; use a fresh operation", file=sys.stderr)
            return 2
    utils.quick_setup(output_dir=str(OUTPUT_DIR), work_dir=str(WORK_DIR))
    params = None
    try:
        params = load_params(sys.argv[1:] if args is None else args)
        results = utils.dispatch(params)
    except Exception as exc:
        traceback.print_exc()
        results = {"tool": TOOL, "status": "failed", "objective": "design intent",
                   "tools_used": [{"name": TOOL, "version": utils.TOOL_VERSION}],
                   "results": {}, "error": str(exc),
                   "validation": {"verdict": "fail", "note": str(exc)},
                   "traceback": traceback.format_exc(), "input_parameters": params}
    utils.save_final_results(results)
    code = _authoritative_exit_code()
    if code:
        path = OUTPUT_DIR / "common_design_envelope.json"
        if path.is_file():
            try:
                with path.open(encoding="utf-8") as stream:
                    persisted = json.load(stream)
                print("CDE_JSON=" + json.dumps(persisted, ensure_ascii=True,
                                              separators=(",", ":")), flush=True)
            except (OSError, ValueError) as exc:
                print(f"{TOOL}: could not log persisted CDE: {exc}", file=sys.stderr)
    print(f"{TOOL}: persisted CDE exit={code}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
