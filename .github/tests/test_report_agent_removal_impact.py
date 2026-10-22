"""Offline tests of the removal profile at the privileged reporting boundary."""

from copy import deepcopy
import io
import json
import struct
import subprocess
import zipfile

import pytest

from agent_removal_report import REPORT_FILE, result
import report_pr_review as reporting
from test_report_pr_review import FakeGitHub, ROOT, archive_for


pytestmark = pytest.mark.usefixtures("removal_offline")


def blocked_report():
    return result(
        "blocked", removed_paths=["agents/old"],
        impacted_kits=[{"path": "starter-kits/example", "required_refs": ["agents/old"]}],
        issues=["starter-kits/example still requires agents/old."],
        reason="Repository policy limits Option B to non-fork PRs. Use Option A.",
    )


class RemovalGitHub(FakeGitHub):
    def __init__(self):
        super().__init__()
        self.run["path"] = self.workflow["path"] = reporting.AGENT_REMOVAL.path
        self.event["workflow_run"] = deepcopy(self.run)
        self.jobs = [{
            "name": next(iter(reporting.AGENT_REMOVAL.required_jobs)), "status": "completed",
            "conclusion": "failure", "run_attempt": 1,
        }]
        self.run["conclusion"] = "failure"
        self.report = blocked_report()
        self.artifacts[0]["name"] = "agent-removal-report-1"

    def request(self, endpoint, **kwargs):
        if endpoint == f"{ROOT}/actions/workflows/check-agent-removal-impact.yml":
            self.calls.append(("GET", endpoint, None))
            return deepcopy(self.workflow)
        if kwargs.get("raw") and self.archive is None:
            self.archive = archive_for(self.report, REPORT_FILE)
        return super().request(endpoint, **kwargs)


@pytest.mark.parametrize("fork", [False, True])
@pytest.mark.parametrize("base", ["main", "release/catalog"])
def test_current_removal_posts_only_an_issue_comment_for_each_branch_and_origin(fork, base):
    api = RemovalGitHub()
    api.pr["base"]["ref"] = base
    if not fork:
        api.head_repository["id"] = 1
        api.head_repository["owner"]["login"] = "microsoft"
        api.artifacts[0]["workflow_run"]["head_repository_id"] = 1
    api.publish()
    assert api.event["workflow_run"]["pull_requests"] == []
    assert [(method, path) for method, path, _ in api.writes] == [
        ("POST", f"{ROOT}/issues/17/comments"),
    ]
    body = api.writes[0][2]["body"]
    assert "Agent Removal Blocked" in body and "starter-kits/example" in body
    assert "agents/old" in body and "/actions/runs/12" in body
    assert "Option A" in body and "Option B" in body
    lookup = next(path for _, path, _ in api.calls if path.startswith(f"{ROOT}/pulls?"))
    assert "base=" not in lookup


@pytest.mark.parametrize("outcome", ["success", "not_applicable"])
def test_success_and_explicit_noop_make_no_privileged_mutations(outcome):
    api = RemovalGitHub()
    api.report = result(outcome)
    api.run["conclusion"] = api.jobs[0]["conclusion"] = "success"
    api.publish()
    assert not api.writes


def test_cross_base_ambiguity_is_not_guessed():
    api = RemovalGitHub()
    another = deepcopy(api.pr)
    another["number"], another["base"]["ref"] = 999, "release/catalog"
    api.prs.append(another)
    with pytest.raises(reporting.ReportError, match="unique"):
        api.publish()
    assert not api.writes


def test_retargeted_base_after_download_is_stale():
    api = RemovalGitHub()
    def retarget():
        api.pr["base"]["ref"] = "release/other"
    api.on_download = retarget
    api.publish()
    assert not api.writes


