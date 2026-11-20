#!/usr/bin/env python3
"""One QoR operation from strict, immutable mounted JSON parameters."""
import json
import math
import sys
import traceback
from pathlib import Path

import qor_analytics_utils as utils

TOOL = "qor-analytics"
SUPPORTED_SCENARIOS = ("aggregate", "trajectory", "anomaly_detect", "baseline_update")
INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
WORK_DIR = Path("/workdir")


def _reject_constant(value):
    raise ValueError("non-finite JSON value: " + value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _input_path(value):
    path = Path(value).resolve()
    if not path.is_relative_to(INPUT_DIR.resolve()):
        raise ValueError("input file must stay under /input")
    return path


def _validate_params(params):
    if not isinstance(params, dict) or params.get("scenario") not in SUPPORTED_SCENARIOS:
        raise ValueError("explicit top-level scenario required: " + ", ".join(SUPPORTED_SCENARIOS))
    for key in ("pdk_binding", "deck_vars", "baseline", "metric_polarity"):
        if key in params and not isinstance(params[key], dict):
            raise ValueError(key + " must be an inline object")
    if "metrics" in params and (not isinstance(params["metrics"], list)
                               or not params["metrics"]
                               or any(not isinstance(m, str) or not m for m in params["metrics"])):
        raise ValueError("metrics must be a nonempty array of names")
    if "order_key" in params and (not isinstance(params["order_key"], str)
                                  or not params["order_key"]):
        raise ValueError("order_key must be a nonempty string")
    for key in ("threshold_percent", "sigma"):
        if key in params:
            value = params[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(key + " must be a finite number")
    for key, value in params.get("baseline", {}).items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("baseline values must be finite numbers: " + key)
    if any(value not in ("min", "max") for value in params.get("metric_polarity", {}).values()):
        raise ValueError("metric_polarity values must be min or max")
    envelopes = params.get("envelopes")
    if not isinstance(envelopes, list):
        raise ValueError("envelopes must be an array")
    for entry in envelopes:
        if isinstance(entry, str):
            _input_path(entry)
        elif isinstance(entry, dict):
            for key in utils._PATH_KEYS:
                if key in entry:
                    if not isinstance(entry[key], str):
                        raise ValueError(key + " must be an input path")
                    _input_path(entry[key])
            if not entry.get("metrics") and utils._looks_like_path(entry.get("hash")):
                _input_path(entry["hash"])
            if "metrics" in entry and not isinstance(entry["metrics"], dict):
                raise ValueError("envelope metrics must be an object")
            if "context" in entry and not isinstance(entry["context"], dict):
                raise ValueError("envelope context must be an object")
        else:
            raise ValueError("envelopes entries must be objects or input paths")
    return params


def load_params(args):
    if not args:
        args = ["--params-file", str(INPUT_DIR / "params.json")]
    if len(args) == 1:
        params = json.loads(args[0], parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    elif len(args) == 2 and args[0] == "--params-file":
        with _input_path(args[1]).open(encoding="utf-8-sig") as stream:
            params = json.load(stream, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    else:
        raise ValueError("use --params-file /input/params.json or one strict JSON object")
    return _validate_params(params)


def _authoritative_exit_code(path=None):
    try:
        with Path(path or OUTPUT_DIR / "common_design_envelope.json").open(encoding="utf-8") as stream:
            envelope = json.load(stream)
        return 0 if (envelope.get("status") == "completed"
                     and envelope.get("validation", {}).get("verdict")
                     in ("pass", "review", "pass_with_caveats")) else 1
    except (OSError, ValueError, TypeError, AttributeError):
        return 1


def main(args=None):
    for path in (OUTPUT_DIR, WORK_DIR):
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            print(f"{TOOL}: refusing nonempty {path}; use fresh mounts", file=sys.stderr)
            return 2
    # Fixed runtime roots must not be overridden by inherited host environment.
    utils._OUTPUT_DIR, utils._WORK_DIR = str(OUTPUT_DIR), str(WORK_DIR)
    for path in (OUTPUT_DIR, WORK_DIR):
        path.mkdir(parents=True, exist_ok=True)
    params = None
    try:
        params = load_params(sys.argv[1:] if args is None else args)
        results = utils.dispatch(params)
    except Exception as exc:
        traceback.print_exc()
        results = utils._cde("QoR analytics", "failed", error=str(exc),
                             validation={"verdict": "fail", "note": str(exc)})
        results["input_parameters"] = params
        results["traceback"] = traceback.format_exc()
    utils.save_final_results(results)
    code = _authoritative_exit_code()
    if code:
        with (OUTPUT_DIR / "common_design_envelope.json").open(encoding="utf-8") as stream:
            persisted = json.load(stream)
        print("CDE_JSON=" + json.dumps(persisted, ensure_ascii=True, separators=(",", ":")), flush=True)
    print(f"{TOOL}: persisted CDE exit={code}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
