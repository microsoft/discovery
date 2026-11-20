"""Preserve native worker exits and expose persisted envelopes in Services logs."""
import json
import os
import runpy
import sys

sys.path.insert(0, "/app")
import drc_utils as _drc_utils


def _log_engine_result(worker):
    def wrapped(*args, **kwargs):
        result = worker(*args, **kwargs)
        print("ENGINE_RUN_JSON=" + json.dumps(result, separators=(",", ":")), flush=True)
        report = result.get("report")
        if report and os.path.basename(report) == report:
            path = os.path.join(_drc_utils._OUTPUT_DIR, report)
            if os.path.isfile(path):
                with open(path, encoding="utf-8", errors="replace") as source:
                    text = source.read()
                print("ENGINE_LOG_JSON=" + json.dumps({
                    "engine": result.get("engine"), "path": path,
                    "contents": text[-5000:], "truncated": len(text) > 5000}), flush=True)
        return result
    return wrapped


_drc_utils._run_klayout_drc = _log_engine_result(_drc_utils._run_klayout_drc)
_drc_utils._run_magic_drc = _log_engine_result(_drc_utils._run_magic_drc)
print("SOURCE_PATCH_JSON=" + json.dumps({
    "patch": "preserve_actual_per_engine_drc_evidence", "applied": True,
    "deployment": "source-backed launcher; native CDE, worker image and engine results unchanged"}), flush=True)
native_exit = 0
domain_failed = True
try:
    runpy.run_path("/app/run.py", run_name="__main__")
except SystemExit as exc:
    native_exit = exc.code if isinstance(exc.code, int) else int(bool(exc.code))
finally:
    for path in ("/output/common_design_envelope.json", "/output/final_results.json"):
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as stream:
                envelope = json.load(stream)
                domain_failed = (envelope.get("status") != "completed" or
                                 envelope.get("validation", {}).get("verdict") in ("fail", "not_assessable"))
                print("CDE_JSON=" + json.dumps(envelope, separators=(",", ":")), flush=True)
            break
effective_exit = native_exit or int(domain_failed)
print("SERVICES_EXIT_JSON=" + json.dumps({"worker_exit": native_exit, "effective_exit": effective_exit}), flush=True)
sys.exit(effective_exit)
