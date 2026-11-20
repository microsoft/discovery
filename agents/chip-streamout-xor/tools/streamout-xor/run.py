#!/usr/bin/env python3
"""Fail-closed entrypoint for streamout-xor.

Always logs to stdout (and /output/logs/run.log), so a failed run never shows
"<no logs found>": the final status, verdict and error are printed even when the
envelope is a fail-closed one."""
import html
import json
import os
import sys
import traceback

# --- tool-call contract normalization (rec-1) ---
SUPPORTED_SCENARIOS = ['xor_gds', 'dual_streamout_xor']
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


TOOL = "streamout-xor"
SCENARIOS = ("xor_gds", "dual_streamout_xor")
_LOG_LINES = []


def log(message):
    line = "[run.py:%s] %s" % (TOOL, message)
    _LOG_LINES.append(line)
    print(line, flush=True)


def _flush_log_file():
    try:
        import streamout_xor_utils as utils
        os.makedirs(os.path.join(utils.OUTPUT, "logs"), exist_ok=True)
        with open(os.path.join(utils.OUTPUT, "logs", "run.log"), "a", encoding="utf-8") as stream:
            stream.write("\n".join(_LOG_LINES) + "\n")
    except Exception as exc:
        print("[run.py:%s] run.log not written: %s" % (TOOL, exc), flush=True)


def _clean(value):
    value = html.unescape(value)
    return (value.replace("\u201c", '"').replace("\u201d", '"')
            .replace("\u2018", "'").replace("\u2019", "'"))


def _scenario_of(params):
    try:
        import streamout_xor_utils as utils
        return utils.resolve_scenario(params)
    except Exception:
        return (params.get("scenario"), "scenario") if isinstance(params, dict) else (None, None)


def _file_params():
    for path in ("/input/input.json", "/input/params.json", "/input/parameters.json", "/input/tool_input.json"):
        try:
            with open(path, encoding="utf-8") as stream:
                value = json.load(stream)
        except (OSError, ValueError):
            continue
        if isinstance(value, dict):
            log("params read from " + path)
            return value
    return None


def execute(params):
    import streamout_xor_utils as utils
    utils.quick_setup()
    scenario, source = _scenario_of(params)
    log("scenario=%r (from %s); param keys: %s" % (
        scenario, source or "none", ", ".join(sorted(k for k in params if k != "pdk_binding"))))
    if not scenario:
        log("no scenario supplied; supported scenarios: " + ", ".join(SCENARIOS))
    try:
        result = utils.dispatch(params)
    except Exception as exc:
        log("dispatch raised: %s" % exc)
        print(traceback.format_exc(), flush=True)
        result = utils.failure_envelope("Layout streamout XOR", str(exc), params,
                                        traceback.format_exc())
    validation = result.get("validation") or {}
    log("status=%s verdict=%s" % (result.get("status"), validation.get("verdict")))
    if validation.get("mode"):
        log("mode: " + str(validation["mode"]))
    error = result.get("error") or (result.get("signoff_evidence") or {}).get("failure_reason")
    if error:
        log("error: " + str(error)[:4000])
    try:
        utils.save_final_results(result)
        log("wrote " + os.path.join(utils.OUTPUT, "common_design_envelope.json"))
        with open(os.path.join(utils.OUTPUT, "common_design_envelope.json"),
                  encoding="utf-8") as stream:
            envelope = json.load(stream)
        print("CDE_JSON=" + json.dumps(envelope, ensure_ascii=False), flush=True)
    except Exception as exc:
        log("save_final_results failed: %s" % exc)
        print(traceback.format_exc(), flush=True)
        _flush_log_file()
        return 1
    _flush_log_file()
    verdict = (envelope.get("validation") or {}).get("verdict")
    return 0 if envelope.get("status") == "completed" and verdict not in (
        "fail", "not_assessable", "blocked") else 1


def main():
    log("=== CHIP STREAMOUT-XOR RUN.PY STARTING ===")
    params = None
    parse_error = None
    if len(sys.argv) > 1:
        try:
            candidate = _normalize_params(json.loads(_clean(sys.argv[1])))
            if isinstance(candidate, dict):
                params = candidate
            else:
                parse_error = "argv[1] JSON is not an object"
        except ValueError as exc:
            parse_error = "argv[1] JSON parse failed: %s" % exc
        if parse_error:
            log(parse_error)
    if params is None or not _scenario_of(params)[0]:
        file_params = _file_params()
        if file_params is not None and (params is None or _scenario_of(file_params)[0]):
            params = file_params
    if params is None:
        params = {"scenario": None,
                  "_parse_error": parse_error or "no JSON parameters on argv[1] or in /input/*.json"}
    raise SystemExit(execute(params))


if __name__ == "__main__":
    main()
