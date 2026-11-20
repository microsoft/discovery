"""Preserve native worker exits and expose persisted envelopes in Services logs."""
import json
import os
import runpy
import sys

sys.path.insert(0, "/app")
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
                verdict = envelope.get("validation", {}).get("verdict")
                domain_failed = (envelope.get("status") != "completed" or
                                 verdict not in ("pass", "pass_with_caveats", "review"))
                print("CDE_JSON=" + json.dumps(envelope, separators=(",", ":")), flush=True)
            break
effective_exit = native_exit or int(domain_failed)
print("SERVICES_EXIT_JSON=" + json.dumps({"worker_exit": native_exit, "effective_exit": effective_exit}), flush=True)
sys.exit(effective_exit)

