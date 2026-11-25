"""Deterministic report: every number comes from the evidence record with its own unit."""

from __future__ import annotations

from .models import Assessment, CaseBundle, Evidence


def _fmt(v: object) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def render(bundle: CaseBundle, plan: dict, evidence: Evidence, a: Assessment) -> str:
    c = bundle.contract
    lines = [
        f"# {c.title}", "",
        f"**Deterministic verdict:** `{a.verdict.value}`  ",
        f"**Live acceptance:** {'yes' if a.live_acceptance else 'no'} (evidence origin `{a.evidence_origin}`)  ",
        f"**Contract authority:** `{c.authority}`; contract SHA-256 `{a.contract_sha256[:16]}…`  ",
        f"**Run:** `{plan['run_id']}` (attempt {plan['attempt']}, lineage `{plan['lineage']['root']}`)", "",
        "Acceptance means the frozen contract below was satisfied by measured evidence. It is not a "
        "general statement of physical validity.", "",
        "## Request", "", c.requested_prompt.strip(), "",
        "## Objectives", "",
    ]
    for o in c.objectives:
        lines.append(f"- **{o.id}** ({o.claim}): {o.description} — checks: {', '.join(o.check_ids) or 'none'}")
    lines += ["", "## Checks", "", "| Check | State | Metric | Value | Criterion | Unit | Category |",
              "|---|---|---|---|---|---|---|"]
    for r in a.checks:
        chk = next(x for x in c.checks if x.id == r.id)
        crit = chk.operator if chk.threshold is None else f"{chk.operator} {_fmt(chk.threshold)}"
        lines.append(f"| {r.id} | {r.state} | `{r.metric}` | {_fmt(r.value)} | {crit} | {r.unit} | {r.category} |")
    if a.unresolved:
        lines += ["", "## Unresolved", ""] + [f"- {u}" for u in a.unresolved]
    lines += ["", "## Assumptions", ""]
    lines += [f"- {x.parameter} = {_fmt(x.value)} {x.unit} ({x.source}): {x.justification}"
              for x in c.assumptions] or ["- none recorded"]
    lines += ["", "## Measured evidence", "", "| Metric | Value | Unit | Source |", "|---|---|---|---|"]
    for k, m in sorted(evidence.metrics.items()):
        val = _fmt(m.value) if m.status == "measured" else f"*{m.status}*"
        lines.append(f"| `{k}` | {val} | {m.unit} | {m.source} |")
    rt = evidence.runtime
    lines += ["", "## Provenance", "",
              f"- OpenFOAM: {rt.get('distribution', '?')} build `{rt.get('openfoam_build', '?')}`",
              f"- Image: `{rt.get('image', '?')}` id `{str(rt.get('image_id', ''))[:19]}`",
              f"- Frozen case SHA-256: `{plan['frozen_sha256']}`",
              f"- Wall time: {rt.get('wall_s', '?')} s; output {rt.get('output_mb', '?')} MB",
              f"- Resource limits: {rt.get('resource_limits', '?')}; MPI ranks {rt.get('mpi_ranks', 1)}",
              ]
    figures = rt.get("figures") or []
    if figures:
        lines += ["", "## Figures", "", "Figures illustrate the evidence; they are not used for the verdict.", ""]
        lines += [f"![{f}](output/figures/{f})" for f in figures]
    lines += ["", "## Limitations", ""]
    lines += [f"- {x}" for x in c.limitations] or ["- none stated"]
    lines += [f"- Reference: {c.reference}"]
    if evidence.errors:
        lines += ["", "## Extraction errors", ""] + [f"- {e}" for e in evidence.errors]
    return "\n".join(lines) + "\n"