@pytest.mark.parametrize("change", [
    "repository", "event", "workflow_id", "path", "descriptor", "unfinished",
    "missing_job", "duplicate_job", "unfinished_job", "wrong_job",
    "missing_artifact", "duplicate_artifact", "expired", "large", "old_attempt",
    "origin_id", "origin_repository_id", "origin_head_repository_id", "origin_head_branch",
    "origin_head_sha", "other_profile",
])
def test_wrong_sources_jobs_and_artifact_provenance_never_write(change):
    api = RemovalGitHub()
    if change == "repository":
        api.run["repository"] = {"id": 999}
    elif change == "event":
        api.run["event"] = "pull_request_target"
    elif change == "workflow_id":
        api.run["workflow_id"] = 999
    elif change == "path":
        api.run["path"] = ".github/workflows/arbitrary.yml"
    elif change == "descriptor":
        api.workflow["path"] = reporting.WORKFLOW_PATH
    elif change == "unfinished":
        api.run["status"] = "in_progress"
    elif change == "missing_job":
        api.jobs = []
    elif change == "duplicate_job":
        api.jobs.append(deepcopy(api.jobs[0]))
    elif change == "unfinished_job":
        api.jobs[0]["status"] = "queued"
    elif change == "wrong_job":
        api.jobs[0]["name"] = "Validate PR"
    elif change == "missing_artifact":
        api.artifacts = []
    elif change == "duplicate_artifact":
        api.artifacts.append(deepcopy(api.artifacts[0]))
    elif change == "expired":
        api.artifacts[0]["expired"] = True
    elif change == "large":
        api.artifacts[0]["size_in_bytes"] = reporting.MAX_REPORT_BYTES + 1
    elif change == "old_attempt":
        api.artifacts[0]["name"] = "agent-removal-report-0"
    elif change.startswith("origin_"):
        api.artifacts[0]["workflow_run"][change.removeprefix("origin_")] = "wrong"
    else:
        api.archive = archive_for(api.report)
    with pytest.raises(reporting.ReportError):
        api.publish()
    assert not api.writes


@pytest.mark.parametrize("change", ["closed", "head", "fork", "branch", "attempt", "cancelled", "newer", "deleted"])
@pytest.mark.parametrize("after_download", [False, True])
def test_stale_sources_skip_without_writes(change, after_download):
    api = RemovalGitHub()
    def supersede():
        if change == "closed":
            api.pr["state"] = "closed"
        elif change == "head":
            api.pr["head"]["sha"] = "c" * 40
        elif change == "fork":
            api.pr["head"]["repo"] = {"id": 999}
        elif change == "branch":
            api.pr["head"]["ref"] = "other"
        elif change == "attempt":
            api.run["run_attempt"] = 2
        elif change == "cancelled":
            api.run["conclusion"] = "cancelled"
        elif change == "deleted":
            api.run["head_repository"] = None
        else:
            api.runs.append({
                **api.run, "id": 13, "run_number": 11,
                "pull_requests": [{"number": 17, "base": {"ref": "main"}}],
            })
    if after_download:
        api.on_download = supersede
    else:
        supersede()
    api.publish()
    assert not api.writes


def test_partial_rerun_selects_current_job_and_attempt_report():
    api = RemovalGitHub()
    api.run["run_attempt"] = api.event["workflow_run"]["run_attempt"] = 2
    api.jobs.append({**api.jobs[0], "run_attempt": 2})
    api.jobs[0]["conclusion"] = "success"
    api.artifacts[0]["name"] = "agent-removal-report-2"
    api.publish()
    assert len(api.writes) == 1


@pytest.mark.parametrize("outcome", ["success", "not_applicable", "blocked", "error"])
@pytest.mark.parametrize("contradiction", ["job", "run"])
def test_report_cannot_contradict_api_conclusions(outcome, contradiction):
    api = RemovalGitHub()
    api.report = blocked_report() if outcome == "blocked" else result(
        outcome, issues=["Setup failed."] if outcome == "error" else [],
    )
    expected = "success" if api.report["exit_code"] == 0 else "failure"
    api.jobs[0]["conclusion"] = api.run["conclusion"] = expected
    if contradiction == "job":
        api.jobs[0]["conclusion"] = "failure" if expected == "success" else "success"
    else:
        api.run["conclusion"] = "failure" if expected == "success" else "success"
    with pytest.raises(reporting.ReportError, match="contradicts"):
        api.publish()
    assert not api.writes


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2), ("outcome", []),
    ("outcome", "approved"), ("exit_code", True), ("exit_code", 0),
    ("removed_paths", ["agents/../old"]), ("removed_paths", ["agents\\old"]),
    ("removed_paths", ["agents/old", "agents/old"]), ("removed_paths", [{}]),
    ("impacted_kits", [{"path": "starter-kits/../other", "required_refs": ["agents/old"]}]),
    ("impacted_kits", [{"path": "starter-kits/example", "required_refs": ["agents/unknown"]}]),
    ("impacted_kits", []), ("issues", []), ("issues", [False]),
    ("override", {"approved": True, "reason": "Override accepted."}),
    ("override", {"approved": "false", "reason": "No."}),
    ("guidance", "https://attacker.example"), ("guidance", "docs/../../secret"),
    pytest.param("guidance", "docs/" + "a" * 60_000, id="oversized-guidance"),
])
def test_invalid_removal_schema_rejected_before_writes(field, value):
    api = RemovalGitHub()
    api.report[field] = value
    with pytest.raises(reporting.ReportError):
        api.publish()
    assert not api.writes


