#!/usr/bin/env python3
"""Fail-closed command wrapper for the OpenDB Utilities tool."""
import html
import json
import os
import sys
import traceback

# --- tool-call contract normalization (rec-1) ---
SUPPORTED_SCENARIOS = ['convert_def_to_odb', 'report_wire_length', 'write_views']
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


TOOL = "opendb-utilities"


def log(message):
    print(f"[run.py:{TOOL}] {message}", flush=True)


def _clean(value):
    return (html.unescape(value).replace("\u201c", '"').replace("\u201d", '"')
            .replace("\u2018", "'").replace("\u2019", "'"))


def _file_params():
    for path in ("/input/input.json", "/input/params.json",
                 "/input/parameters.json", "/input/tool_input.json"):
        try:
            with open(path, encoding="utf-8") as stream:
                value = json.load(stream)
            if isinstance(value, dict) and value.get("scenario"):
                return value
        except FileNotFoundError:
            continue
        except Exception as exc:
            log(f"could not read {path}: {exc}")
    return None


def _authoritative_exit_code(path=None):
    path = path or os.path.join(os.environ.get("CHIP_OUTPUT_DIR", "/output"),
                                "common_design_envelope.json")
    try:
        with open(path, encoding="utf-8") as stream:
            envelope = json.load(stream)
        print("CDE_JSON=" + json.dumps(envelope, ensure_ascii=False), flush=True)
        verdict = envelope.get("validation", {}).get("verdict")
        return 0 if (envelope.get("status") == "completed" and
                     verdict in ("pass", "pass_with_caveats", "review")) else 1
    except Exception:
        return 1


def _run(params):
    import opendb_utilities_utils as utils
    utils.quick_setup()
    try:
        result = utils.dispatch(params)
    except Exception as exc:
        result = utils.failed_envelope(
            str(params.get("scenario", "unknown")), str(exc), params,
            traceback.format_exc())
    utils.save_final_results(result)
    return _authoritative_exit_code()


def _fail(message, params=None):
    try:
        import opendb_utilities_utils as utils
        utils.quick_setup()
        result = utils.failed_envelope("dispatch", message, params or {})
        utils.save_final_results(result)
    except Exception:
        os.makedirs(os.environ.get("CHIP_OUTPUT_DIR", "/output"), exist_ok=True)
        path = os.path.join(os.environ.get("CHIP_OUTPUT_DIR", "/output"),
                            "common_design_envelope.json")
        with open(path, "w", encoding="utf-8") as stream:
            json.dump({"tool": TOOL, "status": "failed", "error": message,
                       "validation": {"verdict": "fail", "note": message}},
                      stream, indent=2)
    _authoritative_exit_code()
    log("FAIL-CLOSED: " + message)
    return 1


def main():
    params = None
    if len(sys.argv) > 1:
        raw = _clean(sys.argv[1].strip())
        if raw.startswith("{"):
            try:
                params = _normalize_params(json.loads(raw))
            except json.JSONDecodeError as exc:
                return _fail(f"invalid params JSON: {exc}")
    params = params or _file_params()
    if not isinstance(params, dict) or not params.get("scenario"):
        return _fail(_SCENARIO_HINT + "no usable parameter object with a non-empty scenario")
    return _run(params)


if __name__ == "__main__":
    sys.exit(main())
