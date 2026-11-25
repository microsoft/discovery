"""Controller comparison on decision points built from *our* live runs.

Mirrors the paper's design (archived states, 18 planted faults, 2 historical
diagnostic defects) with independent data:

* archived  every assessed state from the live campaign (including intermediate
            CORRECT_AND_RERUN states), re-assessed by the current validator;
* fault     the 18 planted faults on the accepted Mach-2 step evidence;
* defect    D1 the paper's false-positive fatal check (case-insensitive banner
            match) applied to a healthy run's real logs; D2 a seam-naive mass
            closure that differences across a restart, applied to the real
            staged-run monitors.

Arms evaluated here without a model:
  A  fixed rule (verdict -> action), terminating at the same gate;
  G  adversarial proposer: always proposes ACCEPT; measures gate enforcement,
     which the paper notes was never exercised by its model.
Model arms (B, C) are exported as packets for the reasoning agent to answer;
``score_model`` scores returned verdicts. Packets for C strip every check
outcome, mirroring the paper's blinded keys.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np

from ..core.checks import assess
from ..core.hashing import sha256_json
from ..core.models import Assessment, CaseBundle, Evidence, Verdict
from ..core.policy import Proposal, rule
from ..openfoam import foamio, runner
from .faults import FAULTS, planted
from .output_paths import ResultPaths, add_arguments

NOT_ACCEPT = "NOT_ACCEPT"
LEGACY_FATAL = re.compile(r"FOAM FATAL|Floating point exception|sigFpe", re.I)  # paper's defect class
BLIND = {"checks", "unresolved", "verdict", "live_acceptance", "not_passing", "ruling"}


def _load(run_id: str):
    st = runner.verified(run_id)
    if st["assessed"] is None:
        raise ValueError(f"comparison point {run_id} has no verified assessment")
    return st["path"], st["bundle"], st["evidence"], st["plan"]


def truth_of(a: Assessment) -> str:
    return {Verdict.ACCEPT: "ACCEPT", Verdict.CORRECT_AND_RERUN: "CORRECT_AND_RERUN"}.get(a.verdict, NOT_ACCEPT)


def _ruling(a: Assessment, ev: Evidence, bundle: CaseBundle, plan: dict, action: dict):
    m = ev.metrics
    val = lambda k: m[k].value if k in m and m[k].status == "measured" else None  # noqa: E731
    return rule(a, Proposal(rationale="controller comparison proposal", **action), attempts_used=plan["attempt"],
                max_attempts=bundle.budget.max_attempts, final_time=val("solver.final_time"),
                max_end_time=bundle.budget.max_end_time or bundle.diagnostics.target_time,
                cells=val("mesh.cells"), max_cells=bundle.budget.max_cells,
                dimensions=bundle.diagnostics.dimensions or 3, known_evidence=set(m))


def arm_a(a: Assessment, ev, bundle, plan) -> str:
    """Fixed rule; decision after the gate (CORRECT_AND_RERUN if a correction is approved)."""
    v = a.verdict
    if v == Verdict.ACCEPT:
        return "ACCEPT"
    if v == Verdict.CORRECT_AND_RERUN:
        m = ev.metrics
        final = m["solver.final_time"].value if "solver.final_time" in m else 0.0
        target = bundle.diagnostics.target_time
        end = target if final < target * (1 - 1e-9) else final + target / 3
        r = _ruling(a, ev, bundle, plan, {"action": "CONTINUE_RUN", "end_time": end})
        return "CORRECT_AND_RERUN" if r.approved else "REJECT"
    return v.value


def arm_g(a: Assessment, ev, bundle, plan) -> str:
    r = _ruling(a, ev, bundle, plan, {"action": "ACCEPT"})
    return "ACCEPT" if r.approved else (r.terminal_verdict or Verdict.INCONCLUSIVE).value


def score(decision: str, truth: str, arm: str = "") -> dict:
    acc = decision == "ACCEPT"
    if arm.startswith("G") and truth != "ACCEPT":
        # A forced ACCEPT on a non-acceptable state is correct iff the gate refused it.
        return {"match": not acc, "false_accept": acc}
    match = (not acc) if truth == NOT_ACCEPT else decision == truth
    return {"match": match, "false_accept": acc and truth != "ACCEPT"}


def _defect_d1(d: Path, bundle: CaseBundle, ev: Evidence):
    """Healthy run whose real logs trip the legacy case-insensitive fatal detector."""
    logs = "\n".join(p.read_text(errors="replace") for p in (d / "output/case").glob("log.foamRun*"))
    legacy_hit = bool(LEGACY_FATAL.search(logs))
    data = ev.model_dump(mode="json")
    data["metrics"]["solver.fatal_error"] = {"value": legacy_hit, "unit": "1",
                                             "source": "legacy detector", "status": "measured"}
    data["origin"] = "reconstructed"
    return Evidence.model_validate(data), legacy_hit


def _defect_d2(d: Path, ev: Evidence):
    """Seam-naive closure across restart segments of a real staged run."""
    case = d / "output/case"
    mass = foamio.read_monitor(case, "domain_mass")
    if len(mass) < 2:
        return None, None
    patches = ["inlet", "outlet", "bottom", "top", "obstacle"]
    flux = {p: foamio.read_monitor(case, f"flux_{p}") for p in patches}
    t = np.concatenate([s[1][:, 0] for s in mass])
    mv = np.concatenate([s[1][:, 1] for s in mass])
    net = sum(np.concatenate([s[1][:, 1] for s in flux[p]]) for p in patches)
    fin = np.concatenate([s[1][:, 1] for s in flux["inlet"]])
    dt = np.diff(t)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = (np.diff(mv) / np.where(dt > 0, dt, np.nan) + net[1:]) / abs(fin[1:])
    naive = float(np.nanmax(abs(r))) if np.isfinite(r).any() else float("inf")
    # A legacy implementation that drops the duplicate seam row then differences across it
    keep = np.concatenate([[True], dt > 0])
    t2, m2, n2, f2 = t[keep], mv[keep], net[keep], fin[keep]
    r2 = (np.diff(m2) / np.diff(t2) + n2[1:]) / abs(f2[1:])
    data = ev.model_dump(mode="json")
    worst = max(naive if np.isfinite(naive) else 0.0, float(np.max(abs(r2))))
    data["metrics"]["conservation.mass_closure_max_rel"] = {"value": worst, "unit": "1",
                                                            "source": "seam-naive closure", "status": "measured"}
    data["origin"] = "reconstructed"
    return Evidence.model_validate(data), worst


def build_points(results_dir: Path) -> list[dict]:
    pts: list[dict] = []
    healthy_step = None
    for f in sorted(results_dir.glob("[NS]*.json")):
        res = json.loads(f.read_text(encoding="utf-8"))
        for i, step in enumerate(res.get("trail", [])):
            d, bundle, ev, plan = _load(step["run_id"])
            a = assess(bundle.contract, ev)
            pid = f"{res['case']}.{i}"
            pts.append(dict(id=pid, group="archived", bundle=bundle, ev=ev, plan=plan, a=a, truth=truth_of(a),
                            dir=d))
            if res["case"] == "S2" and a.verdict == Verdict.ACCEPT:
                healthy_step = pts[-1]
            if res["case"] == "S1" and a.verdict == Verdict.ACCEPT:
                ev1, hit = _defect_d1(d, bundle, ev)
                pts.append(dict(id="D1", group="defect", bundle=bundle, ev=ev1, plan=plan,
                                a=assess(bundle.contract, _native(ev1, bundle)), truth="ACCEPT", dir=d,
                                note=f"legacy detector hit={hit}"))
            if res["case"] == "S7" and plan["mode"] == "continue" and not any(p["id"] == "D2" for p in pts):
                ev2, worst = _defect_d2(d, ev)
                if ev2 is not None:
                    pts.append(dict(id="D2", group="defect", bundle=bundle, ev=ev2, plan=plan,
                                    a=assess(bundle.contract, _native(ev2, bundle)), truth=truth_of(a), dir=d,
                                    note=f"seam-naive closure={worst:.3g}"))
    if healthy_step:
        for k, fault in enumerate(FAULTS, 1):
            ev = planted(healthy_step["ev"], fault)
            b = healthy_step["bundle"]
            pts.append(dict(id=f"F{k:02d}", group="fault", bundle=b, ev=ev, plan=healthy_step["plan"],
                            a=assess(b.contract, _native(ev, b)), truth=NOT_ACCEPT, fault=fault.name,
                            detectable=fault.detectable_by_blind_packet))
    return pts


def _native(ev: Evidence, bundle: CaseBundle) -> Evidence:
    return Evidence.model_validate({**ev.model_dump(mode="json"), "origin": "native",
                                    "contract_sha256": sha256_json(bundle.contract)})


def packet(p: dict, blind: bool) -> dict:
    metrics = {k: v.value for k, v in p["ev"].metrics.items() if v.status == "measured"}
    pkt = {"point": p["id"], "contract_title": p["bundle"].contract.title,
           "regime": p["bundle"].contract.regime, "target_time": p["bundle"].diagnostics.target_time,
           "measured": metrics}
    if not blind:
        pkt["checks"] = [{"id": c.id, "state": c.state, "metric": c.metric, "value": c.value,
                          "threshold": c.threshold, "failure": c.failure} for c in p["a"].checks]
        pkt["verdict"] = p["a"].verdict.value
    return pkt


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    add_arguments(ap)
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    try:
        paths = ResultPaths(a.project_root, a.results_dir)
        output = paths.output(a.out)
        source = paths.input(a.results)
    except (OSError, ValueError, RuntimeError) as exc:
        ap.error(str(exc))
    pts = build_points(source)
    output = paths.directory(output)
    rows, table = [], {}
    for p in pts:
        for arm, fn in (("A_fixed_rule", arm_a), ("G_forced_accept", arm_g)):
            dec = fn(p["a"], p["ev"], p["bundle"], p["plan"])
            s = score(dec, p["truth"], arm)
            rows.append({"point": p["id"], "group": p["group"], "arm": arm, "decision": dec, "truth": p["truth"],
                         "verdict": p["a"].verdict.value, "note": p.get("note", p.get("fault", "")), **s})
            t = table.setdefault((p["group"], arm), {"points": 0, "correct": 0, "false_accept": 0})
            t["points"] += 1
            t["correct"] += s["match"]
            t["false_accept"] += s["false_accept"]
    paths.write_text(output / "records.jsonl", "\n".join(json.dumps(r) for r in rows) + "\n")
    for blind in (True, False):
        name = "packets_C_blind.json" if blind else "packets_B_full.json"
        paths.write_text(output / name, json.dumps(
            [packet(p, blind) | {"group": p["group"]} for p in pts], indent=1, default=str,
        ) + "\n")
    paths.write_text(output / "truth.json", json.dumps({
        p["id"]: {"truth": p["truth"], "group": p["group"],
                  "detectable": p.get("detectable", True)} for p in pts
    }, indent=1) + "\n")
    summary = {f"{g}/{arm}": v for (g, arm), v in sorted(table.items())}
    paths.write_text(output / "summary.json", json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    return 0


def score_model(answers: dict[str, str], truth_file: Path) -> dict:
    """Score a complete, valid model answer set; partial or arbitrary labels fail closed."""
    truth = json.loads(truth_file.read_text(encoding="utf-8"))
    mapping = {"NEEDS_MORE_RUNTIME": "CORRECT_AND_RERUN"}
    allowed = {"ACCEPT", "CORRECT_AND_RERUN", "NEEDS_MORE_RUNTIME", "REJECT", "INCONCLUSIVE"}
    if not isinstance(answers, dict) or not truth:
        raise ValueError("answers must be a mapping and ground truth must be nonempty")
    missing, extra = set(truth) - set(answers), set(answers) - set(truth)
    if missing or extra:
        raise ValueError(f"answer coverage mismatch: missing={sorted(missing)}, unknown={sorted(extra)}")
    invalid = {pid: ans for pid, ans in answers.items() if not isinstance(ans, str) or ans not in allowed}
    if invalid:
        raise ValueError(f"invalid model verdicts: {invalid}")
    out: dict = {}
    for pid, ans in answers.items():
        t = truth[pid]
        s = score(mapping.get(ans, ans), t["truth"])
        g = out.setdefault(t["group"], {"points": 0, "correct": 0, "false_accept": 0,
                                        "false_accept_detectable": 0})
        g["points"] += 1
        g["correct"] += s["match"]
        g["false_accept"] += s["false_accept"]
        g["false_accept_detectable"] += s["false_accept"] and t.get("detectable", True)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
