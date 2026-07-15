"""End-to-end agent evaluation pipeline.

Given a project, an agent, and one or more evaluation suites, the pipeline:
  1. Resolves each suite's dataset (project-specific first, then default/).
  2. Drives the ONLINE agent against every dataset query through the Discovery
     workspace data-plane (DiscoveryAgentClient), capturing each response.
  3. Converts each captured response into a well-formed offline-eval row
     (tool_call_id restored from call_id; ground-truth fields carried through).
  4. Assembles a Foundry-compatible combined dataset with the suite's selected
     evaluators and triggers a Foundry eval over it.
  5. Returns a structured EvaluationResult (per-suite status, criteria summary,
     artifact paths, and an overall exit code).

Why this path (not bare Foundry agent eval / native traces): Discovery agents
depend on Discovery-runtime tools the bare Foundry eval service cannot execute
(live re-invocation hangs), and the OTel trace projection drops the tool-call
correlation id (server-side traces error on tool-using agents). Capturing live
responses through the data-plane and scoring them offline sidesteps both modes
while still exercising the online agent against the user's chosen dataset.

Programmatic use:
    from pipeline import EvaluationPipeline
    pipeline = EvaluationPipeline(
        workspace_api_url="https://<your-workspace>.workspace.discovery.azure.com",
        discovery_project="Literature-Research",
        foundry_project_endpoint="<foundry-project-endpoint>",
        datasets_dir="../datasets",
        dataset_project="literature-agent",
        llm_judge_model_deployment_name="gpt-5.4-mini",
    )
    result = pipeline.run(agent="LiteratureAgent", suites="shared,tool-calling,retrieval")
    print(result.exit_code, result.summary())

CLI use (a CI workflow can invoke this):
    python pipeline.py \
        --workspace-api-url https://<your-workspace>.workspace.discovery.azure.com \
        --foundry-project-endpoint <foundry-project-endpoint> \
        --discovery-project Literature-Research \
        --agent LiteratureAgent \
        --datasets-dir ../datasets \
        --dataset-project literature-agent \
        --suites shared,tool-calling,retrieval \
        --llm-judge-model-deployment-name gpt-5.4-mini \
        --output-dir ./out \
        --fail-on errored

Auth: the data-plane uses DefaultAzureCredential with the
  https://discovery.azure.com/.default audience (override with --scope, or pass a
  raw token via --token / DISCOVERY_TOKEN). The Foundry evaluation uses
  AIProjectClient with DefaultAzureCredential. Both work under the same service
  principal when the workflow exports AZURE_CLIENT_ID / AZURE_TENANT_ID / etc.
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Allow importing sibling modules whether run as a script from any working
# directory (the pipeline may be invoked by absolute path).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from azure.ai.projects import AIProjectClient  # noqa: E402

from azure_credential import get_credential  # noqa: E402
from discovery_client import (  # noqa: E402
    DEFAULT_API_VERSION,
    DEFAULT_SCOPE,
    DiscoveryAgentClient,
)
from eval_datasets import (  # noqa: E402
    build_dataset,
    discover_suites,
    ground_truth_fields,
    make_investigation_name,
    parse_suites,
    resolve_dataset,
)
from responses_to_eval_dataset import response_to_row  # noqa: E402
from run_offline_eval import (  # noqa: E402
    build_testing_criteria,
    clean_row,
    execute_eval,
    report,
)


@dataclass
class SuiteResult:
    """Outcome of evaluating one suite."""
    suite: str
    status: str                      # completed | failed | canceled | no-captures | no-evaluators | no-dataset
    errored: int = 0
    criteria: dict = field(default_factory=dict)
    captures_path: str | None = None
    dataset_path: str | None = None
    results_path: str | None = None
    queries: int = 0
    captured: int = 0


@dataclass
class EvaluationResult:
    """Aggregate outcome returned to the caller."""
    project: str
    agent: str
    investigation: str
    suites: list[SuiteResult]
    exit_code: int

    def summary(self) -> dict:
        """Compact JSON-serializable summary keyed by suite."""
        return {
            "project": self.project,
            "agent": self.agent,
            "investigation": self.investigation,
            "exit_code": self.exit_code,
            "suites": {
                s.suite: {
                    "status": s.status,
                    "errored": s.errored,
                    "criteria": s.criteria,
                    "queries": s.queries,
                    "captured": s.captured,
                    "results": s.results_path,
                }
                for s in self.suites
            },
        }


class EvaluationPipeline:
    """Orchestrates live capture + Foundry scoring for one Discovery project.

    One pipeline instance targets a single project (data-plane + Foundry). Call
    ``run`` per agent/suite selection; reuse the instance across agents.
    """

    def __init__(self, *, workspace_api_url: str, discovery_project: str,
                 foundry_project_endpoint: str, datasets_dir, dataset_project: str,
                 llm_judge_model_deployment_name: str | None = None, token: str | None = None,
                 scope: str = DEFAULT_SCOPE, api_version: str = DEFAULT_API_VERSION,
                 poll_seconds: int = 600, poll_interval: int = 3,
                 eval_poll_seconds: int = 900):
        self.discovery_project = discovery_project
        self.dataset_project = dataset_project
        self.datasets_dir = Path(datasets_dir)
        self.llm_judge_model_deployment_name = llm_judge_model_deployment_name
        self.poll_seconds = poll_seconds
        self.poll_interval = poll_interval
        self.eval_poll_seconds = eval_poll_seconds

        self.client = DiscoveryAgentClient(
            workspace_api_url, token, scope=scope, api_version=api_version)
        self.foundry = AIProjectClient(
            endpoint=foundry_project_endpoint, credential=get_credential())

    # -- discovery ----------------------------------------------------------
    def available_suites(self) -> list[str]:
        """Suites this project supports (data-driven from dataset files)."""
        return discover_suites(self.datasets_dir, self.dataset_project)

    # -- main entry point ---------------------------------------------------
    def run(self, agent: str, suites: str, *, investigation: str | None = None,
            investigation_prefix: str = "eval", max_queries: int = 0,
            fail_on: str = "errored", output_dir=None) -> EvaluationResult:
        """Evaluate ``agent`` across the selected ``suites`` and return results.

        ``suites`` is a comma-separated selection or 'all'. A fresh investigation
        is created per run unless ``investigation`` is supplied. When
        ``output_dir`` is given, captures/datasets/results/summary are persisted
        there for audit.
        """
        available = self.available_suites()
        selected = parse_suites(suites, available)
        if not selected:
            raise ValueError(
                f"no valid suites selected (available for "
                f"'{self.dataset_project}': {', '.join(available) or '(none)'})")

        out_dir = Path(output_dir) if output_dir else None
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)

        investigation = self._ensure_investigation(
            agent, investigation, investigation_prefix)

        suite_results: list[SuiteResult] = []
        exit_code = 0
        for suite in selected:
            print(f"\n=== Suite: {suite} ===")
            result = self._run_suite(
                suite, agent, investigation, max_queries, fail_on, out_dir)
            suite_results.append(result)
            if result.status in ("failed", "canceled") or result.errored:
                if fail_on != "none":
                    exit_code = 2

        eval_result = EvaluationResult(
            project=self.discovery_project, agent=agent,
            investigation=investigation, suites=suite_results, exit_code=exit_code,
        )
        if out_dir:
            (out_dir / "summary.json").write_text(
                json.dumps({"generated": int(time.time()), **eval_result.summary()}, indent=2),
                encoding="utf-8")
            print(f"\nWrote run summary -> {out_dir / 'summary.json'}")
        return eval_result

    # -- internals ----------------------------------------------------------
    def _ensure_investigation(self, agent, investigation, prefix) -> str:
        """Reuse a given investigation, else mint and PUT-create a fresh one."""
        if investigation:
            print(f"Using existing investigation: {investigation}")
            return investigation
        investigation = make_investigation_name(prefix, agent)
        print(f"Creating investigation for this run: {investigation}")
        self.client.create_investigation(
            self.discovery_project, investigation,
            display_name=f"Agent evaluation: {agent}")
        return investigation

    def _capture_responses(self, agent, investigation, src_rows, max_queries):
        """Invoke the live agent once per dataset query.

        Returns (eval_rows, captures): eval_rows are Foundry-ready rows, captures
        are the raw responses kept for audit.
        """
        eval_rows = []
        captures = []
        rows = src_rows if max_queries <= 0 else src_rows[:max_queries]
        for idx, src_row in enumerate(rows, start=1):
            query = src_row.get("query")
            if not query:
                print(f"  [{idx}/{len(rows)}] skipped row without 'query'")
                continue
            gt = ground_truth_fields(src_row)
            print(f"  [{idx}/{len(rows)}] invoking agent: {query[:80]!r}")
            try:
                response, conv_id = self.client.invoke(
                    self.discovery_project, investigation, agent, query,
                    poll_seconds=self.poll_seconds, poll_interval=self.poll_interval)
            except SystemExit as exc:
                print(f"      ERROR invoking agent (skipped): {exc}")
                continue
            status = response.get("status")
            if status != "completed":
                print(f"      WARNING: terminal status '{status}' "
                      f"(error={response.get('error')}); still scoring captured output")
            captures.append({
                "query": query,
                "conversation_id": conv_id,
                "status": status,
                "response": response,
            })
            eval_rows.append(response_to_row(response, query, gt))
        return eval_rows, captures

    def _run_suite(self, suite, agent, investigation, max_queries, fail_on,
                   out_dir) -> SuiteResult:
        """Resolve, capture, build dataset, and score one suite."""
        dataset_path = resolve_dataset(suite, self.datasets_dir, self.dataset_project)
        if dataset_path is None:
            return SuiteResult(suite=suite, status="no-dataset")
        config = json.loads(dataset_path.read_text(encoding="utf-8"))
        src_rows = config.get("data", [])
        if not src_rows:
            print(f"  WARNING: dataset {dataset_path} has no data rows -- skipping")
            return SuiteResult(suite=suite, status="no-dataset")
        print(f"  dataset: {dataset_path} ({len(src_rows)} queries)")

        eval_rows, captures = self._capture_responses(
            agent, investigation, src_rows, max_queries)
        result = SuiteResult(suite=suite, status="no-captures",
                             queries=len(src_rows), captured=len(eval_rows))
        if not eval_rows:
            print(f"  WARNING: no responses captured for suite '{suite}' -- skipping eval")
            return result

        if out_dir:
            captures_path = out_dir / f"captures-{suite}.json"
            captures_path.write_text(json.dumps(captures, indent=2), encoding="utf-8")
            result.captures_path = str(captures_path)

        dataset = build_dataset(suite, config, eval_rows, self.llm_judge_model_deployment_name)
        if out_dir:
            dataset_out = out_dir / f"dataset-{suite}.json"
            dataset_out.write_text(json.dumps(dataset, indent=2), encoding="utf-8")
            result.dataset_path = str(dataset_out)

        criteria = build_testing_criteria(dataset, self.llm_judge_model_deployment_name)
        if not criteria:
            print(f"  WARNING: no evaluators configured for suite '{suite}' -- skipping")
            result.status = "no-evaluators"
            return result

        clean_rows = [clean_row(r) for r in eval_rows]
        run, summary, errored, item_errors = execute_eval(
            self.foundry, f"investigation:{suite}", clean_rows, criteria,
            self.eval_poll_seconds)

        results_path = str(out_dir / f"results-{suite}.json") if out_dir else None
        report(run, summary, errored, item_errors, results_path, fail_on)
        result.status = run.status
        result.errored = errored
        result.criteria = summary
        result.results_path = results_path
        return result


def main() -> int:
    """CLI entry point (a CI workflow can invoke this)."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # Workspace (live invocation) target.
    parser.add_argument("--workspace-api-url", required=True,
                        help="Discovery workspace API URL (the workspace data-plane base "
                             "URL). Find it in the Azure portal on your "
                             "Microsoft.Discovery/workspaces resource, or via 'az resource "
                             "show'. Format: https://<your-workspace>.workspace.discovery.azure.com")
    parser.add_argument("--discovery-project", required=True,
                        help="Discovery project name used by the data-plane")
    parser.add_argument("--investigation", default=None,
                        help="Investigation id to run the queries in. If omitted, a fresh "
                             "investigation is created per agent for this run")
    parser.add_argument("--investigation-prefix", default="eval",
                        help="Prefix for the auto-generated investigation id (default 'eval')")
    parser.add_argument("--agent", required=True,
                        help="Agent name (agent_reference) to invoke")
    # Foundry (evaluation) target.
    parser.add_argument("--foundry-project-endpoint", required=True,
                        help="Foundry project endpoint URL for running evaluators")
    parser.add_argument("--llm-judge-model-deployment-name", default=None,
                        help="Foundry model deployment used by the LLM-judge / custom evaluators")
    # Dataset / suite selection (end-user choices).
    parser.add_argument("--datasets-dir", required=True,
                        help="Root datasets directory (contains default/ and per-project dirs)")
    parser.add_argument("--dataset-project", required=True,
                        help="Dataset subdirectory to prefer (e.g. literature-agent)")
    parser.add_argument("--suites", required=True,
                        help="Comma-separated suites to evaluate, or 'all'. A suite "
                             "'<name>' is backed by a '<name>-evaluators.json' dataset "
                             "(e.g. shared, tool-calling, retrieval)")
    parser.add_argument("--max-queries", type=int, default=0,
                        help="Cap queries invoked per suite (0 = no cap)")
    # Run control.
    parser.add_argument("--output-dir", required=True,
                        help="Directory for captured responses, datasets, and results")
    parser.add_argument("--fail-on", choices=["errored", "failed", "none"],
                        default="errored",
                        help="Non-zero exit when items error (default), any criterion "
                             "fails, or never")
    parser.add_argument("--api-version", default=DEFAULT_API_VERSION,
                        help=f"Data-plane API version (default {DEFAULT_API_VERSION})")
    parser.add_argument("--scope", default=DEFAULT_SCOPE,
                        help=f"AAD token scope for the data-plane (default {DEFAULT_SCOPE})")
    parser.add_argument("--token", default=None,
                        help="Raw data-plane bearer token (overrides --scope / DISCOVERY_TOKEN)")
    parser.add_argument("--poll-seconds", type=int, default=600,
                        help="Max seconds to wait for each agent response (default 600)")
    parser.add_argument("--poll-interval", type=int, default=3,
                        help="Seconds between response polls (default 3)")
    parser.add_argument("--eval-poll-seconds", type=int, default=900,
                        help="Max seconds to wait for each Foundry eval run (default 900)")
    args = parser.parse_args()

    pipeline = EvaluationPipeline(
        workspace_api_url=args.workspace_api_url,
        discovery_project=args.discovery_project,
        foundry_project_endpoint=args.foundry_project_endpoint,
        datasets_dir=args.datasets_dir,
        dataset_project=args.dataset_project,
        llm_judge_model_deployment_name=args.llm_judge_model_deployment_name,
        token=args.token,
        scope=args.scope,
        api_version=args.api_version,
        poll_seconds=args.poll_seconds,
        poll_interval=args.poll_interval,
        eval_poll_seconds=args.eval_poll_seconds,
    )

    try:
        result = pipeline.run(
            agent=args.agent,
            suites=args.suites,
            investigation=args.investigation,
            investigation_prefix=args.investigation_prefix,
            max_queries=args.max_queries,
            fail_on=args.fail_on,
            output_dir=args.output_dir,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
