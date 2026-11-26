"""Reproducible native CLIO reviews of full (B) and packet-blinded (C) evidence.

The CLI requires an explicit project, marked results, --packets input and new --out.
No CFD is executed. Four fresh sessions review 20 points each by default. Protocol,
inputs, raw model judgments, response-model receipts, and complete-coverage scores
are retained. Ground truth is loaded only after every model session has completed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

if __package__:
    from .result_paths import ResultPaths, add_arguments
else:
    from result_paths import ResultPaths, add_arguments

VERDICTS = {"ACCEPT", "CORRECT_AND_RERUN", "NEEDS_MORE_RUNTIME", "REJECT", "INCONCLUSIVE"}
BLIND_KEYS = {"checks", "unresolved", "verdict", "live_acceptance", "not_passing", "ruling"}


def data_home() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DiscoveryPhysics"


def native_state_home() -> Path:
    """Root containing science-runs/ and session-state/ for the installed CLIO."""
    selected = os.environ.get("DISCOVERY_CLIO_STATE_HOME")
    return (Path(selected).expanduser() if selected else Path.home() / ".copilot").resolve()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_text(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def _write_bytes(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique)


def prepare_batches(full: list[dict], blind: list[dict], *, seed: int, batch_size: int):
    """Remove group/point label leakage and pair the same shuffled snapshots."""
    if not 1 <= batch_size <= 40:
        raise ValueError("batch size must be between 1 and 40")
    b = {p["point"]: p for p in full}
    c = {p["point"]: p for p in blind}
    if not b or len(b) != len(full) or len(c) != len(blind) or set(b) != set(c):
        raise ValueError("packet points must be unique, nonempty, and paired between arms")
    for point in b:
        if BLIND_KEYS & set(c[point]):
            raise ValueError(f"blind packet leaks gate outputs: {point}")
        if b[point]["measured"] != c[point]["measured"]:
            raise ValueError(f"arms do not share identical measured evidence: {point}")
    order = sorted(b)
    random.Random(seed).shuffle(order)
    aliases = {f"P{i + 1:02d}": point for i, point in enumerate(order)}
    batches = []
    # C is scheduled before B; every batch owns a fresh native server/session.
    for arm, source in (("C_blind", c), ("B_full", b)):
        packets = [{**{k: v for k, v in source[point].items() if k not in {"point", "group"}},
                    "point": alias} for alias, point in aliases.items()]
        for offset in range(0, len(packets), batch_size):
            batches.append({"batch": f"{arm[0]}{offset // batch_size + 1:02d}", "arm": arm,
                            "packets": packets[offset:offset + batch_size]})
    return aliases, batches


def objective(batch: dict) -> str:
    ids = [p["point"] for p in batch["packets"]]
    visibility = (
        "The full packet includes registered check outcomes and the reported assessment. "
        "That is intentional: this arm measures informed interpretation, "
        "not independent validation."
        if batch["arm"] == "B_full"
        else (
            "This arm withholds registered check outcomes, thresholds, assessment verdicts, and "
            "objective coverage. Do not infer a missing registered tolerance or invent a check. "
            "A limitation of the supplied evidence may justify INCONCLUSIVE."
        )
    )
    return (
        f"Perform an evidence-only review of {len(ids)} anonymized CFD decision snapshots in "
        f"the {batch['arm']} condition. Your sole admissible data source is packet.json in this "
        "working directory. Supply your own model judgment for every point, with a short grounded "
        "rationale and actual measured metric names. Do not implement a deterministic controller "
        "to produce the judgments. " + visibility + "\n\n"
        "Hard constraints: no solver execution, case preparation, confirmation, "
        "source-code changes, file writes, external searches, subagents, or other investigations. "
        "Do not read outside this working directory or inspect ground truth, other packets, "
        "source code, logs, or other sessions. "
        "You may read the input and perform arithmetic. There is no feedback on the correctness "
        "of individual decisions. Do not revise a judgment to make a benchmark pass.\n\n"
        "Labels: ACCEPT means evidence supports scientific acceptance; CORRECT_AND_RERUN means "
        "healthy but insufficient horizon/stationarity and a bounded continuation is needed; "
        "REJECT means a hard physical or numerical failure; INCONCLUSIVE means evidence/coverage "
        "is missing or cannot resolve the claim. These are ungated advisory judgments, not actual "
        "solver acceptance decisions.\n\n"
        f"Required point IDs, each exactly once: {json.dumps(ids)}. "
        "Your final answer AND completion summary must both be exactly one JSON object, no fences "
        "or headings, with this schema: "
        '{"predictions":[{"point":"P01","verdict":"ACCEPT","rationale":"short reason",'
        '"evidence_metrics":["solver.completed"]}],"limitations":["short limitation"]}. '
        "Each evidence_metrics entry must occur in that point's measured dictionary; an empty "
        "list is permitted when the reason explicitly identifies missing evidence. Use LaTeX "
        "delimiters if a rationale contains a scientific equation. "
        "End when all points are reviewed."
    )


def parse_predictions(text: str, packets: list[dict]) -> dict:
    data = json.loads(text.strip(), object_pairs_hook=_unique)
    if not isinstance(data, dict) or set(data) != {"predictions", "limitations"}:
        raise ValueError("model response must contain exactly predictions and limitations")
    if not isinstance(data["predictions"], list) or not isinstance(data["limitations"], list):
        raise ValueError("predictions and limitations must be arrays")
    if any(not isinstance(x, str) for x in data["limitations"]):
        raise ValueError("limitations must be strings")
    expected = {p["point"]: p for p in packets}
    seen = set()
    for row in data["predictions"]:
        if not isinstance(row, dict) or set(row) != {
            "point", "verdict", "rationale", "evidence_metrics",
        }:
            raise ValueError("invalid prediction schema")
        point = row["point"]
        if not isinstance(point, str) or point not in expected or point in seen:
            raise ValueError(f"unknown or duplicate model point: {point}")
        seen.add(point)
        if not isinstance(row["verdict"], str) or row["verdict"] not in VERDICTS:
            raise ValueError(f"invalid model verdict: {point}")
        if not isinstance(row["rationale"], str) or not row["rationale"].strip():
            raise ValueError(f"missing model rationale: {point}")
        metrics = row["evidence_metrics"]
        if not isinstance(metrics, list) or any(not isinstance(k, str) for k in metrics):
            raise ValueError(f"invalid metric citations: {point}")
        if set(metrics) - set(expected[point]["measured"]):
            raise ValueError(f"invented measured metric: {point}")
    if seen != set(expected):
        raise ValueError(f"incomplete model answer coverage: {sorted(set(expected) - seen)}")
    return data


def audit_tool_events(events: list[dict], input_dir: Path) -> dict:
    """Audit ordered access, recognizing only same-run, tool-created output spills.

    A temporary filename alone is not permission: an earlier successful allowed
    tool must have returned the runtime's explicit overflow receipt for that path.
    """
    tools, violations, spills, calls = [], [], {}, {}
    denied = {"web_search", "web_fetch", "task", "start", "run", "steer"}
    forbidden_data = re.compile(
        r"truth\.json|packets_[BC]_|records\.jsonl|score_model|build_points|"
        r"benchmarks[/\\]|session-state[/\\]|science-runs", re.I,
    )
    forbidden_write = re.compile(r"write_text|write_bytes|Set-Content|Add-Content|Out-File", re.I)
    overflow = re.compile(
        r"^Output too large to read at once \([^\r\n]+\)\. Saved to:\s*([^\r\n]+)"
    )
    for event in events:
        data = event.get("data", {})
        if event.get("type") == "tool.execution_start":
            name = data.get("toolName", "")
            args = data.get("arguments", {})
            encoded = json.dumps(args)
            tools.append({
                "name": name, "arguments_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            })
            before = len(violations)
            if name in denied or forbidden_data.search(encoded) or forbidden_write.search(encoded):
                violations.append({"tool": name, "reason": "disallowed_tool_or_data_access"})
            if isinstance(args, dict):
                for key in ("path", "filePath", "file_path", "filename"):
                    if key in args and isinstance(args[key], str):
                        path = Path(args[key])
                        path = (
                            path.resolve() if path.is_absolute()
                            else (input_dir / path).resolve()
                        )
                        if not path.is_relative_to(input_dir.resolve()) and path not in spills:
                            violations.append({
                                "tool": name, "reason": "file_outside_input_directory",
                            })
            calls[data.get("toolCallId")] = {"allowed": before == len(violations), "name": name}
        elif event.get("type") == "tool.execution_complete":
            origin = calls.get(data.get("toolCallId"), {})
            result = data.get("result", {})
            content = result.get("content", "") if isinstance(result, dict) else ""
            match = overflow.match(content) if isinstance(content, str) else None
            if (data.get("success") is True and origin.get("allowed") and match
                    and origin.get("name") in {"powershell", "bash", "view"}):
                path = Path(match.group(1)).resolve()
                if (path.parent == Path(tempfile.gettempdir()).resolve()
                        and re.fullmatch(r"copilot-tool-output-[\w-]+\.txt", path.name)):
                    spills[path] = {"filename": path.name,
                                    "origin_tool_call_id": data["toolCallId"],
                                    "output_sha256": digest(path) if path.is_file() else None}
    return {"tool_calls": tools, "policy_violations": violations,
            "same_session_overflow_outputs": list(spills.values()), "audit_revision": 2}


def native_receipt(run_id: str, input_dir: Path, *, state_home: Path | None = None) -> dict:
    """Copy only bounded provenance fields, never opaque API/reasoning blobs."""
    if not re.fullmatch(r"[0-9a-f]{6,}", run_id):
        raise ValueError("invalid native CLIO run ID")
    root = (state_home if state_home is not None else native_state_home()).expanduser().resolve()
    index_path = (root / "science-runs" / f"{run_id}.json").resolve()
    if not index_path.is_relative_to(root):
        raise ValueError("native run index is outside the configured state root")
    index = load_json(index_path)
    session_id = index["session_id"]
    if (not isinstance(session_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", session_id)):
        raise ValueError("invalid native CLIO session ID")
    path = (root / "session-state" / session_id / "events.jsonl").resolve()
    if not path.is_relative_to(root):
        raise ValueError("native session events are outside the configured state root")
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    models, metrics = set(), {}
    for event in events:
        data = event.get("data", {})
        if event.get("type") == "assistant.message" and data.get("model"):
            models.add(data["model"])
        if event.get("type") == "session.shutdown":
            metrics = {model: {"requests": values.get("requests", {}).get("count", 0),
                                "input_tokens": values.get("usage", {}).get("inputTokens", 0),
                                "output_tokens": values.get("usage", {}).get("outputTokens", 0)}
                       for model, values in data.get("modelMetrics", {}).items()}
    if not models or not metrics or not any(v["requests"] > 0 for v in metrics.values()):
        raise ValueError("native session lacks response-model and nonzero request evidence")
    return {"run_id": run_id, "session_id": session_id, "response_models": sorted(models),
            "model_metrics": metrics, **audit_tool_events(events, input_dir),
            "events_sha256": digest(path)}


def review_batch(batch: dict, work: Path, published: Path, timeout: float,
                 *, env: dict[str, str] | None = None) -> dict:
    if __package__:
        from . import clio_driver
    else:
        import clio_driver

    d = work / batch["batch"]
    inputs = d / "input"
    inputs.mkdir(parents=True)
    packet_file = inputs / "packet.json"
    _write_text(packet_file, json.dumps(batch, indent=1) + "\n")
    _write_bytes(published / "inputs" / f"{batch['batch']}.json", packet_file.read_bytes())
    prompt = objective(batch)
    _write_text(published / "objectives" / f"{batch['batch']}.txt", prompt)
    if env is None:  # Retain the explicit-path interface for synthetic plumbing tests.
        clio_driver.run(prompt, d / "clio", cwd=inputs, timeout=timeout)
    else:
        clio_driver.run(prompt, d / "clio", cwd=inputs, timeout=timeout, env=env)
    return collect_batch(batch, work, published)


def collect_batch(batch: dict, work: Path, published: Path) -> dict:
    """Re-audit immutable native judgments without making another model call."""
    if __package__:
        from .heldout import final_answer
    else:
        from heldout import final_answer

    d = work / batch["batch"]
    inputs = d / "input"
    result = load_json(d / "clio" / "result.json")
    if result["state"] != "done":
        raise RuntimeError(f"{batch['batch']} native CLIO ended as {result['state']}")
    before = digest(published / "inputs" / f"{batch['batch']}.json")
    if digest(inputs / "packet.json") != before:
        raise ValueError(f"{batch['batch']} input changed during review")
    text = final_answer(d)
    _write_text(published / "responses" / f"{batch['batch']}.txt", text)
    parsed = parse_predictions(text, batch["packets"])
    receipt = native_receipt(result["run_id"], inputs)
    if receipt["policy_violations"]:
        raise ValueError(f"{batch['batch']} violated the evidence-only review policy")
    out = {
        "batch": batch["batch"], "arm": batch["arm"], "result": result,
        "input_sha256": before, "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "native": receipt, "predictions": parsed["predictions"],
        "limitations": parsed["limitations"],
    }
    _write_text(published / "receipts" / f"{batch['batch']}.json", json.dumps(out, indent=1) + "\n")
    print(json.dumps({
        "batch": batch["batch"], "state": result["state"], "points": len(parsed["predictions"]),
        "run_id": result["run_id"], "models": receipt["response_models"],
    }), flush=True)
    return out


def render_report(summary: dict) -> str:
    lines = [
        "# Native CLIO controller comparison", "",
        f"Generated: {summary['generated_utc']}. Points per arm: {summary['points_per_arm']}.", "",
        "| Arm | Group | Points | Correct | Raw false accepts | Detectable raw false accepts |",
        "|---|---|---|---|---|---|",
    ]
    for arm, groups in summary["scores"].items():
        for group, values in groups.items():
            lines.append(
                f"| {arm} | {group} | {values['points']} | {values['correct']} | "
                f"{values['false_accept']} | {values['false_accept_detectable']} |"
            )
    lines += [
        "", "## Protocol and interpretation", "",
        "- Real bundled CLIO sessions made the judgments; "
        "no deterministic rule stood in for a model.",
        "- Each batch started a fresh session in an input-only working directory. "
        "C batches were scheduled first. Original point IDs and group labels were replaced "
        "with shared "
        "shuffled aliases; ground truth was loaded by the scorer only after all reviews "
        "completed.",
        "- B intentionally sees check outcomes and assessment verdicts. B accuracy is informed "
        "interpretation, not independent CFD validation. "
        "C sees measured values but no gate outputs, registered thresholds, or objective coverage; "
        "some failures are not identifiable from that packet.",
        "- Raw model judgments are ungated. They did not execute a solver, confirm assumptions, "
        "or change any frozen scientific decision. Compare their false accepts with the separately "
        "tested fixed/gated-adversary controls, not with live solver acceptance.",
        "- The input restriction is prompt-based with a tool-event audit, not an OS-enforced data "
        "sandbox. No claim is made that pretrained model knowledge has been blinded.",
        "- One pass per point/arm; no correctness feedback or answer tuning. This is a finite "
        "local comparison, not a statistical production guarantee.", "",
        "- Access-audit revision 2 recognizes a temporary overflow file only when a preceding "
        "successful permitted tool returned its exact creation receipt in the same session. "
        "Collection re-audits retained answers without additional model calls or correctness "
        "feedback; retain failed audit attempts separately.", "",
        "Protocol: [protocol.json](protocol.json). Complete scores: [summary.json](summary.json). "
        "Inputs, objectives, raw responses, and native model receipts are retained "
        "in sibling folders.", "",
    ]
    return "\n".join(lines)


def score_reviews(packets: Path, published: Path, reviews: list[dict], protocol: dict) -> dict:
    from discovery_physics.benchmarks.comparison import score_model

    hashes = protocol["source_packet_sha256"]
    if hashes != {arm: digest(packets / f"packets_{arm}.json") for arm in hashes}:
        raise ValueError("comparison source packets changed")
    if protocol["truth_sha256"] != digest(packets / "truth.json"):
        raise ValueError("comparison ground truth changed")
    aliases = protocol["aliases"]
    if ([r["batch"] for r in reviews] != protocol["batch_order"]
            or len({r["batch"] for r in reviews}) != len(reviews)):
        raise ValueError("missing native review batches")
    models = {model for r in reviews for model in r["native"]["response_models"]}
    if len(models) != 1:
        raise ValueError(f"arms did not share one response model: {sorted(models)}")
    scores, mismatches = {}, []
    truth = load_json(packets / "truth.json")
    for arm in ("B_full", "C_blind"):
        judgments = {aliases[p["point"]]: p["verdict"] for r in reviews if r["arm"] == arm
                     for p in r["predictions"]}
        scores[arm] = score_model(judgments, packets / "truth.json")
        for review in reviews:
            if review["arm"] != arm:
                continue
            for prediction in review["predictions"]:
                point = aliases[prediction["point"]]
                expected = truth[point]["truth"]
                decision = prediction["verdict"]
                normalized = (
                    "CORRECT_AND_RERUN" if decision == "NEEDS_MORE_RUNTIME" else decision
                )
                match = (
                    normalized != "ACCEPT" if expected == "NOT_ACCEPT" else normalized == expected
                )
                if not match:
                    mismatches.append({
                        "arm": arm, "point": point, "group": truth[point]["group"],
                        "truth": expected, "decision": decision,
                        "false_accept": decision == "ACCEPT" and expected != "ACCEPT",
                        "detectable": truth[point].get("detectable", True),
                        "rationale": prediction["rationale"],
                        "evidence_metrics": prediction["evidence_metrics"],
                    })
        _write_text(published / f"answers_{arm}.json", json.dumps(judgments, indent=1) + "\n")
    summary = {
        "generated_utc": datetime.now(UTC).isoformat(), "model": next(iter(models)),
        "points_per_arm": len(aliases), "scores": scores,
        "native_runs": [
            {"batch": r["batch"], "run_id": r["result"]["run_id"],
             "session_id": r["native"]["session_id"], "wall_s": r["result"]["wall_s"]}
            for r in reviews
        ],
        "policy_violations": 0, "protocol_sha256": digest(published / "protocol.json"),
        "audit_revision": 2, "mismatches": mismatches,
    }
    _write_text(published / "summary.json", json.dumps(summary, indent=1) + "\n")
    _write_text(published / "RESULTS.md", render_report(summary))
    return summary


def collect_comparison(packets: Path, published: Path, work: Path, *, source: Path) -> dict:
    """Recollect to a fresh destination; never overwrite a prior response or audit."""
    protocol = load_json(source / "protocol.json")
    batches = [load_json(source / "inputs" / f"{name}.json") for name in protocol["batch_order"]]
    if any(not isinstance(batch["batch"], str)
           or not re.fullmatch(r"[BC][0-9]{2}", batch["batch"]) for batch in batches):
        raise ValueError("Invalid comparison batch identifier")
    published.mkdir(parents=True, exist_ok=False)
    for name in ("inputs", "objectives", "responses", "receipts"):
        (published / name).mkdir()
    _write_bytes(published / "protocol.json", (source / "protocol.json").read_bytes())
    for batch in batches:
        name = batch["batch"]
        _write_bytes(published / "inputs" / f"{name}.json",
                     (source / "inputs" / f"{name}.json").read_bytes())
        objective_file = source / "objectives" / f"{name}.txt"
        if objective_file.is_file():
            _write_bytes(published / "objectives" / f"{name}.txt", objective_file.read_bytes())
    reviews = [collect_batch(batch, work, published) for batch in batches]
    return score_reviews(packets, published, reviews, protocol)


def run_comparison(packets: Path, published: Path, *, seed: int, batch_size: int,
                   jobs: int, timeout: float, work_root: Path | None = None,
                   env: dict[str, str] | None = None) -> dict:
    if jobs not in (1, 2):
        raise ValueError("review concurrency must be 1 or 2")
    if published.exists() or published.is_symlink():
        raise FileExistsError("Output exists; retain prior attempts and choose a new directory")
    files = {arm: packets / f"packets_{arm}.json" for arm in ("B_full", "C_blind")}
    aliases, batches = prepare_batches(load_json(files["B_full"]), load_json(files["C_blind"]),
                                       seed=seed, batch_size=batch_size)
    published.mkdir(parents=True, exist_ok=False)
    for name in ("inputs", "objectives", "responses", "receipts"):
        (published / name).mkdir()
    parent = work_root if work_root is not None else published / "work"
    parent = parent.expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="clio-", dir=parent)).resolve()
    hashes = {arm: digest(path) for arm, path in files.items()}
    truth_hash = digest(packets / "truth.json")  # Hash only; never supplied to a session.
    protocol = {"revision": 1, "registered_utc": datetime.now(UTC).isoformat(),
                "seed": seed, "batch_size": batch_size, "points_per_arm": len(aliases),
                "jobs": jobs, "timeout_per_batch_s": timeout, "source_packet_sha256": hashes,
                "truth_sha256": truth_hash, "aliases": aliases,
                "batch_order": [b["batch"] for b in batches], "label_set": sorted(VERDICTS),
                "group_and_original_point_ids_supplied": False, "raw_model_judgments": True,
                "correctness_feedback": False, "os_enforced_blinding": False}
    _write_text(published / "protocol.json", json.dumps(protocol, indent=1) + "\n")
    try:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            def review(batch):
                if env is None:
                    return review_batch(batch, work, published, timeout)
                return review_batch(batch, work, published, timeout, env=env)

            reviews = list(pool.map(review, batches))
        return score_reviews(packets, published, reviews, protocol)
    except Exception as exc:
        _write_text(published / "failure.json", json.dumps({
            "error_type": type(exc).__name__, "error": str(exc),
        }, indent=1) + "\n")
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "collect"))
    add_arguments(parser)
    parser.add_argument("--packets", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261122)
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--source", type=Path, help="Collect: existing published inputs/protocol")
    parser.add_argument("--work-root", type=Path,
                        help="Results-contained parent for new native review work stores")
    args = parser.parse_args(argv)
    try:
        paths = ResultPaths(args.project_root, args.results_dir)
        output = paths.output(args.out)
        packets = paths.input(args.packets)
        work_root = paths.output(args.work_root or output / "work", new=False)
        env = paths.child_env()
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    if args.action == "collect":
        if args.work is None or args.source is None:
            parser.error("collect requires --work and --source for the existing native receipts")
        result = collect_comparison(packets, output, paths.input(args.work),
                                    source=paths.input(args.source))
    else:
        result = run_comparison(
            packets, output, seed=args.seed, batch_size=args.batch_size,
            jobs=args.jobs, timeout=args.timeout, work_root=work_root, env=env,
        )
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())