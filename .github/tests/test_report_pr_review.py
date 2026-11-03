"""Behavioral tests for the untrusted-artifact / privileged-reporting boundary."""

from __future__ import annotations

from copy import deepcopy
import io
import json
import subprocess
from typing import Any
import zipfile

import pytest

import report_pr_review as reporting


REPOSITORY = "microsoft/discovery"
ROOT = f"repos/{REPOSITORY}"
HEAD_SHA = "a" * 40


def archive_for(report: Any, filename: str = reporting.REPORT_FILE) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(filename, json.dumps(report))
    return buffer.getvalue()


def failure(**changes: Any) -> dict[str, Any]:
    return {
        "rule_id": "POL-016", "file": "agents/example/README.md", "line": 2,
        "message": "Invalid content.", "remediation": "Correct the content.",
        "docs": "docs/authoring-guides/agent-authoring-guide.md#images",
        **changes,
    }


class FakeGitHub(reporting.GitHub):
    def __init__(self) -> None:
        self.repository = {"id": 1, "full_name": REPOSITORY}
        self.head_repository = {"id": 2, "owner": {"login": "contributor"}}
        self.run = {
            "id": 12, "repository": self.repository, "workflow_id": 88,
            "path": reporting.WORKFLOW_PATH, "event": "pull_request",
            "status": "completed", "conclusion": "success", "run_attempt": 1,
            "run_number": 10, "head_repository": self.head_repository,
            "head_sha": HEAD_SHA, "head_branch": "feature/reporting", "pull_requests": [],
        }
        self.event = {"repository": self.repository, "workflow_run": deepcopy(self.run)}
        self.workflow = {"id": 88, "path": reporting.WORKFLOW_PATH}
        self.pr = {
            "number": 17, "state": "open",
            "base": {"repo": self.repository, "ref": "main", "sha": "b" * 40},
            "head": {"repo": self.head_repository, "ref": "feature/reporting", "sha": HEAD_SHA},
        }
        self.prs = [self.pr]
        self.runs = [self.run]
        self.jobs = [
            {"name": name, "status": "completed", "conclusion": "success", "run_attempt": 1}
            for name in sorted(reporting.REQUIRED_JOBS)
        ]
        self.report = {"passed": True, "failure_count": 0, "failures": []}
        self.artifacts = [{
            "id": 90, "name": "pr-review-report-1", "expired": False,
            "size_in_bytes": 1000, "workflow_run": {
                "id": 12, "repository_id": 1, "head_repository_id": 2,
                "head_branch": "feature/reporting", "head_sha": HEAD_SHA,
            },
        }]
        self.files = [{"filename": "agents/example/README.md"}]
        self.labels = [{"name": "human-label"}, {"name": "pr-validation-failed"}]
        self.existing_labels = [{"name": label} for label in reporting.LABELS]
        self.reviews: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str, Any]] = []
        self.archive: bytes | None = None
        self.on_download = lambda: None
        self.fail_inline = False
        self.fail_summary = False

    @property
    def writes(self) -> list[tuple[str, str, Any]]:
        return [call for call in self.calls if call[0] != "GET"]

    def request(
        self, endpoint: str, *, method: str = "GET",
        payload: dict[str, Any] | None = None, raw: bool = False,
        paginate: bool = False,
    ) -> Any:
        self.calls.append((method, endpoint, payload))
        path = endpoint.partition("?")[0]
        if method != "GET":
            if (self.fail_inline and path.endswith("/reviews")) or (
                self.fail_summary and path.endswith("/comments")
            ):
                raise subprocess.CalledProcessError(1, ["gh", "api"], stderr=b"HTTP 422: rejected")
            return {}
        if raw:
            assert path == f"{ROOT}/actions/artifacts/90/zip"
            self.on_download()
            return self.archive if self.archive is not None else archive_for(self.report)
        responses = {
            f"{ROOT}/actions/runs/12": self.run,
            f"{ROOT}/actions/workflows/pr-review.yml": self.workflow,
            f"{ROOT}/actions/workflows/88/runs": {"workflow_runs": self.runs},
            f"{ROOT}/pulls": self.prs,
            f"{ROOT}/pulls/17": self.pr,
            f"{ROOT}/pulls/17/files": self.files,
            f"{ROOT}/pulls/17/reviews": self.reviews,
            f"{ROOT}/actions/runs/12/jobs": {"jobs": self.jobs},
            f"{ROOT}/actions/runs/12/artifacts": {"artifacts": self.artifacts},
            f"{ROOT}/issues/17/labels": self.labels,
            f"{ROOT}/labels": self.existing_labels,
        }
        assert path in responses, f"Unexpected API request: {endpoint}"
        response = deepcopy(responses[path])
        return [response] if paginate else response

    def publish(self) -> None:
        reporting.report_run(self, self.event, REPOSITORY, "https://github.com")

    def failed_validation(self, failures: list[dict[str, Any]]) -> None:
        self.report.update(passed=False, failure_count=len(failures), failures=failures)
        self.run["conclusion"] = "failure"
        next(job for job in self.jobs if job["name"] == "Validate PR")["conclusion"] = "failure"


