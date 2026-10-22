"""Real gate bytes -> workflow finalizer -> ZIP -> trusted reporter, offline."""

import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest
import yaml

import agent_removal_report as protocol
import report_pr_review as reporting
from test_check_agent_removal_impact import RecordingHTTP, invoke_gate, make_catalog
from test_report_agent_removal_impact import RemovalGitHub, ROOT


pytestmark = pytest.mark.usefixtures("removal_offline")
WORKFLOW = Path(__file__).resolve().parents[1] / "workflows" / "check-agent-removal-impact.yml"


def workflow_steps():
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    return workflow["jobs"]["check-impact"]["steps"]


def run_workflow_script(root, name, *, classification="success", relevant="true",
                        gate="failure", files=(), prepare=True, no_python=False):
    trusted_script = root / "trusted" / ".github" / "scripts" / "agent_removal_report.py"
    if prepare:
        trusted_script.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(protocol.__file__, trusted_script)
    script = next(step["with"]["script"] for step in workflow_steps() if step["name"] == name)
    # Execute the actual inline JS with fake action bindings, not a reimplementation.
    harness = r"""
const fs = require('fs');
const {spawnSync} = require('child_process');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
Object.assign(process.env, input.env);
const failures = [], outputs = {}, commands = [], notices = [];
const core = {
  setFailed: message => failures.push(message),
  setOutput: (key, value) => outputs[key] = value,
  notice: message => notices.push(message),
};
const exec = {exec: async (command, args, options) => {
  if (input.no_python) throw new Error('Skipped Python setup must not be required');
  commands.push([command, ...args]);
  const result = spawnSync(input.python, args, {encoding: 'utf8'});
  return result.status === null ? 1 : result.status;
}};
const github = {
  rest: {pulls: {listFiles: {}}},
  paginate: async () => input.files,
};
const context = {repo: {owner: 'microsoft', repo: 'discovery'}, issue: {number: 17}};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('require', 'process', 'core', 'exec', 'github', 'context', input.script)(
  require, process, core, exec, github, context
).then(() => console.log(JSON.stringify({failures, outputs, commands, notices})))
 .catch(error => { console.error(error); process.exitCode = 1; });
"""
    process = subprocess.run(
        ["node", "-e", harness], input=json.dumps({
            "script": script, "python": sys.executable, "files": list(files),
            "no_python": no_python, "env": {
                "RUNNER_TEMP": str(root / "runtime"),
                "CLASSIFICATION_OUTCOME": classification, "RELEVANT": relevant,
                "GATE_OUTCOME": gate,
            },
        }),
        cwd=root, capture_output=True, text=True,
    )
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def local_report_path(root):
    return root / "runtime" / "agent-removal-report" / protocol.REPORT_FILE


