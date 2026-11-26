"""Held-out prompt suite: run each prompt through CLIO, then score from the run stores.

    python -m scripts.heldout --help
    python scripts/heldout.py run [--only H01,H02] [--parallel 2]
    python scripts/heldout.py score

Each prompt gets its own run store (DISCOVERY_PHYSICS_RUNS) so artifacts are attributable;
the operator's concurrency and resource policy still apply. The harness does not enable
unenforced resource limits unless the operator explicitly supplies --allow-unenforced-limits.
New CLI outputs require an explicit project, marked results and --out; AppData is
only a historical score-input default, never a new live work/output default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import runpy
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

if __package__:
    from .result_paths import ResultPaths, add_arguments
else:
    _routing = runpy.run_path(str(Path(__file__).with_name("result_paths.py")))
    ResultPaths, add_arguments = _routing["ResultPaths"], _routing["add_arguments"]

WS = Path(__file__).resolve().parents[1]
PROMPTS = WS / "benchmarks" / "heldout" / "prompts.json"


def data_home() -> Path:
    """Use package configuration when installed; importing the harness needs no install."""
    try:
        from discovery_physics.core.config import home
    except ImportError:
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DiscoveryPhysics"
    return home()


OUT = data_home() / "heldout"
PY = Path(sys.executable)
SUFFIX = (
    "\n\nContext: use the phy-openfoam skill in this workspace (the `discovery-physics` CLI). "
    "No user is available during this run: if information that materially changes the physics "
    "is missing, do not guess; stop and state the specific questions you would ask, "
    "with any assumptions you could offer. Keep every mesh under 50,000 cells and each solve "
    "under 30 minutes. Report the final verdict exactly as returned by `finalize`, with run IDs."
)


def require_skill(workspace: Path) -> None:
    skill = workspace / ".github" / "skills" / "phy-openfoam" / "SKILL.md"
    if not skill.is_file():
        raise FileNotFoundError(
            f"Live held-out runs require the installed phy-openfoam skill at {skill}. "
            "Install the skill into the target project and select it with --workspace."
        )


def run_one(p: dict, *, project_root: Path, results_dir: Path,
            work_root: Path | None = None, workspace: Path | None = None,
            python: str | Path | None = None, clio_executable: str | Path | None = None,
            allow_unenforced_limits: bool = False) -> dict:
    paths = ResultPaths(project_root, results_dir)
    workspace = paths.guard.project_root(workspace if workspace is not None else project_root)
    if workspace != paths.project:
        raise ValueError("The held-out workspace must be the explicitly selected project root")
    require_skill(workspace)
    if not isinstance(p["id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", p["id"]):
        raise ValueError("Invalid held-out prompt ID")
    parent = paths.output(work_root or "analysis/heldout", new=False)
    d = paths.output(parent / p["id"])
    native_parent = paths.destination(paths.results / "runs" / p["id"], new=True)
    runs = paths.run_root(native_parent / "runs")
    d = paths.directory(d)
    native_parent.mkdir(parents=True, exist_ok=False)
    prompt = p["prompt"] + SUFFIX + (
        f"\nExplicit project root: {paths.project}\nSelected marked results: {paths.results}\n"
        f"This harness isolates this prompt's native store at {runs}; preserve the inherited "
        "DISCOVERY_PHYSICS_RUNS when calling the native CLI. Keep every generated input, "
        "analysis, log and report inside the selected results, never contribution source."
    )
    paths.write_text(d / "prompt.txt", prompt)
    env = paths.child_env(runs)
    if allow_unenforced_limits:
        env["DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS"] = "1"
    command = [str(python if python is not None else PY), "-X", "utf8",
               str(Path(__file__).with_name("clio_driver.py")), "run",
               str(d / "prompt.txt"), "--out", str(d / "clio"), "--cwd", str(workspace),
               "--project-root", str(paths.project), "--results-dir", str(paths.results),
               "--runs-root", str(runs),
               "--timeout", "5400"]
    if clio_executable is not None:
        command.extend(["--clio-executable", str(clio_executable)])
    t0 = time.time()
    proc = subprocess.run(
        command, env=env, cwd=workspace, capture_output=True, text=True, encoding="utf-8",
    )
    paths.write_text(d / "stdout.log", proc.stdout)
    paths.write_text(d / "stderr.log", proc.stderr)
    res = {
        "id": p["id"], "rc": proc.returncode, "wall_s": round(time.time() - t0),
        "stdout": proc.stdout[-500:], "stderr": proc.stderr[-1500:],
        "runs_root": str(runs),
        "operator_resource_policy": {
            "allow_unenforced_limits_flag": allow_unenforced_limits,
            "allow_unenforced_limits_environment": env.get(
                "DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS",
            ),
            "configuration_inherited": True,
        },
    }
    paths.write_text(d / "driver.json", json.dumps(res, indent=1) + "\n")
    print(time.strftime("%H:%M:%S"), p["id"], res["rc"], res["stdout"].strip()[-200:], flush=True)
    return res


def final_answer(d: Path) -> str:
    """Read the terminal result for this workflow, not a truncated event tail."""
    w = d / "clio" / "wait.log"
    if not w.exists():
        return ""
    receipt = d / "clio" / "result.json"
    try:
        run_id = json.loads(receipt.read_text(encoding="utf-8"))["run_id"]
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    blocks = w.read_text(encoding="utf-8").split("\n---\n")
    terminal = re.compile(rf"^run {re.escape(run_id)} \[(done|failed|stopped)\]", re.M)
    done = [b for b in blocks if terminal.search(b)]
    if not done:
        return ""
    return done[-1].partition("===== RESULT =====")[2].strip()


def classify_behavior(expect: str, runs: list[dict], studies: list[dict], answer: str,
                      *, completed: bool) -> dict:
    """Behavioral compliance, never a substitute for the scientific acceptance gate.

    Revision 2 recognizes a signed, unexecuted method-substitution gate as an
    honest response to an infeasible request. It does not change any CFD contract.
    """
    asked = bool(re.search(r"\?|clarif|question", answer, re.I))
    refused = bool(re.search(
        r"unsupported|cannot|not (able|possible)|outside|REJECT_UNSUPPORTED|out of scope",
        answer, re.I,
    ))
    executed = any(r.get("ever_started") or r.get("executed") for r in runs)
    finals = [r.get("final") for r in runs if r.get("final")]
    blocked = any("method_substitution" in r.get("pending", []) for r in runs)
    result = {"behaviour_ok": False, "outcome": "failed", "asked": asked,
              "refused_language": refused, "reason": "expected_behavior_not_observed"}
    if not completed:
        return {**result, "reason": "workflow_not_completed"}
    if any(r.get("integrity_ok") is not True for r in [*runs, *studies]):
        return {**result, "reason": "integrity_failure"}
    if any(v not in {"ACCEPT", "REJECT", "INCONCLUSIVE"} for v in finals):
        return {**result, "reason": "invalid_final_verdict"}
    if any(r.get("final") == "ACCEPT" and r.get("live_acceptance") is not True for r in runs):
        return {**result, "reason": "accept_without_live_evidence"}
    outcome = None
    if expect == "run" and finals:
        outcome = "finalized"
    elif expect == "study" and runs and any(
        s.get("verdict") in {"ACCEPT", "REJECT", "INCONCLUSIVE"} for s in studies
    ):
        outcome = "study_assessed"
    elif expect == "clarify" and not executed and not finals and asked:
        outcome = "clarification"
    elif expect == "refuse" and not executed and not finals:
        if blocked:
            outcome = "blocked_method_substitution"
        elif refused:
            outcome = "unsupported_refusal"
    elif expect == "run_honest":
        if finals:
            outcome = "finalized"
        elif not executed and (asked or blocked):
            outcome = "blocked_method_substitution" if blocked else "clarification"
    if outcome:
        return {**result, "behaviour_ok": True, "outcome": outcome, "reason": "verified_behavior"}
    return result


def _completion(d: Path) -> tuple[dict, bool]:
    driver = {}
    try:
        driver = json.loads((d / "driver.json").read_text(encoding="utf-8"))
        if not isinstance(driver, dict):
            return {}, False
        receipt = json.loads((d / "clio" / "result.json").read_text(encoding="utf-8"))
        answer = final_answer(d)
        completed = driver["rc"] == 0 and receipt["state"] == "done" and bool(answer)
        return driver, completed
    except (OSError, ValueError, KeyError, TypeError):
        return driver, False


def _study_results(d: Path, *, studies_root: Path | None = None) -> list[dict]:
    """Audit the signed study result without appending a new assessment."""
    from discovery_physics.core import integrity
    from discovery_physics.core.hashing import sha256_json
    from discovery_physics.openfoam import study

    out = []
    root = studies_root if studies_root is not None else d / "studies"
    for path in sorted(root.iterdir()) if root.is_dir() else []:
        if not path.is_dir():
            continue
        try:
            _, spec, members = study._verified_study(path.name)
            records = integrity.verify_journal(path)
            last = integrity.last(records, "study_assessed")
            if last is None:
                for root_run in members.values():
                    study._leaf(root_run)
                out.append({
                    "study": path.name, "verdict": None, "integrity_ok": True,
                    "assessed": False, "status": "prepared_not_assessed",
                    "journal_sha256": hashlib.sha256(
                        (path / "journal.jsonl").read_bytes()
                    ).hexdigest(),
                })
                continue
            record = last["record"]
            saved = json.loads((path / "study_assessment.json").read_text(encoding="utf-8"))
            if (
                sha256_json(record) != sha256_json(saved)
                or record["study_sha256"] != sha256_json(spec)
            ):
                raise ValueError("study result differs from the signed record")
            for name, root_run in members.items():
                leaf = study._leaf(root_run)
                final = leaf["final"]["final_verdict"] if leaf["final"] else None
                if record["members"][name] != {
                    "final": final, "leaf_run": leaf["plan"]["run_id"],
                }:
                    raise ValueError("study result does not describe the current member lineage")
            out.append({
                "study": path.name, "verdict": record["verdict"], "integrity_ok": True,
                "assessed": True,
                "journal_sha256": hashlib.sha256((path / "journal.jsonl").read_bytes()).hexdigest(),
            })
        except (integrity.IntegrityError, OSError, ValueError, KeyError, TypeError) as exc:
            out.append({
                "study": path.name, "verdict": None, "integrity_ok": False, "error": str(exc),
            })
    return out


def score(output: Path | None = None, *, work_root: Path | None = None) -> dict:
    if output is None:
        raise ValueError("An explicit score output is required; historical inputs are read-only")
    if output.exists() or output.is_symlink():
        raise FileExistsError("Score output already exists; preserve the original")
    from discovery_physics.core.integrity import IntegrityError
    from discovery_physics.openfoam import runner

    prompts = json.loads(PROMPTS.read_text(encoding="utf-8"))
    root = work_root if work_root is not None else OUT
    rows = []
    previous_store = os.environ.get("DISCOVERY_PHYSICS_RUNS")
    try:
        for p in prompts:
            d = root / p["id"]
            driver, completed = _completion(d)
            # Old receipts retain their original per-prompt layout. New routed
            # receipts explicitly identify the store under selected results/runs.
            runs = Path(driver.get("runs_root") or d / "runs")
            os.environ["DISCOVERY_PHYSICS_RUNS"] = str(runs)
            paths = (
                sorted(x for x in runs.iterdir()
                       if x.is_dir() and re.match(r"^\d{8}T", x.name))
                if runs.is_dir() else []
            )
            info = []
            for path in paths:
                try:
                    st = runner.verified(path.name)
                    info.append({
                        "run": path.name, "integrity_ok": True, "executed": bool(st["assessed"]),
                        "ever_started": any(
                            r["event"] == "execution_started" for r in st["records"]
                        ),
                        "final": st["final"]["final_verdict"] if st["final"] else None,
                        "live_acceptance": st["final"]["live_acceptance"] if st["final"] else False,
                        "pending": st["pending"], "checks": len(st["bundle"].contract.checks),
                        "claims": sorted({o.claim for o in st["bundle"].contract.objectives}),
                        "journal_sha256": hashlib.sha256(
                            (path / "journal.jsonl").read_bytes()
                        ).hexdigest(),
                    })
                except (IntegrityError, OSError, ValueError, KeyError, TypeError) as exc:
                    info.append({"run": path.name, "integrity_ok": False, "executed": False,
                                 "final": None, "claims": [], "error": str(exc)})
            studies = _study_results(d, studies_root=runs.parent / "studies")
            answer = final_answer(d)
            behavior = classify_behavior(
                p["expect"], info, studies, answer, completed=completed,
            )
            rows.append({
                "id": p["id"], "kind": p["kind"], "expect": p["expect"], **behavior,
                "completed": completed, "runs": len(info),
                "executed": sum(i["executed"] for i in info),
                "ever_started": sum(bool(i.get("ever_started")) for i in info),
                "finals": [i["final"] for i in info if i["final"]],
                "studies": [s["verdict"] for s in studies if s["integrity_ok"] and s["verdict"]],
                "tampered": [i["run"] for i in info if not i["integrity_ok"]],
                "study_errors": [s for s in studies if not s["integrity_ok"]],
                "claims": sorted({c for i in info for c in i["claims"]}),
                "wall_s": driver.get("wall_s"), "run_receipts": info, "study_receipts": studies,
                "operator_resource_policy": driver.get("operator_resource_policy"),
                "answer_sha256": hashlib.sha256(answer.encode("utf-8")).hexdigest(),
            })
    finally:
        if previous_store is None:
            os.environ.pop("DISCOVERY_PHYSICS_RUNS", None)
        else:
            os.environ["DISCOVERY_PHYSICS_RUNS"] = previous_store
    summary = {
        "n": len(rows), "behaviour_ok": sum(r["behaviour_ok"] for r in rows),
        "tampered_runs": sum(len(r["tampered"]) for r in rows),
        "false_accept_candidates": [
            r["id"] for r in rows
            if "ACCEPT" in r["finals"] and r["expect"] in ("clarify", "refuse")
        ],
        "completed": sum(r["completed"] for r in rows),
        "study_integrity_errors": sum(len(r["study_errors"]) for r in rows),
        "scorer_revision": 2, "generated_utc": datetime.now(UTC).isoformat(),
        "prompts_sha256": hashlib.sha256(PROMPTS.read_bytes()).hexdigest(), "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(summary, indent=1) + "\n")
    return summary


def render_report(s: dict) -> str:
    lines = [
        "# Held-out prompt validation", "",
        f"Generated: {s['generated_utc']}. Scorer revision: {s['scorer_revision']}.", "",
        f"**Behavior checks: {s['behaviour_ok']}/{s['n']}; "
        f"completed workflows: {s['completed']}/{s['n']}.**",
        f"Run integrity errors: {s['tampered_runs']}; "
        f"study integrity errors: {s['study_integrity_errors']}; "
        f"clarify/refuse ACCEPT candidates: {len(s['false_accept_candidates'])}.", "",
        "This is behavioral compliance, not independent validation of every CFD prediction. "
        "`ACCEPT` means the frozen scientific contract passed with live evidence. "
        "`REJECT`, `INCONCLUSIVE`, clarification, and a blocked method substitution "
        "can be honest outcomes.", "",
        "## Per-prompt results", "",
        "| Prompt | Kind | Expected behavior | Observed outcome | "
        "Scientific finals | Studies | Executed | Behavior |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in s["rows"]:
        finals = ", ".join(r["finals"]) or "none"
        studies = ", ".join(r["studies"]) or "none"
        lines.append(
            f"| {r['id']} | {r['kind']} | {r['expect']} | {r['outcome']} | {finals} | {studies} | "
            f"{r['executed']} | {'PASS' if r['behaviour_ok'] else 'FAIL'} |"
        )
    lines += [
        "", "## Scoring correction and evidence limits", "",
        "- Revision 1 used refusal keywords in a truncated answer. "
        "Revision 2 reads the full terminal "
        "result and recognizes a signed, unexecuted `method_substitution` confirmation gate. "
        "This is a disclosed post-run correction to behavioral scoring, "
        "not a relaxed CFD tolerance.",
        "- A blocked method substitution has no scientific final verdict. "
        "Nothing in this report authorizes a substitute or confirms a pending assumption.",
        "- Every expected prompt is counted, including missing or unfinished workflows. "
        "A failed integrity audit, missing completion receipt, or non-live ACCEPT cannot pass.",
        "- Study results are checked against signed assessment records "
        "and current member lineages; "
        "scoring does not append new assessments or alter run artifacts.",
        "- Prepared-only study attempts are retained in the receipts as unassessed. "
        "They neither count as completed study results nor invalidate a separate, verified "
        "completed study.",
        "- The harness does not enable unenforced resource limits by default. Explicit operator "
        "flags and inherited configuration are disclosed in driver/runtime receipts; "
        "host evidence is not proof of production cgroup enforcement.",
        "- Single-run results do not establish grid independence. Inconclusive/rejected quantities "
        "must not be presented as validated answers.", "",
        "Machine-readable receipts and hashes: [score.json](score.json). "
        "Prompt definitions: [prompts.json](prompts.json).", "",
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("run", "score"))
    add_arguments(ap)
    ap.add_argument("--only")
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--out", type=Path, required=True, help="New JSON receipt inside results")
    ap.add_argument("--report", type=Path)
    ap.add_argument("--work-root", type=Path,
                    help="Run: new results-contained receipts directory; score: historical read input")
    ap.add_argument("--workspace", type=Path,
                    help="Target project with the installed phy-openfoam skill")
    ap.add_argument("--python",
                    help="Python with discovery-physics installed; defaults to this interpreter")
    ap.add_argument("--clio-executable", help="Installed CLIO executable (or DISCOVERY_CLIO_EXE)")
    ap.add_argument(
        "--allow-unenforced-limits", action="store_true",
        help="OPERATOR ONLY: explicitly permit the runner's disclosed unenforced-limit fallback",
    )
    args = ap.parse_args(argv)
    try:
        paths = ResultPaths(args.project_root, args.results_dir)
        output = paths.output(args.out)
        report = paths.output(args.report) if args.report is not None else None
        if report == output:
            raise ValueError("--out and --report must select different new files")
    except (OSError, ValueError, RuntimeError) as exc:
        ap.error(str(exc))
    if args.action == "score":
        source = paths.input(args.work_root) if args.work_root is not None else OUT
        s = score(output, work_root=source)
        if report is not None:
            paths.write_text(report, render_report(s))
        for r in s["rows"]:
            print(
                r["id"], r["expect"], "OK" if r["behaviour_ok"] else "CHECK", r["outcome"],
                r["finals"], r["studies"], f"{r['wall_s']}s",
            )
        print({
            k: s[k] for k in (
                "n", "behaviour_ok", "tampered_runs", "study_integrity_errors",
                "false_accept_candidates",
            )
        })
        return 0 if s["behaviour_ok"] == s["n"] else 1
    if args.parallel < 1:
        ap.error("--parallel must be positive")
    if report is not None:
        ap.error("--report is available only for score")
    try:
        workspace = paths.guard.project_root(args.workspace or args.project_root)
        if workspace != paths.project:
            raise ValueError("--workspace must match --project-root")
        require_skill(workspace)
    except (OSError, ValueError, RuntimeError) as exc:
        ap.error(str(exc))
    only = args.only.split(",") if args.only else None
    prompts = [
        p for p in json.loads(PROMPTS.read_text(encoding="utf-8"))
        if not only or p["id"] in only
    ]
    try:
        work = paths.output(args.work_root or "analysis/heldout")
        if work == output or work.is_relative_to(output):
            raise ValueError("The JSON output cannot be the work directory or one of its parents")
        # Refuse the whole requested batch before dispatching any model session.
        ids = [prompt.get("id") for prompt in prompts]
        if (any(not isinstance(value, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_-]*", value,
        ) for value in ids) or len(set(ids)) != len(ids)):
            raise ValueError("Held-out prompt IDs must be unique portable names")
        for prompt_id in ids:
            paths.output(work / prompt_id)
            native = paths.destination(paths.results / "runs" / prompt_id, new=True)
            paths.run_root(native / "runs")
        work = paths.directory(work)
    except (OSError, ValueError, RuntimeError) as exc:
        ap.error(str(exc))
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        results = list(pool.map(lambda p: run_one(
            p, project_root=paths.project, results_dir=paths.results,
            work_root=work, workspace=workspace, python=args.python,
            clio_executable=args.clio_executable,
            allow_unenforced_limits=args.allow_unenforced_limits,
        ), prompts))
    paths.write_text(output, json.dumps({"work": str(work), "results": results}, indent=1) + "\n")
    return 0 if all(result["rc"] == 0 for result in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