@pytest.mark.parametrize("fork", [True, False])
def test_current_fork_and_same_repository_runs_publish_without_pr_payload(fork):
    api = FakeGitHub()
    if not fork:
        api.head_repository["id"] = 1
        api.head_repository["owner"]["login"] = "microsoft"
        api.artifacts[0]["workflow_run"]["head_repository_id"] = 1
    api.publish()

    assert api.event["workflow_run"]["pull_requests"] == []
    assert ("DELETE", f"{ROOT}/issues/17/labels/pr-validation-failed", None) in api.writes
    assert ("POST", f"{ROOT}/issues/17/labels", {"labels": ["pr-validation-passed"]}) in api.writes
    assert all("human-label" not in endpoint for _, endpoint, _ in api.writes)
    assert not any(endpoint.endswith("/comments") for _, endpoint, _ in api.writes)
    lookup = next(endpoint for _, endpoint, _ in api.calls if endpoint.startswith(f"{ROOT}/pulls?"))
    assert "feature%2Freporting" in lookup


@pytest.mark.parametrize("field,value", [
    ("event", "push"), ("status", "in_progress"),
    ("workflow_id", 99), ("path", ".github/workflows/other.yml"),
    ("repository", {"id": 999}),
])
def test_wrong_source_run_is_rejected_before_writes(field, value):
    api = FakeGitHub()
    api.run[field] = value
    with pytest.raises(reporting.ReportError, match="Source"):
        api.publish()
    assert not api.writes


def test_wrong_event_repository_and_workflow_identity_are_rejected():
    api = FakeGitHub()
    api.event["repository"] = {"id": 999, "full_name": "attacker/repo"}
    with pytest.raises(reporting.ReportError, match="another repository"):
        api.publish()
    api = FakeGitHub()
    api.workflow["path"] = ".github/workflows/other.yml"
    with pytest.raises(reporting.ReportError, match="Source"):
        api.publish()
    assert not api.writes


def test_artifact_routing_fields_and_arbitrary_labels_are_ignored():
    api = FakeGitHub()
    api.report.update(pr_number=999, head_sha="c" * 40, labels=["approved", "skip-validation"])
    api.publish()
    assert ("POST", f"{ROOT}/issues/17/labels", {"labels": ["pr-validation-passed"]}) in api.writes
    assert not any("/999/" in endpoint for _, endpoint, _ in api.writes)
    assert not any("skip-validation" in str(payload) for _, _, payload in api.writes)


def test_ambiguous_pr_association_is_rejected():
    api = FakeGitHub()
    api.prs.append({**api.pr, "number": 999})
    with pytest.raises(reporting.ReportError, match="unique"):
        api.publish()
    assert not api.writes


@pytest.mark.parametrize("change", [
    "closed", "head_sha", "head_repository", "head_branch", "base_branch", "base_repository",
])
def test_nonmatching_closed_and_superseded_prs_are_skipped(change, capsys):
    api = FakeGitHub()
    if change == "closed":
        api.pr["state"] = "closed"
    elif change == "head_sha":
        api.pr["head"]["sha"] = "c" * 40
    elif change == "head_repository":
        api.pr["head"]["repo"] = {"id": 999}
    elif change == "head_branch":
        api.pr["head"]["ref"] = "another-branch"
    elif change == "base_branch":
        api.pr["base"]["ref"] = "another-base"
    else:
        api.pr["base"]["repo"] = {"id": 999}
    api.publish()
    assert not api.writes
    assert "::notice::" in capsys.readouterr().out


@pytest.mark.parametrize("change", ["cancelled", "attempt", "newer_run", "deleted_fork"])
def test_cancelled_and_superseded_runs_do_not_publish(change):
    api = FakeGitHub()
    if change == "cancelled":
        api.run["conclusion"] = "cancelled"
    elif change == "attempt":
        api.run["run_attempt"] = 2
    elif change == "deleted_fork":
        api.run["head_repository"] = None
    else:
        api.runs.append({
            **api.run, "id": 13, "run_number": 11, "status": "in_progress",
            "pull_requests": [{"number": 17, "base": {"ref": "main"}}],
        })
    api.publish()
    assert not api.writes