def test_unknown_routing_and_label_fields_have_no_authority():
    api = RemovalGitHub()
    api.report.update(pr_number=999, labels=["arbitrary-label"], handler="pr-review", override_approved=True)
    api.publish()
    assert [(method, path) for method, path, _ in api.writes] == [("POST", f"{ROOT}/issues/17/comments")]
    assert all("arbitrary-label" not in str(payload) for _, _, payload in api.writes)


def test_comment_failure_is_an_explicit_error():
    api = RemovalGitHub()
    api.fail_summary = True
    with pytest.raises(subprocess.CalledProcessError):
        api.publish()
    assert len(api.writes) == 1 and api.jobs[0]["conclusion"] == "failure"


def test_untrusted_removal_details_are_literal_bounded_and_truncation_visible():
    api = RemovalGitHub()
    text = "<script>alert(1)</script> @maintainers | [click](https://attacker.example) $(echo unsafe)"
    api.report["issues"] = [text] * 1000
    api.publish()
    body = api.writes[0][2]["body"]
    assert len(body) <= reporting.MAX_COMMENT_CHARS
    assert "<script>" not in body and "@maintainers" not in body
    assert "&#124;" in body and "Additional findings omitted" in body
    assert "/actions/runs/12" in body


@pytest.mark.parametrize("expanded", [True, False])
def test_real_zip_limits_at_boundary_and_boundary_plus_one(monkeypatch, expanded):
    api = RemovalGitHub()
    api.report["override"]["reason"] = "r" * 2000
    archive = archive_for(api.report, REPORT_FILE)
    if not expanded:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as zipped:
            zipped.writestr(REPORT_FILE, json.dumps(api.report))
        archive = buffer.getvalue()
    size = len(json.dumps(api.report).encode()) if expanded else len(archive)
    monkeypatch.setattr(reporting, "MAX_REPORT_BYTES", size)
    assert reporting.read_report(archive, reporting.AGENT_REMOVAL)["outcome"] == "blocked"
    if expanded:
        monkeypatch.setattr(reporting, "MAX_REPORT_BYTES", size - 1)
    else:
        archive += b"x"
    with pytest.raises(reporting.ReportError):
        reporting.read_report(archive, reporting.AGENT_REMOVAL)


@pytest.mark.parametrize("expanded", [True, False])
def test_actual_five_mib_boundary_through_reporting_entry_point(expanded):
    api = RemovalGitHub()
    limit = 5 * 1024 * 1024
    assert reporting.MAX_REPORT_BYTES == limit
    raw = json.dumps(api.report).encode()
    def pack(data):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
            zipped.writestr(REPORT_FILE, data)
        return buffer.getvalue()
    if expanded:
        raw += b" " * (limit - len(raw))
        archive, oversized = pack(raw), pack(raw + b" ")
    else:
        zipped = pack(raw)
        archive = b"\0" * (limit - len(zipped)) + zipped
        oversized = b"\0" + archive
    api.archive = archive
    api.artifacts[0]["size_in_bytes"] = len(archive)
    api.publish()
    assert len(api.writes) == 1
    api.calls.clear()
    api.archive = oversized
    with pytest.raises(reporting.ReportError):
        api.publish()
    assert not api.writes


@pytest.mark.parametrize("length", [16_000, 16_001])
def test_removal_string_limit(length):
    api = RemovalGitHub()
    api.report["override"]["reason"] = "r" * length
    if length == 16_000:
        api.publish()
        assert len(api.writes) == 1
    else:
        with pytest.raises(reporting.ReportError):
            api.publish()
        assert not api.writes


@pytest.mark.parametrize("kind", ["nested", "traversal", "multiple", "invalid_json", "encrypted", "unsupported"])
def test_hostile_zips_never_extract_or_write(kind, monkeypatch):
    api = RemovalGitHub()
    buffer = io.BytesIO()
    compression = zipfile.ZIP_BZIP2 if kind == "unsupported" else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(buffer, "w", compression=compression) as zipped:
        name = {"nested": f"nested/{REPORT_FILE}", "traversal": f"../{REPORT_FILE}"}.get(kind, REPORT_FILE)
        zipped.writestr(name, "{" if kind == "invalid_json" else json.dumps(api.report))
        if kind == "multiple":
            zipped.writestr("execute.py", "raise RuntimeError('must not execute')")
    data = bytearray(buffer.getvalue())
    if kind == "encrypted":
        struct.pack_into("<H", data, 6, 1)
        struct.pack_into("<H", data, data.index(b"PK\x01\x02") + 8, 1)
    api.archive = bytes(data)
    def extracted(*args, **kwargs):
        pytest.fail("Untrusted ZIP was extracted")
    monkeypatch.setattr(zipfile.ZipFile, "extract", extracted)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", extracted)
    with pytest.raises((reporting.ReportError, ValueError)):
        api.publish()
    assert not api.writes
