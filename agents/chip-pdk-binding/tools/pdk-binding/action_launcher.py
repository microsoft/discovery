"""Preserve native worker exits and expose persisted envelopes in Services logs."""
import json
import os
import re
import runpy
import sys

sys.path.insert(0, "/app")
import pdk_binding_utils as _binding_utils


def _magic_density_window_size(active_text, step, span):
    """Account for the checker's prorated tenth row and column."""
    totals = set(re.findall(
        r"atotal\s*=\s*([0-9.]+)\s*\+\s*([0-9.]+)\s*\*\s*locxfrac"
        r"\s*\+\s*([0-9.]+)\s*\*\s*locyfrac"
        r"\s*\+\s*locxfrac\s*\*\s*locyfrac", active_text))
    if len(totals) != 1:
        return None
    base, edge_x, edge_y = map(float, next(iter(totals)))
    if base != span * span or edge_x != span or edge_y != span:
        return None
    return step * (span + 1)


_original_density_parser = _binding_utils._parse_magic_density_rules


def _parse_pinned_density_rules(path):
    result = _original_density_parser(path)
    if result is None:
        return None
    with open(path, encoding="utf-8", errors="ignore") as source:
        active = "\n".join(line for line in source.read().splitlines()
                           if not line.lstrip().startswith("#"))
    steps = set(re.findall(r"box size\s+([0-9.]+)um\s+\1um", active))
    spans = set(re.findall(r"for w in range\(y,\s*y \+ ([0-9]+)\)", active))
    if len(steps) != 1 or len(spans) != 1:
        return None
    window = _magic_density_window_size(active, float(next(iter(steps))), int(next(iter(spans))))
    if window is None:
        return None
    result["window_um"].update(width=window, height=window)
    return result


_binding_utils._parse_magic_density_rules = _parse_pinned_density_rules
print("SOURCE_PATCH_JSON=" + json.dumps({
    "patch": "magic_density_prorated_tenth_tile", "applied": True,
    "original_module": _binding_utils.__file__,
    "deployment": "source-backed registered launcher; immutable worker image unchanged"}), flush=True)
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