def test_newer_run_from_another_fork_cannot_suppress_reporting():
    api = FakeGitHub()
    api.runs.append({
        **api.run, "id": 13, "run_number": 11, "head_repository": {"id": 999},
    })
    api.publish()
    assert api.writes


@pytest.mark.parametrize("association", [
    {"number": 18, "base": {"ref": "main"}},
    {"number": 17, "base": {"ref": "release/catalog"}},
    {},
])
def test_newer_run_for_another_pr_or_base_cannot_suppress_reporting(association):
    api = FakeGitHub()
    api.runs.append({
        **api.run, "id": 13, "run_number": 11,
        "pull_requests": [association],
    })
    api.publish()
    assert api.writes


@pytest.mark.parametrize("change", ["head", "closed", "attempt", "newer_run"])
def test_freshness_is_rechecked_after_downloading_untrusted_data(change):
    api = FakeGitHub()

    def supersede():
        if change == "head":
            api.pr["head"]["sha"] = "c" * 40
        elif change == "closed":
            api.pr["state"] = "closed"
        elif change == "attempt":
            api.run["run_attempt"] = 2
        else:
            api.runs.append({
                **api.run, "id": 13, "run_number": 11,
                "pull_requests": [{"number": 17, "base": {"ref": "main"}}],
            })

    api.on_download = supersede
    api.publish()
    assert not api.writes


def test_partial_rerun_uses_current_handoff_and_latest_result_for_each_job():
    api = FakeGitHub()
    api.run["run_attempt"] = api.event["workflow_run"]["run_attempt"] = 2
    api.jobs.extend([
        {"name": "Secret Scan", "status": "completed", "conclusion": "success", "run_attempt": 2},
        {"name": "Post Results", "status": "completed", "conclusion": "success", "run_attempt": 2},
    ])
    next(job for job in api.jobs if job["name"] == "Secret Scan")["conclusion"] = "failure"
    api.artifacts[0]["name"] = "pr-review-report-2"
    api.publish()
    assert ("POST", f"{ROOT}/issues/17/labels", {"labels": ["pr-validation-passed"]}) in api.writes


@pytest.mark.parametrize("change", [
    "missing", "duplicate", "expired", "large", "wrong_run", "old_attempt",
    "wrong_repository", "wrong_fork", "wrong_branch", "wrong_sha",
])
def test_invalid_artifact_provenance_is_rejected(change):
    api = FakeGitHub()
    if change == "missing":
        api.artifacts = []
    elif change == "duplicate":
        api.artifacts.append(deepcopy(api.artifacts[0]))
    elif change == "expired":
        api.artifacts[0]["expired"] = True
    elif change == "large":
        api.artifacts[0]["size_in_bytes"] = reporting.MAX_REPORT_BYTES + 1
    elif change == "wrong_run":
        api.artifacts[0]["workflow_run"]["id"] = 999
    elif change == "old_attempt":
        api.artifacts[0]["name"] = "pr-review-report-0"
    else:
        field = {
            "wrong_repository": "repository_id", "wrong_fork": "head_repository_id",
            "wrong_branch": "head_branch", "wrong_sha": "head_sha",
        }[change]
        api.artifacts[0]["workflow_run"][field] = "wrong"
    with pytest.raises(reporting.ReportError, match="attempt-scoped"):
        api.publish()
    assert not api.writes


@pytest.mark.parametrize("change", ["missing", "duplicate", "unfinished"])
def test_missing_ambiguous_or_unfinished_required_jobs_are_rejected(change):
    api = FakeGitHub()
    if change == "missing":
        api.jobs.pop()
    elif change == "duplicate":
        api.jobs.append(deepcopy(api.jobs[0]))
    else:
        api.jobs[0]["status"] = "queued"
    with pytest.raises(reporting.ReportError):
        api.publish()
    assert not api.writes


