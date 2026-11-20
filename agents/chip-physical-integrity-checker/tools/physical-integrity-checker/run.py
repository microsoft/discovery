#!/usr/bin/env python3
"""Fail-closed entrypoint for physical-integrity-checker."""
import html
import json
import os
import sys
import traceback

# --- tool-call contract normalization (rec-1) ---
SUPPORTED_SCENARIOS = ['integrity_check']
_SCENARIO_HINT = ("Missing or unusable top-level 'scenario' key; params_json must be one JSON "
                  "object with \"scenario\" set to one of: " + ", ".join(SUPPORTED_SCENARIOS) + ". ")
_OBJECT_PARAMS = ("pdk_binding", "deck_vars")


def _normalize_params(p):
    """Accept common caller slips without guessing: nested/aliased scenario and
    object params passed as JSON text or a .json path. Never invents values."""
    import json as _j, os as _o
    if not isinstance(p, dict):
        return p
    if not p.get("scenario"):
        tool = p.get("tool")
        cand = None
        if isinstance(tool, dict) and tool.get("scenario"):
            cand = tool.get("scenario")
        elif p.get("tool.scenario"):
            cand = p.get("tool.scenario")
        else:
            for k in ("mode", "action", "task"):
                if p.get(k) in SUPPORTED_SCENARIOS:
                    cand = p.get(k)
                    break
        if isinstance(cand, str) and cand:
            p = dict(p)
            p["scenario"] = cand
            p.pop("tool.scenario", None)
            if isinstance(tool, dict) and set(tool) <= {"scenario", "name"}:
                p.pop("tool", None)
            print(f"[run.py] normalized scenario alias -> {cand!r}", flush=True)
    for k in _OBJECT_PARAMS:
        v = p.get(k)
        if isinstance(v, str):
            s = v.strip()
            try:
                if s.startswith("{"):
                    p[k] = _j.loads(s)
                    print(f"[run.py] parsed JSON-string {k} into an object", flush=True)
                elif s.lower().endswith(".json") and _o.path.isfile(s):
                    with open(s, encoding="utf-8-sig") as _fh:
                        p[k] = _j.load(_fh)
                    print(f"[run.py] loaded {k} object from {s}", flush=True)
            except Exception as _e:
                print(f"[run.py] could not coerce {k} to an object: {_e}", flush=True)
    return p
# --- tool-call contract normalization (rec-1) --- end


TOOL = "physical-integrity-checker"


def _clean(value):
    value = html.unescape(value)
    return (value.replace("\u201c", '"').replace("\u201d", '"')
            .replace("\u2018", "'").replace("\u2019", "'"))


def _file_params():
    for path in ("/input/input.json", "/input/params.json", "/input/parameters.json", "/input/tool_input.json"):
        try:
            with open(path, encoding="utf-8") as stream:
                value = json.load(stream)
            if isinstance(value, dict) and "scenario" in value:
                return value
        except (OSError, ValueError):
            pass
    return None


def execute(params):
    import physical_integrity_checker_utils as utils
    utils.quick_setup()
    try:
        result = utils.dispatch(params)
    except Exception as exc:  # last-resort fail closure
        result = utils.failure_envelope("Physical integrity check", str(exc), params,
                                        traceback.format_exc())
    utils.save_final_results(result)
    with open(os.path.join(utils.OUTPUT, "common_design_envelope.json"),
              encoding="utf-8") as stream:
        envelope = json.load(stream)
    print("CDE_JSON=" + json.dumps(envelope, ensure_ascii=False), flush=True)
    verdict = (envelope.get("validation") or {}).get("verdict")
    return 0 if envelope.get("status") == "completed" and verdict not in (
        "fail", "not_assessable", "blocked") else 1


def main():
    params = None
    if len(sys.argv) > 1:
        try:
            candidate = _normalize_params(json.loads(_clean(sys.argv[1])))
            if isinstance(candidate, dict) and "scenario" in candidate:
                params = candidate
        except ValueError:
            pass
    params = params or _file_params()
    if params is None:
        params = {"scenario": None}
        params["_parse_error"] = _SCENARIO_HINT + "No usable JSON parameters with a scenario were supplied"
    raise SystemExit(execute(params))


if __name__ == "__main__":
    main()
