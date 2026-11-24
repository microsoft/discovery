"""Cloud (Discovery container action) entry point: one call runs a whole bounded evaluation.

Inside the platform container there is no nested container runtime, so the worker
runs as a local subprocess (DISCOVERY_PHYSICS_IN_CONTAINER=1) and the platform
enforces CPU/memory. The agent cannot touch the container filesystem during the
job, so the journal, evidence, and verdict are produced without agent access.
Corrections inside a cloud call follow the deterministic fixed rule (continue to
the frozen horizon); a model-proposed rebuild is a new call with a new bundle.

    python -m discovery_physics.service evaluate --bundle-b64gz <...> [--confirmations-json <...>]
    python -m discovery_physics.service study --spec-b64gz <...>
    python -m discovery_physics.service lint --bundle-b64gz <...>
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import sys
from pathlib import Path

OUTPUT = Path(os.environ.get("DISCOVERY_PHYSICS_OUTPUT", "/output"))


def _decode(b64gz: str | None, raw: str | None) -> dict:
    if b64gz:
        return json.loads(gzip.decompress(base64.b64decode(b64gz, validate=True)).decode("utf-8"))
    if raw:
        return json.loads(raw)
    raise SystemExit("a bundle/spec is required")


def _fixed_rule(s: dict, target: float, max_end: float) -> dict:
    v = s["verdict"]
    if v == "ACCEPT":
        return {"action": "ACCEPT", "rationale": "All registered checks pass (deterministic cloud rule)."}
    if v == "CORRECT_AND_RERUN":
        final = (s["metrics"].get("solver.final_time") or [0.0])[0]
        end = target if final < target * (1 - 1e-9) else min(max_end, final + target / 3)
        return {"action": "CONTINUE_RUN", "end_time": end,
                "rationale": "Healthy but incomplete: continue to the frozen horizon (deterministic cloud rule)."}
    return {"action": "FAIL_SAFELY", "rationale": f"Verdict {v}; stop and preserve evidence (cloud rule)."}


def evaluate(bundle: dict, confirmations: list[dict] | None = None) -> dict:
    from .openfoam import runner

    prep = runner.prepare(bundle)
    run_id = prep["run_id"]
    if confirmations:
        runner.confirm(run_id, confirmations)
    final, trail, run_id = _drive(run_id, bundle)
    return {"prepared": prep, "trail": trail, "final": final, "summary": runner.summary(run_id),
            "integrity": runner.verify(run_id)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="discovery-physics-service")
    ap.add_argument("action", choices=["evaluate", "study", "lint", "capabilities"])
    ap.add_argument("--bundle-b64gz")
    ap.add_argument("--bundle-json")
    ap.add_argument("--spec-b64gz")
    ap.add_argument("--confirmations-b64")
    a = ap.parse_args(argv)
    os.environ.setdefault("DISCOVERY_PHYSICS_IN_CONTAINER", "1")
    os.environ.setdefault("DISCOVERY_PHYSICS_RUNS", str(OUTPUT / "runs"))
    os.environ.setdefault("DISCOVERY_PHYSICS_KEY_FILE", "/tmp/discovery-physics/journal.key")
    os.environ.setdefault("LOCALAPPDATA", "/tmp")
    from .openfoam import runner

    try:
        if a.action == "capabilities":
            out = runner.capabilities()
        elif a.action == "lint":
            out = runner.lint_bundle(_decode(a.bundle_b64gz, a.bundle_json))
        elif a.action == "evaluate":
            conf = json.loads(base64.b64decode(a.confirmations_b64, validate=True)) if a.confirmations_b64 else None
            out = evaluate(_decode(a.bundle_b64gz, a.bundle_json), conf)
        else:
            from .openfoam import study

            spec = _decode(a.spec_b64gz, None)
            prepared = study.prepare(spec)
            members = {}
            for m in spec["members"]:
                rid = prepared["members"][m["name"]]
                # Each member was staged by study.prepare; drive its lineage with the cloud rule.
                members[m["name"]] = _drive(rid, m["bundle"])[0]
            out = {"study": study.assess(prepared["study_id"]), "members": members}
        status = 0
    except Exception as exc:  # report refusals as data, not stack traces
        out = {"error": type(exc).__name__, "detail": str(exc)[:4000]}
        status = 2
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "result.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, indent=1, default=str))
    return status


def _drive(run_id: str, bundle: dict) -> tuple[dict, list[dict], str]:
    from .openfoam import runner

    target = bundle["diagnostics"]["target_time"]
    max_end = (bundle.get("budget") or {}).get("max_end_time") or target
    trail = []
    while True:
        s = runner.execute(run_id)
        proposal = _fixed_rule(s, target, max_end)
        r = runner.propose(run_id, proposal)
        trail.append({"run_id": run_id, "verdict": s["verdict"], "action": proposal["action"],
                      "approved": r["approved"], "reasons": r["reasons"]})
        if not r.get("child_run_id"):
            break
        run_id = r["child_run_id"]
    return runner.finalize(run_id), trail, run_id


if __name__ == "__main__":
    sys.exit(main())