@pytest.mark.parametrize("report", [
    [], {"passed": "true", "failure_count": 0, "failures": []},
    {"passed": True, "failure_count": True, "failures": []},
    {"passed": True, "failure_count": 1, "failures": []},
    {"passed": True, "failure_count": 1, "failures": [failure()]},
    {"passed": True, "failure_count": 0, "failures": [], "has_images": "true"},
    {"passed": False, "failure_count": 1, "failures": ["invalid"]},
    {"passed": False, "failure_count": 1, "failures": [failure(line=True)]},
    {"passed": False, "failure_count": 1, "failures": [failure(line=0)]},
    {"passed": False, "failure_count": 1, "failures": [failure(message={})]},
    {"passed": False, "failure_count": 1, "failures": [failure(message="")]},
    {"passed": False, "failure_count": 1, "failures": [failure(message="a" * 16_001)]},
    {"passed": False, "failure_count": 1, "failures": [failure(docs="https://attacker.example")]},
    {"passed": False, "failure_count": 1, "failures": [failure(docs="docs/../../secret")]},
])
def test_hostile_report_shapes_are_rejected_before_any_privileged_action(report):
    api = FakeGitHub()
    api.report = report
    with pytest.raises(reporting.ReportError):
        api.publish()
    assert not api.writes


@pytest.mark.parametrize("filename", ["../validation-results.json", "script.py", "nested/validation-results.json"])
def test_archive_paths_are_not_extracted_or_accepted(filename, monkeypatch):
    api = FakeGitHub()
    api.archive = archive_for(api.report, filename)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", lambda *_: pytest.fail("Archive extracted"))
    with pytest.raises(reporting.ReportError):
        api.publish()
    assert not api.writes


