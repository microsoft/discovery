"""Offline (captured-response) evaluation runner.

Runs Foundry built-in / custom evaluators over a dataset of PRE-CAPTURED agent
responses, with NO live agent target. Use this for Microsoft Discovery agents,
whose tools (knowledge bases, GetResourceContext, PreviewResource, and any
custom Discovery-managed tools) only execute inside the Discovery runtime and
therefore cannot be invoked by the bare Foundry evaluation service. When the
eval service tries to invoke such an agent it emits a single unresolved tool
call, returns an empty answer, and every dataset item ERRORS (the bare Foundry
agent-evaluation flow then hangs to its timeout).

Workflow:
  1. Run the agent inside Discovery (portal / runtime) and capture each response
     (final text, tool calls, retrieved documents) into the dataset's `data`
     rows -- e.g. a `retrieved_documents` field for retrieval evaluators.
  2. Point evaluator `data_mapping` entries at the captured columns using
     `{{item.<field>}}` (NOT `{{sample.<field>}}`, which only exists when a live
     agent target generates a completion).
  3. Run this script. It creates a Foundry eval with a STATIC JSONL data source
     and reports per-criteria results -- the agent is never invoked.

Dataset schema (two differences from a live-agent eval dataset):
  - `data_mapping` uses `{{item.*}}` instead of `{{sample.*}}`.
  - each `data` row carries the captured fields the evaluators consume.

Optional `evaluator_parameters` maps an evaluator name to its
initialization_parameters (e.g. {"builtin.groundedness": {"deployment_name": "gpt-4o"}}).

Usage:
    python run_offline_eval.py \
        --endpoint <project-endpoint> \
        --data-path <dataset.json> \
        [--deployment-name <model-deployment>] \
        [--poll-seconds 900] \
        [--fail-on errored|failed|none] \
        [--output results.json]
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai.types.eval_create_params import DataSourceConfigCustom

# Builtin metric evaluators that do NOT take a model deployment (no LLM judge).
# Everything else gets deployment_name auto-injected when --deployment-name is
# supplied and the dataset does not override it via evaluator_parameters.
NO_DEPLOYMENT_EVALUATORS = {
    "builtin.document_retrieval",
}

_SAMPLE_REF = re.compile(r"\{\{\s*sample\.")


def _short_name(evaluator: str) -> str:
    """Turn 'builtin.tool_call_accuracy' into a criterion name 'tool_call_accuracy'."""
    return evaluator.split(".", 1)[-1]


def _clean_row(row: dict) -> dict:
    """Drop documentation-only keys (leading underscore) from a data row."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def _build_item_schema(rows):
    """Permissive object schema covering every key present in the data rows."""
    props = {}
    for row in rows:
        for key in row:
            props.setdefault(key, {})
    return {"type": "object", "properties": props, "required": []}


def _normalize_data_mapping(mapping: dict) -> dict:
    """Rewrite any {{sample.x}} reference to {{item.x}} for offline evaluation."""
    fixed = {}
    for field, ref in mapping.items():
        if isinstance(ref, str) and _SAMPLE_REF.search(ref):
            new_ref = _SAMPLE_REF.sub("{{item.", ref)
            print(
                f"  note: remapping '{field}': '{ref}' -> '{new_ref}' "
                "(offline runs have no live sample)"
            )
            fixed[field] = new_ref
        else:
            fixed[field] = ref
    return fixed


def _testing_criteria(dataset: dict, deployment_name: str | None):
    evaluators = dataset.get("evaluators", [])
    data_mapping = _normalize_data_mapping(dataset.get("data_mapping", {}))
    explicit_params = dataset.get("evaluator_parameters", {})

    criteria = []
    for evaluator in evaluators:
        criterion = {
            "type": "azure_ai_evaluator",
            "name": _short_name(evaluator),
            "evaluator_name": evaluator,
        }
        if data_mapping:
            criterion["data_mapping"] = data_mapping

        if evaluator in explicit_params:
            init = dict(explicit_params[evaluator])
            if deployment_name and "deployment_name" not in init:
                init["deployment_name"] = deployment_name
            criterion["initialization_parameters"] = init
        elif deployment_name and evaluator not in NO_DEPLOYMENT_EVALUATORS:
            criterion["initialization_parameters"] = {
                "deployment_name": deployment_name
            }

        criteria.append(criterion)
    return criteria


def _aggregate(output_items):
    """Aggregate per-criterion pass/fail/errors and collect error messages.

    Errors can surface at two levels:
      - item level: item["status"] == "error" or item["error"];
      - result level: results[i]["status"] == "error" with the message under
        results[i]["sample"]["error"] (this is how trace-scenario evaluator
        failures, e.g. malformed tool_call content, are reported).
    """
    per_criterion = {}
    errored = 0
    item_errors = []

    for raw in output_items:
        item = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        item_status = item.get("status")
        item_error = item.get("error")
        item_counted = False
        if item_status == "error" or item_error:
            errored += 1
            item_counted = True
            item_errors.append(
                {"id": item.get("id"), "error": item_error or item_status}
            )

        item_has_result_error = False
        for result in item.get("results", []) or []:
            name = result.get("name") or result.get("metric") or "unknown"
            bucket = per_criterion.setdefault(
                name, {"passed": 0, "failed": 0, "errored": 0, "scores": []}
            )
            sample = result.get("sample") or {}
            result_error = result.get("status") == "error" or sample.get("error")
            if result_error:
                bucket["errored"] += 1
                item_has_result_error = True
                err = sample.get("error") or result.get("status")
                msg = err.get("message") if isinstance(err, dict) else err
                item_errors.append(
                    {"id": item.get("id"), "criterion": name, "error": msg}
                )
                continue

            passed = result.get("passed")
            if passed is True:
                bucket["passed"] += 1
            elif passed is False:
                bucket["failed"] += 1
            score = result.get("score")
            if isinstance(score, (int, float)):
                bucket["scores"].append(float(score))

        if item_has_result_error and not item_counted:
            errored += 1

    summary = {}
    for name, bucket in per_criterion.items():
        scores = bucket["scores"]
        summary[name] = {
            "passed": bucket["passed"],
            "failed": bucket["failed"],
            "errored": bucket["errored"],
            "avg_score": (sum(scores) / len(scores)) if scores else None,
        }
    return summary, errored, item_errors