@pytest.mark.parametrize("case", [
    "blocked", "no_removal", "replacement", "archived", "deleted_kit", "optional",
    "flag_removed", "override", "fork_override", "error",
])
def test_actual_gate_bytes_survive_workflow_handoff_and_reporter(tmp_path, monkeypatch, case, record_property):
    trusted, head = make_catalog(tmp_path, case)
    if case == "error":
        (trusted / ".auto-registry" / "agent-registry.json").write_text("{", encoding="utf-8")
    http = RecordingHTTP()
    monkeypatch.setattr("urllib.request.urlopen", http)
    extra = ["--github-token", "fixture-token"] if case in {"override", "fork_override"} else []
    if case == "fork_override":
        extra.append("--is-fork")
    code, report = invoke_gate(monkeypatch, trusted, head, extra=extra)
    raw = (tmp_path / "report.json").read_bytes()
    target = local_report_path(tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(raw)
    handoff = run_workflow_script(
        tmp_path, "Finalize removal report", gate="failure" if code else "success",
    )
    assert not handoff["failures"]
    assert target.read_bytes() == raw
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(protocol.REPORT_FILE, target.read_bytes())
    api = RemovalGitHub()
    api.archive = buffer.getvalue()
    api.artifacts[0]["size_in_bytes"] = len(api.archive)
    api.jobs[0]["conclusion"] = api.run["conclusion"] = "failure" if code else "success"
    api.publish()
    expected_failure = case in {"blocked", "fork_override", "error"}
    assert code == (1 if expected_failure else 0)
    assert report["outcome"] == ("error" if case == "error" else "blocked" if expected_failure else "success")
    assert [(method, path) for method, path, _ in api.writes] == (
        [("POST", f"{ROOT}/issues/17/comments")] if expected_failure else []
    )
    manifest = {
        "case": case, "gate_exit": code, "schema_outcome": report["outcome"],
        "source_job_conclusion": api.jobs[0]["conclusion"], "reporter_outcome": "completed",
        "captured_mutations": [{"method": method, "target": path} for method, path, _ in api.writes],
    }
    evidence = tmp_path / "case-manifest.json"
    evidence.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    record_property("fixture_case_manifest", str(evidence))


def test_noop_does_not_need_checkout_or_python_and_round_trips(tmp_path):
    handoff = run_workflow_script(
        tmp_path, "Finalize removal report", relevant="false", gate="skipped",
        prepare=False, no_python=True,
    )
    report = protocol.validate_report(json.loads(local_report_path(tmp_path).read_bytes()))
    assert report["outcome"] == "not_applicable" and not handoff["failures"]
    assert not handoff["commands"] and not (tmp_path / "trusted").exists()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        zipped.writestr(protocol.REPORT_FILE, local_report_path(tmp_path).read_bytes())
    api = RemovalGitHub()
    api.archive = buffer.getvalue()
    api.run["conclusion"] = api.jobs[0]["conclusion"] = "success"
    api.publish()
    assert not api.writes


@pytest.mark.parametrize("classification,relevant,gate", [
    ("failure", "", "skipped"), ("success", "", "skipped"),
    ("success", "unknown", "skipped"), ("failure", "false", "skipped"),
    ("success", "true", "skipped"),
])
def test_classification_and_setup_failures_are_errors_without_python(tmp_path, classification, relevant, gate):
    handoff = run_workflow_script(
        tmp_path, "Finalize removal report", classification=classification,
        relevant=relevant, gate=gate, prepare=False, no_python=True,
    )
    report = protocol.validate_report(json.loads(local_report_path(tmp_path).read_bytes()))
    assert handoff["failures"] and report["outcome"] == "error"
    assert report["exit_code"] == 1 and not handoff["commands"]


@pytest.mark.parametrize("problem", ["missing", "invalid_json", "invalid_schema", "contradictory", "old_base"])
def test_missing_invalid_or_unsupported_local_results_fail_closed(tmp_path, problem):
    target = local_report_path(tmp_path)
    target.parent.mkdir(parents=True)
    if problem == "invalid_json":
        target.write_text("{", encoding="utf-8")
    elif problem == "invalid_schema":
        target.write_text('{"schema_version": 1, "outcome": "success", "exit_code": 0}', encoding="utf-8")
    elif problem in {"contradictory", "old_base"}:
        target.write_text(json.dumps(protocol.result("success")), encoding="utf-8")
    # The untrusted copy is a sentinel, never a fallback for an unprepared base.
    untrusted = tmp_path / "pr" / ".github" / "scripts" / "agent_removal_report.py"
    untrusted.parent.mkdir(parents=True)
    untrusted.write_text("raise RuntimeError('PR code executed')", encoding="utf-8")
    handoff = run_workflow_script(
        tmp_path, "Finalize removal report", prepare=problem != "old_base",
        gate="failure" if problem == "contradictory" else "success",
    )
    report = protocol.validate_report(json.loads(target.read_bytes()))
    assert handoff["failures"] and report["outcome"] == "error"
    assert len(handoff["commands"]) == 1
    assert handoff["commands"][0][1] == "trusted/.github/scripts/agent_removal_report.py"


@pytest.mark.parametrize("files,expected", [
    ([], "false"), ([{"filename": "README.md"}], "false"),
    ([{"filename": "agents/old/metadata.yaml"}], "true"),
    ([{"filename": "docs/old.yaml", "previous_filename": "agents/old/metadata.yaml"}], "true"),
])
def test_actual_classification_covers_renames_out_of_agents(tmp_path, files, expected):
    observed = run_workflow_script(tmp_path, "Detect relevant changes", files=files, prepare=False, no_python=True)
    assert observed["outputs"] == {"relevant": expected}


@pytest.mark.parametrize("reporting_mode", ["disabled", "denied", "missing_artifact"])
def test_reporting_failure_never_changes_computed_gate_decision(tmp_path, monkeypatch, reporting_mode):
    trusted, head = make_catalog(tmp_path)
    code, report = invoke_gate(monkeypatch, trusted, head)
    before = (tmp_path / "report.json").read_bytes()
    api = RemovalGitHub()
    if reporting_mode == "denied":
        api.fail_summary = True
        with pytest.raises(subprocess.CalledProcessError):
            api.publish()
    elif reporting_mode == "missing_artifact":
        api.artifacts = []
        with pytest.raises(reporting.ReportError):
            api.publish()
        assert not api.writes
    assert code == 1 and report["outcome"] == "blocked"
    assert before == (tmp_path / "report.json").read_bytes()