def test_duplicate_zip_members_zip_bombs_and_invalid_json_are_rejected(monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        zipped.writestr(reporting.REPORT_FILE, "{}")
        zipped.writestr("extra.py", "raise Exception('must not execute')")
    with pytest.raises(reporting.ReportError):
        reporting.read_report(buffer.getvalue())
    monkeypatch.setattr(reporting, "MAX_REPORT_BYTES", 1000)
    with pytest.raises(reporting.ReportError):
        reporting.read_report(archive_for("x" * 1001))
    with pytest.raises(reporting.ReportError):
        reporting.read_report(b"x" * 1001)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        zipped.writestr(reporting.REPORT_FILE, "{invalid")
    with pytest.raises(json.JSONDecodeError):
        reporting.read_report(buffer.getvalue())


@pytest.mark.parametrize("paths,expected", [
    (["README.md"], []),
    (["docs/schemas/schema.json"], ["docs-only"]),
    (["docs/schemas/schema.json", "README.md"], []),
    (["agents/example/README.md"], [
        "1p-contribution", "3p-contribution", "markdown-only",
        "contains-dockerfile", "contains-code", "needs-image-review",
    ]),
    (["starter-kits/example/kit.json"], [
        "1p-contribution", "3p-contribution", "markdown-only",
        "contains-dockerfile", "contains-code", "needs-image-review",
    ]),
])
def test_classification_and_image_labels_are_limited_to_catalog_changes(paths, expected):
    report = {flag: True for flag in reporting.CLASSIFICATION_FLAGS}
    files = [{"filename": path} for path in paths]
    assert reporting.labels_for(report, files, True) == expected + ["pr-validation-passed"]


def test_failure_feedback_is_comment_only_commit_pinned_and_actionable():
    api = FakeGitHub()
    api.files = [{"filename": f"docs/file-{i}.md"} for i in range(150)] + api.files
    api.failed_validation([failure(), failure(file="outside-diff.md")])
    api.publish()
    review = next(payload for _, endpoint, payload in api.writes if endpoint.endswith("/reviews"))
    assert review["event"] == "COMMENT"
    assert review["commit_id"] == HEAD_SHA
    assert len(review["comments"]) == 1
    assert review["comments"][0]["line"] == 2
    assert "**How to fix:**" in review["comments"][0]["body"]
    assert "**Guidance:**" in review["comments"][0]["body"]
    summary = next(payload["body"] for _, endpoint, payload in api.writes if endpoint.endswith("/comments"))
    assert "outside-diff.md" in summary
    assert "/blob/" + "b" * 40 + "/docs/" in summary
    assert "/actions/runs/12" in summary
    assert not any("APPROVE" in str(payload) or "REQUEST_CHANGES" in str(payload) for _, _, payload in api.writes)


@pytest.mark.parametrize("source_success", [True, False])
def test_artifact_cannot_turn_a_failed_or_skipped_secret_scan_into_passing_labels(source_success):
    api = FakeGitHub()
    api.run["conclusion"] = "success" if source_success else "failure"
    next(job for job in api.jobs if job["name"] == "Secret Scan")["conclusion"] = "failure"
    api.publish()
    assert ("POST", f"{ROOT}/issues/17/labels", {"labels": ["pr-validation-failed"]}) in api.writes
    summary = next(payload["body"] for _, endpoint, payload in api.writes if endpoint.endswith("/comments"))
    assert "SEC-SCAN" in summary


def test_missing_labels_are_created_without_changing_any_review_state():
    api = FakeGitHub()
    api.existing_labels = []
    api.reviews = [
        {"id": 1, "state": "CHANGES_REQUESTED", "user": {"login": "github-actions[bot]"}},
        {"id": 2, "state": "CHANGES_REQUESTED", "user": {"login": "other[bot]"}},
        {"id": 3, "state": "CHANGES_REQUESTED", "user": {"login": "human"}},
    ]
    api.publish()
    assert any(endpoint == f"{ROOT}/labels" for _, endpoint, _ in api.writes)
    assert not any("/reviews" in endpoint for _, endpoint, _ in api.writes)


def test_failed_source_with_a_passing_report_cannot_apply_a_passing_label():
    api = FakeGitHub()
    api.run["conclusion"] = "failure"
    api.publish()
    assert ("POST", f"{ROOT}/issues/17/labels", {"labels": ["pr-validation-failed"]}) in api.writes
    summary = next(payload["body"] for _, endpoint, payload in api.writes if endpoint.endswith("/comments"))
    assert "WORKFLOW" in summary


def test_untrusted_text_is_literal_and_feedback_stays_within_api_limits():
    api = FakeGitHub()
    text = "<script>alert(1)</script> @maintainers | [click](https://attacker.example) $(echo unsafe)\n"
    api.failed_validation([failure(message=text * 100, remediation=text * 100) for _ in range(100)])
    api.publish()
    review = next(payload for _, endpoint, payload in api.writes if endpoint.endswith("/reviews"))
    assert len(review["comments"]) == reporting.MAX_INLINE_COMMENTS
    assert all(len(comment["body"]) <= reporting.MAX_COMMENT_CHARS for comment in review["comments"])
    summary = next(payload["body"] for _, endpoint, payload in api.writes if endpoint.endswith("/comments"))
    assert len(summary) <= reporting.MAX_COMMENT_CHARS
    assert "<script>" not in summary
    assert "@maintainers" not in summary
    assert "Additional findings omitted" in summary
    assert "&#124;" in summary


def test_failed_inline_feedback_warns_and_keeps_summary_but_summary_failure_is_an_error(capsys):
    api = FakeGitHub()
    api.failed_validation([failure()])
    api.fail_inline = True
    api.publish()
    assert "::warning::" in capsys.readouterr().out
    assert any(endpoint.endswith("/comments") for _, endpoint, _ in api.writes)
    api = FakeGitHub()
    api.failed_validation([failure()])
    api.fail_summary = True
    with pytest.raises(subprocess.CalledProcessError):
        api.publish()


def test_cli_reads_event_file_and_surfaces_invalid_artifacts(tmp_path, monkeypatch, capsys):
    api = FakeGitHub()
    path = tmp_path / "event.json"
    path.write_text(json.dumps(api.event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setattr(reporting, "GitHub", lambda: api)
    assert reporting.main() == 0
    api.archive = b"not a zip file"
    api.calls.clear()
    assert reporting.main() == 1
    assert "::error::" in capsys.readouterr().err
    assert not api.writes


def test_github_cli_uses_argument_arrays_binary_artifacts_and_paginated_json(monkeypatch):
    calls = []

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        if command[2].endswith("/zip"):
            return subprocess.CompletedProcess(command, 0, stdout=b"zip bytes")
        if "--paginate" in command:
            return subprocess.CompletedProcess(command, 0, stdout=b'[[{"name":"first"}],[{"name":"second"}]]')
        return subprocess.CompletedProcess(command, 0, stdout=b"")

    monkeypatch.setattr(subprocess, "run", execute)
    api = reporting.GitHub()
    assert api.request("repos/example/artifacts/90/zip", raw=True) == b"zip bytes"
    assert api.pages("repos/example/labels") == [{"name": "first"}, {"name": "second"}]
    assert api.request("repos/example/labels/old", method="DELETE") is None
    api.request("repos/example/comments", method="POST", payload={"body": "$(do not execute)"})
    assert calls[-1][1]["input"] == b'{"body": "$(do not execute)"}'
    assert "--input" in calls[-1][0]
    assert all("shell" not in kwargs and kwargs["check"] for _, kwargs in calls)
