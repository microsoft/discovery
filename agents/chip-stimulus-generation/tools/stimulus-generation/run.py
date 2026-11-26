#!/usr/bin/env python3
"""One stimulus operation from explicit JSON, with immutable mounted inputs."""
import json
import math
import sys
import traceback
from pathlib import Path

import stimulus_generation_utils as utils

TOOL = "stimulus-generation"
SUPPORTED_SCENARIOS = ("constrained_random", "directed", "coverage_directed")
INPUT_DIR = Path("/input")
OUTPUT_DIR = Path("/output")
WORK_DIR = Path("/workdir")


def _reject_constant(value):
    raise ValueError("non-finite JSON value is not allowed: " + value)


def _input_path(value):
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError("input paths must be absolute under /input")
    path = Path(value).resolve()
    if not path.is_relative_to(INPUT_DIR.resolve()):
        raise ValueError("input path must stay under /input")
    if not path.is_file():
        raise ValueError("input file does not exist: " + value)
    return path


def _number(value, name, minimum=0):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < minimum):
        raise ValueError(name + " must be a finite number >= " + str(minimum))


def _integer(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(name + " must be an integer >= " + str(minimum))


def _domain(spec, name, predicate=False):
    if isinstance(spec, list):
        spec = {"values": spec}
    if not isinstance(spec, dict):
        if predicate and isinstance(spec, (str, int, float, bool)):
            return
        raise ValueError(name + " must be an object or value-list")
    if not spec or set(spec) - {"min", "max", "values", "weights"}:
        raise ValueError(name + " has missing or unsupported domain keys")
    if "values" in spec:
        values = spec["values"]
        if (not isinstance(values, list) or not values
                or any(v is None or isinstance(v, (dict, list)) for v in values)):
            raise ValueError(name + ".values must be a nonempty scalar array")
        if "min" in spec or "max" in spec:
            raise ValueError(name + " must use values OR a range")
        if "weights" in spec:
            weights = spec["weights"]
            if not isinstance(weights, list) or len(weights) != len(values):
                raise ValueError(name + ".weights must match values")
            for weight in weights:
                _number(weight, name + ".weight")
            if not any(weights):
                raise ValueError(name + ".weights must have positive total")
    else:
        if "weights" in spec or (not predicate and not {"min", "max"} <= set(spec)):
            raise ValueError(name + " requires min and max")
        for key in ("min", "max"):
            if key in spec and (isinstance(spec[key], bool)
                               or not isinstance(spec[key], int)):
                raise ValueError(name + "." + key + " must be an integer")


def _validate_params(params):
    if not isinstance(params, dict) or params.get("scenario") not in SUPPORTED_SCENARIOS:
        raise ValueError("scenario must be one of: " + ", ".join(SUPPORTED_SCENARIOS))
    for key in ("pdk_binding", "deck_vars", "constraints", "value_distributions",
                "soft_constraints"):
        if key in params and not isinstance(params[key], dict):
            raise ValueError(key + " must be an inline object")
    if "vplan_file" in params:
        path = _input_path(params["vplan_file"])
        with path.open(encoding="utf-8-sig") as stream:
            vplan = json.load(stream, parse_constant=_reject_constant)
        if not isinstance(vplan, dict):
            raise ValueError("vplan_file must contain a JSON object")
    if params["scenario"] == "directed":
        tests = params.get("tests")
        if not isinstance(tests, list) or not tests or any(not isinstance(t, dict) for t in tests):
            raise ValueError("tests must be a nonempty array of objects")
        return params
    if not isinstance(params.get("dut_top"), str) or not params["dut_top"].strip():
        raise ValueError("dut_top must be a nonempty string")
    constraints = params.get("constraints")
    if not constraints:
        raise ValueError("constraints must be a nonempty inline object")
    for field, spec in constraints.items():
        if not field:
            raise ValueError("constraint field names must be nonempty")
        _domain(spec, "constraints." + field)
    for key, default, minimum in (("count", 100, 1), ("max_rejection_tries", 50, 0)):
        _integer(params.get(key, default), key, minimum)
    if "seeds" in params:
        seeds = params["seeds"]
        if not isinstance(seeds, list) or not seeds:
            raise ValueError("seeds must be a nonempty integer array")
        for seed in seeds:
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise ValueError("seeds must be a nonempty integer array")
    for key in ("constraint_blocks", "randc_fields", "holes"):
        if key in params and not isinstance(params[key], list):
            raise ValueError(key + " must be an array")
    for field in params.get("randc_fields", []):
        if not isinstance(field, str) or field not in constraints:
            raise ValueError("randc_fields must name constrained fields")
    for block in params.get("constraint_blocks", []):
        if not isinstance(block, dict) or set(block) - {"if", "then"}:
            raise ValueError("constraint blocks require only if/then object keys")
        for side in ("if", "then"):
            conditions = block.get(side, {})
            if not isinstance(conditions, dict):
                raise ValueError("constraint block " + side + " must be an object")
            for field, spec in conditions.items():
                if field not in constraints:
                    raise ValueError("constraint block names unknown field: " + field)
                _domain(spec, "constraint block " + side + "." + field, predicate=True)
    for field, dist in params.get("value_distributions", {}).items():
        if field not in constraints or not isinstance(dist, dict) or not dist:
            raise ValueError("value_distributions must map known fields to weight objects")
        for weight in dist.values():
            _number(weight, "distribution weight")
        if not any(dist.values()):
            raise ValueError("distribution weights must have positive total")
    for field, pref in params.get("soft_constraints", {}).items():
        if field not in constraints or not isinstance(pref, dict) or set(pref) - {"value", "probability"}:
            raise ValueError("soft_constraints must map known fields to value/probability objects")
        probability = pref.get("probability", 0.9)
        _number(probability, "soft probability")
        if probability > 1:
            raise ValueError("soft probability must be <= 1")
    for hole in params.get("holes", []):
        if not isinstance(hole, (str, dict)):
            raise ValueError("holes must contain strings or objects")
        if isinstance(hole, dict):
            if "count" in hole:
                _integer(hole["count"], "hole count", 1)
            if "values" in hole and (not isinstance(hole["values"], list) or not hole["values"]):
                raise ValueError("hole values must be a nonempty array")
    return params


def load_params(args):
    if not args:
        args = ["--params-file", str(INPUT_DIR / "params.json")]
    if len(args) == 1:
        params = json.loads(args[0], parse_constant=_reject_constant)
    elif len(args) == 2 and args[0] == "--params-file":
        with _input_path(args[1]).open(encoding="utf-8-sig") as stream:
            params = json.load(stream, parse_constant=_reject_constant)
    else:
        raise ValueError("use --params-file /input/params.json or one JSON object")
    return _validate_params(params)


def _authoritative_exit_code(path=None):
    try:
        with Path(path or OUTPUT_DIR / "common_design_envelope.json").open(encoding="utf-8") as stream:
            envelope = json.load(stream)
        return 0 if (envelope.get("status") == "completed"
                     and envelope.get("validation", {}).get("verdict")
                     in ("pass", "pass_with_caveats", "review")) else 1
    except (OSError, ValueError, TypeError, AttributeError):
        return 1


def main(args=None):
    for path in (OUTPUT_DIR, WORK_DIR):
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            print(f"{TOOL}: refusing nonempty {path}; use a fresh operation", file=sys.stderr)
            return 2
    utils.quick_setup(str(OUTPUT_DIR), str(WORK_DIR))
    params = None
    try:
        params = load_params(sys.argv[1:] if args is None else args)
        results = utils.dispatch(params)
        if "vplan_file" in params:
            results["vplan"] = params["vplan_file"]
            results.setdefault("inputs_ref", {})["vplan_file"] = params["vplan_file"]
    except Exception as exc:
        traceback.print_exc()
        results = {"tool": TOOL, "status": "failed", "objective": "generate stimulus",
                   "tools_used": [{"name": TOOL, "version": "1.2.0"}],
                   "results": {}, "error": str(exc),
                   "validation": {"verdict": "fail", "note": str(exc)},
                   "traceback": traceback.format_exc(), "input_parameters": params}
    utils.save_final_results(results)
    code = _authoritative_exit_code()
    if code:
        path = OUTPUT_DIR / "common_design_envelope.json"
        if path.is_file():
            with path.open(encoding="utf-8") as stream:
                persisted = json.load(stream)
            print("CDE_JSON=" + json.dumps(persisted, ensure_ascii=True,
                                          separators=(",", ":")), flush=True)
    print(f"{TOOL}: persisted CDE exit={code}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
