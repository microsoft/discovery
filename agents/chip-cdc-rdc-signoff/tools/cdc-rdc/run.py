#!/usr/bin/env python3
"""run.py -- entrypoint wrapper for the Discovery chip tool 'cdc-rdc'.

PARAMS MODE: single-line JSON via sys.argv[1]. FILE MODE: /input/*.json with a
'scenario' key. Results always written to /output/final_results.json (Common
Design Envelope), even on error.
"""
import html, json, os, sys, traceback

# --- tool-call contract normalization (rec-1) ---
SUPPORTED_SCENARIOS = ['cdc_signoff', 'rdc_signoff', 'synchronizer_verify', 'reconvergence']
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


TOOL = "cdc-rdc"


def log(msg):
    print(f"[run.py:{TOOL}] {msg}", flush=True)


def _clean_arg(arg):
    arg = html.unescape(arg)
    return (arg.replace("\u201c", '"').replace("\u201d", '"')
               .replace("\u2018", "'").replace("\u2019", "'"))


def _find_params_file():
    for path in ("/input/input.json", "/input/params.json",
                 "/input/parameters.json", "/input/tool_input.json"):
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = _normalize_params(json.load(f))
                if "scenario" in data:
                    return data
            except Exception as e:
                log(f"Error reading {path}: {e}")
    return None


def _authoritative_exit_code(path=None):
    # save_final_results writes common_design_envelope.json; older builds
    # wrote final_results.json. Read whichever exists so the exit code
    # reflects the REAL status (a missing file must never read as success).
    _candidates = ([path] if path else
                   ["/output/common_design_envelope.json", "/output/final_results.json"])
    for _p in _candidates:
        try:
            with open(_p, encoding="utf-8") as stream:
                result = json.load(stream)
            print("CDE_JSON=" + json.dumps(result, ensure_ascii=False), flush=True)
            return 0 if (result.get("status") == "completed" and
                         result.get("validation", {}).get("verdict") in
                         ("pass", "pass_with_caveats", "review")) else 1
        except Exception:
            continue
    return 1


def run_from_params(params):
    import cdc_rdc_utils as utils
    utils.quick_setup(output_dir="/output", work_dir="/workdir")
    results = {}
    try:
        results = utils.dispatch(params)
    except Exception as e:
        results = {"tool": TOOL, "status": "failed", "error": str(e),
                   "validation": {"verdict": "fail", "note": str(e)},
                   "traceback": traceback.format_exc(),
                   "input_parameters": dict(params)}
    finally:
        utils.save_final_results(results)
    return _authoritative_exit_code()


def _fail_closed(error, params=None):
    """Always emit a well-formed failed CDE, then exit non-zero.

    Fail-closed contract: a bad or absent argument must never crash the container
    without leaving `/output/final_results.json` (status=failed, verdict=fail,
    non-empty error). Routes through the tool's save_final_results when possible
    (so the results/reports/logs split + SUMMARY are still produced) and falls
    back to a direct minimal write if the utils module itself cannot load."""
    results = {
        "tool": TOOL, "status": "failed",
        "validation": {"verdict": "fail", "note": error},
        "error": error,
    }
    if params is not None:
        results["input_parameters"] = (
            params if isinstance(params, dict) else {"raw": str(params)})
    try:
        import cdc_rdc_utils as utils
        utils.quick_setup(output_dir="/output", work_dir="/workdir")
        utils.save_final_results(results)
    except Exception as _e:
        try:
            os.makedirs("/output", exist_ok=True)
            with open("/output/final_results.json", "w", encoding="utf-8") as _f:
                json.dump(results, _f, indent=2, default=str)
        except Exception:
            pass
    log("FAIL-CLOSED: " + str(error))
    sys.exit(1)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--params-file":
        from pathlib import Path
        path = Path(sys.argv[2]).resolve()
        try:
            if not path.is_relative_to(Path("/input").resolve()):
                raise ValueError("parameter file must stay under /input")
            with path.open(encoding="utf-8-sig") as stream:
                params = json.load(stream)
            if not isinstance(params, dict) or params.get("scenario") not in SUPPORTED_SCENARIOS:
                raise ValueError(_SCENARIO_HINT)
        except (OSError, ValueError) as exc:
            _fail_closed(str(exc))
        sys.exit(run_from_params(params))
    log("=== CHIP CDC-RDC RUN.PY STARTING ===")
    if len(sys.argv) > 1:
        arg = _clean_arg(sys.argv[1].strip())
        if arg.startswith("{"):
            try:
                params = _normalize_params(json.loads(arg))
                if "scenario" in params:
                    sys.exit(run_from_params(params))
            except json.JSONDecodeError as e:
                log(f"argv[1] JSON parse failed: {e}")
    data = _find_params_file()
    if data is not None:
        sys.exit(run_from_params(data))
    _fail_closed(_SCENARIO_HINT + "No usable params: sys.argv[1] was missing, unparseable, "
                 "or lacked a 'scenario' key, and no /input/*.json params "
                 "file was found. Emitting a fail-closed CDE.")


if __name__ == "__main__":
    main()
