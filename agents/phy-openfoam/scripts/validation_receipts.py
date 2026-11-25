"""Publish bounded verification receipts for existing CFD evidence; never re-solve."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from discovery_physics.benchmarks.report import PAPER_DECISION, PAPER_NUM
from discovery_physics.core import integrity
from discovery_physics.openfoam import runner, study

if __package__:
    from .result_paths import ResultPaths, add_arguments
else:
    from result_paths import ResultPaths, add_arguments


def campaign(results: Path) -> dict:
    rows = []
    for case, paper in PAPER_DECISION.items():
        source = results / f"{case}.json"
        result = json.loads(source.read_text(encoding="utf-8"))
        if result.get("case") != case or not result.get("trail"):
            raise ValueError(f"invalid campaign receipt: {case}")
        verified = [runner.verified(step["run_id"]) for step in result["trail"]]
        leaf = verified[-1]
        final = leaf["final"]
        if final is None or final != result["final"]:
            raise ValueError(f"campaign final differs from signed record: {case}")
        metrics = leaf["evidence"].metrics
        comparisons = {}
        for name, reference in PAPER_NUM.get(case, {}).items():
            m = metrics.get(name)
            if m is None or m.status != "measured":
                raise ValueError(f"missing comparison metric: {case}/{name}")
            comparisons[name] = {"paper": reference, "measured": m.value, "unit": m.unit,
                                 "difference_pct": 100 * (m.value / reference - 1)}
        rows.append({"case": case, "paper_decision": paper, "final": final["final_verdict"],
                     "decision_match": final["final_verdict"] == paper.split()[0],
                     "live_acceptance": final["live_acceptance"], "comparisons": comparisons,
                     "runs": [{"run_id": s["plan"]["run_id"], "journal_sha256":
                               integrity.file_sha256(s["path"] / "journal.jsonl"),
                               "worker_image_id": s["assessed"]["runtime_host"]["image_id"],
                               "resource_limits": s["assessed"]["runtime_host"]["resource_limits"],
                               "integrity_ok": True} for s in verified]})
    if not all(row["decision_match"] for row in rows):
        raise ValueError("campaign decisions no longer match the published reference")
    return {
        "cases": len(rows), "decision_matches": sum(r["decision_match"] for r in rows),
        "rows": rows,
    }


def supplemental(source: Path) -> dict:
    saved = json.loads(source.read_text(encoding="utf-8"))
    path, _, members = study._verified_study(saved["study_id"])
    record = integrity.last(integrity.verify_journal(path), "study_assessed")["record"]
    if record["verdict"] != saved["verdict"]:
        raise ValueError("supplemental study differs from signed verdict")
    rows = {}
    for name, root in members.items():
        leaf = study._leaf(root)
        selected = {
            k: {"value": v.value, "unit": v.unit}
            for k, v in leaf["evidence"].metrics.items()
            if k in {"mesh.cells", "compression.front_x", "compression.p_ratio",
                     "compression.rho_ratio", "compression.T_ratio"}
        }
        rows[name] = {"run_id": leaf["plan"]["run_id"], "final": leaf["final"]["final_verdict"],
                      "integrity_ok": True, "metrics": selected,
                      "journal_sha256": integrity.file_sha256(leaf["path"] / "journal.jsonl")}
    return {
        "study_id": saved["study_id"], "verdict": record["verdict"], "criteria": record["criteria"],
        "members": rows, "journal_sha256": integrity.file_sha256(path / "journal.jsonl"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        paths = ResultPaths(args.project_root, args.results_dir)
        output = paths.output(args.out)
        source = paths.input(args.results)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    record = {
        "generated_utc": datetime.now(UTC).isoformat(), "campaign": campaign(source),
        "supplemental_s8": supplemental(source / "S8_study.json"),
    }
    paths.write_text(output, json.dumps(record, indent=1) + "\n")
    print(json.dumps({
        "cases": record["campaign"]["cases"], "matches": record["campaign"]["decision_matches"],
        "supplemental_s8": record["supplemental_s8"]["verdict"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())