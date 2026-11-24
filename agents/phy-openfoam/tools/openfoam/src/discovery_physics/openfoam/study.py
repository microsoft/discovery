"""Studies: sweeps, mesh-refinement series, and design candidates across several runs.

A study freezes its cross-run criteria before any member runs. Each member is an
ordinary run with its own frozen contract; the study verdict is computed by code
from the members' verified, finalized evidence.
"""

from __future__ import annotations

import json
import math
import re
import time
import uuid
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..core import integrity
from ..core.design import quadratic_surrogate
from ..core.gci import gci
from ..core.hashing import sha256_json
from ..core.models import CaseBundle, Identifier, Number, Positive, Record, Verdict
from . import runner
from .catalog import N, known_metrics

_STUDY_ID = re.compile(r"^S[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")


class Member(Record):
    name: Identifier
    bundle: dict
    parameters: dict[str, Number] = Field(default_factory=dict, max_length=8)
    h: Positive | None = None  # representative cell size, refinement studies


class Criterion(Record):
    id: Identifier
    kind: Literal["all_accept", "gci", "monotonic", "range", "best"]
    metric: str | None = Field(default=None, max_length=128)
    max_gci_pct: Positive | None = None
    safety_factor: float = Field(default=1.25, ge=1.0, le=3.0)
    parameter: str | None = Field(default=None, max_length=64)
    direction: Literal["increasing", "decreasing"] | None = None
    bounds: list[Number] | None = None
    goal: Literal["minimize", "maximize"] | None = None
    uncertainty_pct: float = Field(default=0.0, ge=0, le=100, allow_inf_nan=False)
    uncertainty_from: Identifier | None = None  # a gci criterion whose GCI bounds every member
    min_accepted: int | None = Field(default=None, ge=1)  # all_accept: candidates may tolerate failures
    rationale: str = Field(min_length=8, max_length=2000)

    @model_validator(mode="after")
    def complete(self) -> Criterion:
        need = {"gci": ("metric", "max_gci_pct"), "monotonic": ("metric", "parameter", "direction"),
                "range": ("metric", "bounds"), "best": ("metric", "goal"), "all_accept": ()}[self.kind]
        missing = [k for k in need if getattr(self, k) is None]
        if missing:
            raise ValueError(f"{self.kind} criterion requires {missing}")
        if self.bounds is not None and (len(self.bounds) != 2 or not self.bounds[0] < self.bounds[1]):
            raise ValueError("bounds must be two increasing numbers")
        return self


class Study(Record):
    schema_version: Literal["1.0"] = "1.0"
    id: Identifier
    title: str = Field(min_length=5, max_length=256)
    requested_prompt: str = Field(min_length=5, max_length=32000)
    kind: Literal["sweep", "refinement", "candidates"]
    members: list[Member] = Field(min_length=2, max_length=32)
    criteria: list[Criterion] = Field(min_length=1, max_length=32)
    design_bounds: dict[str, list[Number]] = Field(default_factory=dict, max_length=6)

    @model_validator(mode="after")
    def consistent(self) -> Study:
        names = [m.name for m in self.members]
        if len(set(names)) != len(names):
            raise ValueError("member names must be unique")
        ids = [c.id for c in self.criteria]
        if len(set(ids)) != len(ids):
            raise ValueError("criterion ids must be unique")
        if not any(c.kind == "all_accept" for c in self.criteria):
            raise ValueError("a study must include an all_accept criterion")
        for c in self.criteria:
            if c.kind == "gci" and (sum(m.h is not None for m in self.members) < 3):
                raise ValueError("a gci criterion needs at least three members with h")
            if c.parameter and any(c.parameter not in m.parameters for m in self.members):
                raise ValueError(f"every member must set parameter {c.parameter!r}")
            if c.uncertainty_from and c.uncertainty_from not in {x.id for x in self.criteria if x.kind == "gci"}:
                raise ValueError("uncertainty_from must name a gci criterion")
        if self.kind == "refinement" and not any(c.kind == "gci" for c in self.criteria):
            raise ValueError("a refinement study needs a gci criterion")
        return self