def execute_eval(project, name, rows, criteria, poll_seconds):
    """Create a Foundry eval with a static JSONL data source, run it over `rows`,
    poll to completion, and return (run, summary, errored, item_errors).

    The agent is never invoked: `rows` already carry the captured/extracted
    fields the evaluators consume.
    """
    oai = project.get_openai_client()
    data_source_config = DataSourceConfigCustom(
        type="custom",
        item_schema=_build_item_schema(rows),
        include_sample_schema=False,
    )
    eval_object = oai.evals.create(
        name=name,
        data_source_config=data_source_config,  # type: ignore[arg-type]
        testing_criteria=criteria,  # type: ignore[arg-type]
    )
    print(f"created eval {eval_object.id} ({len(criteria)} criteria, {len(rows)} rows)")

    data_source = {
        "type": "jsonl",
        "source": {
            "type": "file_content",
            "content": [{"item": row} for row in rows],
        },
    }
    run = oai.evals.runs.create(
        eval_id=eval_object.id,
        name=f"{name}-{int(time.time())}",
        data_source=data_source,  # type: ignore[arg-type]
    )
    print(f"created eval run {run.id} status={run.status}")
    return poll_run(oai, eval_object.id, run, poll_seconds)


def poll_run(oai, eval_id, run, poll_seconds):
    """Poll an eval run to completion and return (run, summary, errored, item_errors).

    Shared by the offline (static JSONL) and trace (azure_ai_traces) runners.
    """
    start = time.time()
    last = None
    while time.time() - start < poll_seconds:
        run = oai.evals.runs.retrieve(run_id=run.id, eval_id=eval_id)
        line = f"[{int(time.time() - start):4d}s] status={run.status} {run.result_counts}"
        if line != last:
            print(line, flush=True)
            last = line
        if run.status in ("completed", "failed", "canceled"):
            break
        time.sleep(10)
    else:
        raise TimeoutError(f"run still {run.status} after {poll_seconds}s")

    output_items = oai.evals.runs.output_items.list(run_id=run.id, eval_id=eval_id)
    summary, errored, item_errors = _aggregate(output_items)
    return run, summary, errored, item_errors


def report(run, summary, errored, item_errors, output, fail_on):
    """Print results, optionally write a JSON report, and return an exit code."""
    print("\n=== Results ===")
    print(f"run status: {run.status}")
    for crit, stats in sorted(summary.items()):
        avg = stats["avg_score"]
        avg_str = f"{avg:.3f}" if avg is not None else "n/a"
        print(
            f"  {crit:32s} passed={stats['passed']:<3d} "
            f"failed={stats['failed']:<3d} errored={stats.get('errored', 0):<3d} "
            f"avg_score={avg_str}"
        )
    if errored:
        print(f"\n  ERRORED items: {errored}")
        for err in item_errors[:10]:
            print(f"    - {err['id']}: {err['error']}")

    if output:
        Path(output).write_text(
            json.dumps(
                {
                    "run_id": run.id,
                    "eval_id": run.eval_id,
                    "status": run.status,
                    "criteria": summary,
                    "errored": errored,
                    "item_errors": item_errors,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {output}")

    total_failed = sum(s["failed"] for s in summary.values())
    if fail_on == "errored" and errored:
        return 2
    if fail_on == "failed" and (errored or total_failed):
        return 2
    return 0


# Public aliases for reuse by the evaluation pipeline (stable names).
clean_row = _clean_row
build_testing_criteria = _testing_criteria


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Foundry evaluators over pre-captured agent responses "
        "(no live agent target)."
    )
    parser.add_argument("--endpoint", required=True, help="Foundry project endpoint URL.")
    parser.add_argument("--data-path", required=True, help="Dataset JSON file.")
    parser.add_argument(
        "--deployment-name",
        default=None,
        help="Model deployment for LLM-judge evaluators (auto-injected unless "
        "the dataset overrides it via evaluator_parameters).",
    )
    parser.add_argument("--poll-seconds", type=int, default=900)
    parser.add_argument(
        "--fail-on",
        choices=["errored", "failed", "none"],
        default="errored",
        help="Non-zero exit when items error (default), when any criterion "
        "fails, or never.",
    )
    parser.add_argument("--output", default=None, help="Optional results JSON path.")
    args = parser.parse_args()

    dataset = json.loads(Path(args.data_path).read_text(encoding="utf-8"))
    rows = [_clean_row(r) for r in dataset.get("data", [])]
    if not rows:
        print(f"ERROR: no data rows in {args.data_path}", file=sys.stderr)
        return 1

    criteria = _testing_criteria(dataset, args.deployment_name)
    if not criteria:
        print(f"ERROR: no evaluators in {args.data_path}", file=sys.stderr)
        return 1

    project = AIProjectClient(
        endpoint=args.endpoint, credential=DefaultAzureCredential()
    )

    name = dataset.get("name", Path(args.data_path).stem)
    try:
        run, summary, errored, item_errors = execute_eval(
            project, f"offline:{name}", rows, criteria, args.poll_seconds
        )
    except TimeoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return report(run, summary, errored, item_errors, args.output, args.fail_on)


if __name__ == "__main__":
    raise SystemExit(main())