def studies_root() -> Path:
    p = runner.runs_root().parent / "studies"
    p.mkdir(parents=True, exist_ok=True)
    return p


def study_dir(study_id: str) -> Path:
    if not _STUDY_ID.match(study_id):
        raise ValueError("invalid study id")
    p = studies_root() / study_id
    if not p.is_dir():
        raise FileNotFoundError(f"unknown study {study_id}")
    return p


def load_spec(path: Path) -> dict:
    """Read a study spec; members may give ``bundle_file`` relative to the spec."""
    data = json.loads(path.read_text(encoding="utf-8"))
    for m in data.get("members", []):
        if "bundle_file" in m:
            m["bundle"] = json.loads((path.parent / m.pop("bundle_file")).read_text(encoding="utf-8"))
    return data


def prepare(spec: dict) -> dict:
    study = Study.model_validate(spec)
    # Freeze every member before staging any, so one bad member stages nothing.
    bundles = {m.name: runner.freeze(m.bundle, study_member=True)[0] for m in study.members}
    for c in study.criteria:
        if c.kind != "all_accept":
            _metric_unit(c, bundles)
    sid = "S" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
    path = studies_root() / sid
    path.mkdir()
    members = {m.name: runner.prepare(m.bundle, study=sid)["run_id"] for m in study.members}
    (path / "study.json").write_text(json.dumps(study.model_dump(mode="json"), indent=1), encoding="utf-8")
    integrity.append(path, "prepared", study_sha256=integrity.file_sha256(path / "study.json"), members=members)
    return {"study_id": sid, "members": members, "criteria": [c.id for c in study.criteria],
            "next": "execute each member run (respecting the concurrency cap), propose/finalize each lineage, "
                    "then `discovery-physics study-assess <study_id>`"}


def _verified_study(study_id: str) -> tuple[Path, Study, dict]:
    path = study_dir(study_id)
    records = integrity.verify_journal(path)
    integrity.require_file(path / "study.json", records[0]["study_sha256"], "study.json")
    return path, Study.model_validate(json.loads((path / "study.json").read_text(encoding="utf-8"))), \
        records[0]["members"]


def _leaf(run_id: str) -> dict:
    """Follow a member's lineage to its newest run."""
    st = runner.verified(run_id)
    while st["children"]:
        st = runner.verified(st["children"][-1])
    return st


def status(study_id: str) -> dict:
    _, study, members = _verified_study(study_id)
    out = {}
    for name, rid in members.items():
        st = _leaf(rid)
        out[name] = {"root_run": rid, "leaf_run": st["plan"]["run_id"],
                     "final": st["final"]["final_verdict"] if st["final"] else None,
                     "verdict": st["assessment"].verdict.value if st["assessment"] else None,
                     "started": st["started"]}
    return {"study_id": study_id, "members": out}


def _metric_unit(criterion: Criterion, bundles: dict[str, CaseBundle]) -> str:
    """Bind a cross-run metric to the same explicit numeric unit in every member.

    Member diagnostics are already part of the frozen study, so no mutable
    sidecar or implicit conversion is needed. Bounds use this common unit.
    """
    units = {}
    for name, bundle in bundles.items():
        spec = known_metrics(bundle.diagnostics).get(criterion.metric)
        if spec is None or spec[0] != N:
            raise ValueError(f"criterion {criterion.id!r}: member {name!r} must declare "
                             f"numeric metric {criterion.metric!r}")
        unit = spec[1]
        if not unit.strip():
            raise ValueError(f"criterion {criterion.id!r}: member {name!r} has a blank metric unit")
        units[name] = unit
    if len(set(units.values())) != 1:
        raise ValueError(f"criterion {criterion.id!r}: metric unit mismatch across members: {units}")
    return next(iter(units.values()))


def _value(st: dict, metric: str, unit: str) -> float | None:
    m = st["evidence"].metrics.get(metric) if st["evidence"] else None
    if m is None or m.status != "measured" or m.unit != unit or \
            isinstance(m.value, bool) or not isinstance(m.value, (int, float)):
        return None
    return float(m.value) if math.isfinite(m.value) else None


def assess(study_id: str) -> dict:
    path, study, members = _verified_study(study_id)
    leaves = {m.name: _leaf(members[m.name]) for m in study.members}
    bundles = {m.name: CaseBundle.model_validate(m.bundle) for m in study.members}
    final = {n: (st["final"]["final_verdict"] if st["final"] else None) for n, st in leaves.items()}
    accepted = {n for n, v in final.items() if v == Verdict.ACCEPT.value and leaves[n]["final"]["live_acceptance"]}
    results: dict[str, dict] = {}
    checked_values: dict[str, dict[str, float]] = {}
    for c in study.criteria:
        r: dict = {"id": c.id, "kind": c.kind, "rationale": c.rationale}
        vals = {}
        if c.kind != "all_accept":
            try:
                unit = _metric_unit(c, bundles)
            except ValueError as exc:
                # Legacy studies must also fail closed instead of comparing
                # numbers from incompatible declarations or inventing units.
                r.update(state="UNKNOWN", detail={"issue": str(exc)})
                results[c.id] = r
                continue
            r["unit"] = unit
            required = accepted if c.kind == "best" else set(leaves)
            recorded_units = {}
            for name in sorted(required):
                ev = leaves[name]["evidence"]
                m = ev.metrics.get(c.metric) if ev else None
                if m is not None:
                    recorded_units[name] = m.unit
            if any(value != unit for value in recorded_units.values()):
                r.update(state="UNKNOWN", detail={"issue": "recorded metric unit mismatch",
                                                  "expected_unit": unit, "recorded_units": recorded_units})
                results[c.id] = r
                continue
            vals = {name: _value(st, c.metric, unit) for name, st in leaves.items()}
            missing = sorted(name for name in required if vals[name] is None)
            if missing:
                r.update(state="UNKNOWN", detail={"issue": "metric missing, invalid or non-finite",
                                                  "members": missing, "unit": unit})
                results[c.id] = r
                continue
            checked_values[c.id] = {name: value for name, value in vals.items()
                                    if name in accepted and value is not None}
        if c.kind == "all_accept":
            pending = [n for n, v in final.items() if v is None]
            failed = [n for n, v in final.items() if v is not None and n not in accepted]
            need = c.min_accepted or len(study.members)
            state = "PASS" if len(accepted) >= need else ("UNKNOWN" if len(accepted) + len(pending) >= need else "FAIL")
            r.update(state=state, detail={"accepted": sorted(accepted), "required": need,
                                          "not_finalized": pending, "not_accepted": failed})
        elif c.kind != "best" and any(m.name not in accepted for m in study.members):
            r.update(state="UNKNOWN", detail="every member must be finalized ACCEPT before cross-run criteria apply")
        elif c.kind == "gci":
            ms = sorted((m for m in study.members if m.h is not None), key=lambda m: m.h)[:3]
            res = gci([m.h for m in ms], [vals[m.name] for m in ms], c.safety_factor)
            r["detail"] = {**res.as_dict(), "members": [m.name for m in ms]}
            if res.status == "monotonic" and res.gci_fine_pct is not None:
                r["state"] = "PASS" if res.gci_fine_pct <= c.max_gci_pct else "FAIL"
            elif res.status == "converged":
                r["state"] = "PASS"
            elif res.status == "divergent":
                r["state"] = "FAIL"
            else:
                r["state"] = "UNKNOWN"
        elif c.kind == "monotonic":
            seq = [vals[m.name] for m in sorted(study.members, key=lambda m: m.parameters[c.parameter])]
            diffs = [b - a for a, b in zip(seq, seq[1:])]
            ok = all(d > 0 for d in diffs) if c.direction == "increasing" else all(d < 0 for d in diffs)
            r.update(state="PASS" if ok else "FAIL", detail={"ordered_values": seq})
        elif c.kind == "range":
            lo, hi = c.bounds
            bad = {n: v for n, v in vals.items() if not lo <= v <= hi}
            r.update(state="FAIL" if bad else "PASS", detail={"values": vals, "outside": bad})
        elif c.kind == "best":
            pool = {n: v for n, v in vals.items() if n in accepted and v is not None}
            if len(pool) < 2 or any(final[n] is None for n in final):
                r.update(state="UNKNOWN", detail="fewer than two accepted candidates, or members not finalized")
            else:
                ranked = sorted(pool.items(), key=lambda kv: kv[1], reverse=c.goal == "maximize")
                pct = c.uncertainty_pct
                if c.uncertainty_from:
                    g = results.get(c.uncertainty_from, {}).get("detail", {})
                    gp = g.get("gci_fine_pct") if isinstance(g, dict) else None
                    if gp is None:
                        r.update(state="UNKNOWN", detail="referenced GCI unavailable")
                        results[c.id] = r
                        continue
                    pct = max(pct, gp)
                (b, vb), (s2, vs) = ranked[0], ranked[1]
                margin = abs(vb - vs)
                band = pct / 100 * (abs(vb) + abs(vs))
                r["detail"] = {"ranking": ranked, "best": b, "runner_up": s2, "margin": margin,
                               "combined_uncertainty": band, "uncertainty_pct": pct,
                               "excluded_not_accepted": sorted(set(vals) - accepted)}
                r["state"] = "PASS" if margin > band else "UNKNOWN"
        results[c.id] = r
    states = [r["state"] for r in results.values()]
    verdict = ("REJECT" if "FAIL" in states else "INCONCLUSIVE" if "UNKNOWN" in states else "ACCEPT")
    record = {"study_id": study_id, "verdict": verdict, "criteria": list(results.values()),
              "members": {n: {"final": final[n], "leaf_run": leaves[n]["plan"]["run_id"]} for n in final},
              "study_sha256": sha256_json(study)}
    if study.design_bounds:
        b = {k: (v[0], v[1]) for k, v in study.design_bounds.items()}
        for c in study.criteria:
            if c.kind == "best":
                values = checked_values.get(c.id, {})
                pts = [(m.parameters, values.get(m.name)) for m in study.members if m.name in accepted]
                pts = [(p, v) for p, v in pts if v is not None and set(b) <= set(p)]
                record["surrogate"] = quadratic_surrogate([p for p, _ in pts], [v for _, v in pts], b, c.goal) \
                    if pts else {"ok": False, "reason": "no unit-consistent accepted points"}
                break
    integrity.append(path, "study_assessed", record=record)
    (path / "study_assessment.json").write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
    (path / "study_report.md").write_text(_report(study, record), encoding="utf-8")
    return {**record, "report": str(path / "study_report.md")}


def _report(study: Study, rec: dict) -> str:
    lines = [f"# {study.title}", "", f"**Study verdict:** `{rec['verdict']}` ({study.kind})", "",
             "## Request", "", study.requested_prompt.strip(), "", "## Members", "",
             "| Member | Parameters | h | Final | Leaf run |", "|---|---|---|---|---|"]
    for m in study.members:
        info = rec["members"][m.name]
        lines.append(f"| {m.name} | {json.dumps(m.parameters)} | {m.h or ''} | {info['final']} | `{info['leaf_run']}` |")
    lines += ["", "## Criteria", ""]
    for r in rec["criteria"]:
        lines += [f"### {r['id']} ({r['kind']}): {r['state']}", "", r["rationale"], ""]
        if "unit" in r:
            lines += [f"Recorded comparison unit: `{r['unit']}`.", ""]
        lines += ["```json", json.dumps(r.get("detail"), indent=1, default=str), "```", ""]
    if "surrogate" in rec:
        lines += ["## Surrogate (advisory only)", "", "```json", json.dumps(rec["surrogate"], indent=1), "```", "",
                  "The surrogate is not evidence. A design claim needs a checked run at the suggested point."]
    return "\n".join(lines) + "\n"
