#!/usr/bin/env python3
"""Trusted workflow_run publisher for PR Review and Check Agent Removal Impact.

Invoked by pr-review-report.yml from the default-branch checkout, using GH_TOKEN
and the standard GITHUB_EVENT_PATH/GITHUB_REPOSITORY/GITHUB_SERVER_URL values.
Fixed source profiles verify provenance, current-head freshness, jobs and
bounded data-only artifacts; artifacts never choose a handler or target PR.

Only the PR Review profile manages diagnostic labels and COMMENT reviews.
Removal results produce issue comments for blocked/errors only. Neither profile
approves, dismisses reviews or merges, and this job is not a required PR check.
"""

from __future__ import annotations

import html
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any
from urllib.parse import quote, urlencode
import zipfile

from agent_removal_report import REPORT_FILE as REMOVAL_REPORT_FILE, validate_report as validate_removal_report


WORKFLOW_PATH = ".github/workflows/pr-review.yml"
REPORT_FILE = "validation-results.json"
MAX_REPORT_BYTES = 5 * 1024 * 1024
MAX_COMMENT_CHARS = 60_000
MAX_INLINE_COMMENTS = 50
REQUIRED_JOBS = {"Classify Changed Paths", "Validate PR", "Secret Scan", "Post Results"}


@dataclass(frozen=True)
class SourceProfile:
    """Trusted dispatch contract; never populated from an artifact."""

    path: str
    required_jobs: frozenset[str]
    artifact_prefix: str
    report_file: str
    base_branch: str | None


PR_REVIEW = SourceProfile(
    WORKFLOW_PATH, frozenset(REQUIRED_JOBS), "pr-review-report", REPORT_FILE, "main",
)
AGENT_REMOVAL = SourceProfile(
    ".github/workflows/check-agent-removal-impact.yml",
    frozenset({"Check if agent removal breaks starter kits"}),
    "agent-removal-report", REMOVAL_REPORT_FILE, None,
)
SOURCES = {profile.path: profile for profile in (PR_REVIEW, AGENT_REMOVAL)}

LABELS = {
    "pr-validation-passed": ("0e8a16", "PR validation passed; other required checks report separately."),
    "pr-validation-failed": ("d93f0b", "PR validation failed; see automated feedback and run logs."),
    "1p-contribution": ("1d76db", "Authored by Microsoft (party='1p' in metadata)."),
    "3p-contribution": ("bfd4f2", "Authored by a third-party partner (party='3p' in metadata)."),
    "docs-only": ("cfd3d7", "PR only modifies files in docs/schemas/."),
    "markdown-only": ("8250df", "Every file changed by this PR is Markdown."),
    "contains-dockerfile": ("2496ed", "PR adds, modifies, renames, or removes a Dockerfile."),
    "contains-code": ("1f883d", "PR includes source-code changes."),
    "needs-image-review": ("d4c5f9", "PR adds or modifies image files; human review is required."),
}
CLASSIFICATION_FLAGS = {
    "has_agents", "has_markdown_only", "has_dockerfile", "has_code",
    "has_1p", "has_3p", "has_images",
}


class ReportError(ValueError):
    pass


class GitHub:
    def request(
        self, endpoint: str, *, method: str = "GET",
        payload: dict[str, Any] | None = None, raw: bool = False,
        paginate: bool = False,
    ) -> Any:
        command = ["gh", "api", endpoint, "--method", method]
        if paginate:
            command.extend(["--paginate", "--slurp"])
        if payload is not None:
            command.extend(["--input", "-"])
        response = subprocess.run(
            command,
            input=json.dumps(payload).encode() if payload is not None else None,
            capture_output=True,
            check=True,
        )
        if raw:
            return response.stdout
        return json.loads(response.stdout) if response.stdout.strip() else None

    def pages(self, endpoint: str, key: str | None = None) -> list[dict[str, Any]]:
        separator = "&" if "?" in endpoint else "?"
        pages = self.request(f"{endpoint}{separator}per_page=100", paginate=True)
        return [item for page in pages for item in (page[key] if key else page)]


def read_report(archive: bytes, profile: SourceProfile = PR_REVIEW) -> dict[str, Any]:
    if len(archive) > MAX_REPORT_BYTES:
        raise ReportError("Reporting archive exceeds the size limit.")
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        entries = zipped.infolist()
        if (
            len(entries) != 1 or entries[0].filename != profile.report_file
            or entries[0].file_size > MAX_REPORT_BYTES
            or entries[0].flag_bits & 1
            or entries[0].compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
        ):
            raise ReportError(f"Expected one bounded {profile.report_file} file.")
        # Read in memory; never extract files or run anything supplied by the PR.
        with zipped.open(entries[0]) as report_file:
            data = report_file.read(MAX_REPORT_BYTES + 1)
        if len(data) > MAX_REPORT_BYTES:
            raise ReportError("Validation report exceeds the size limit.")
    report = json.loads(data)
    if profile == AGENT_REMOVAL:
        try:
            return validate_removal_report(report)
        except ValueError as error:
            raise ReportError(str(error)) from error
    if not isinstance(report, dict) or type(report.get("passed")) is not bool:
        raise ReportError("Validation report must contain a boolean passed field.")
    failures = report.get("failures")
    if (
        not isinstance(failures, list)
        or type(report.get("failure_count")) is not int
        or report["failure_count"] != len(failures)
        or report["passed"] != (not failures)
    ):
        raise ReportError("Validation failure count and passed flag are inconsistent.")
    for flag in CLASSIFICATION_FLAGS:
        if flag in report and type(report[flag]) is not bool:
            raise ReportError(f"{flag} must be a boolean.")
    for failure in failures:
        if not isinstance(failure, dict):
            raise ReportError("Each failure must be an object.")
        for field in ("rule_id", "file", "message"):
            value = failure.get(field)
            if not isinstance(value, str) or not value or len(value) > 16_000:
                raise ReportError(f"Failure {field} must be a bounded nonempty string.")
        if type(failure.get("line", 1)) is not int or failure.get("line", 1) < 1:
            raise ReportError("Failure line must be a positive integer.")
        for field in ("remediation", "docs"):
            value = failure.get(field, "")
            if not isinstance(value, str) or len(value) > 16_000:
                raise ReportError(f"Failure {field} must be a bounded string.")
        docs = failure.get("docs", "")
        if docs and (
            not re.fullmatch(r"docs/[A-Za-z0-9_./-]+(?:#[A-Za-z0-9_-]+)?", docs)
            or ".." in PurePosixPath(docs.partition("#")[0]).parts
        ):
            raise ReportError("Guidance must refer to repository documentation.")
    return report


def matches_pr(
    pr: dict[str, Any], run: dict[str, Any], repository_id: int,
    profile: SourceProfile = PR_REVIEW,
) -> bool:
    head_repo = pr.get("head", {}).get("repo") or {}
    return (
        pr.get("state") == "open"
        and pr["base"]["repo"]["id"] == repository_id
        and (profile.base_branch is None or pr["base"]["ref"] == profile.base_branch)
        and head_repo.get("id") == run["head_repository"]["id"]
        and pr["head"]["ref"] == run["head_branch"]
        and pr["head"]["sha"] == run["head_sha"]
    )


def is_current(
    api: GitHub, root: str, run: dict[str, Any], pr: dict[str, Any],
    repository_id: int, profile: SourceProfile = PR_REVIEW,
) -> bool:
    current_run = api.request(f"{root}/actions/runs/{run['id']}")
    current_pr = api.request(f"{root}/pulls/{pr['number']}")
    if (
        current_run["run_attempt"] != run["run_attempt"]
        or current_run["status"] != "completed"
        or (current_run.get("head_repository") or {}).get("id") != run["head_repository"]["id"]
        or current_run["conclusion"] == "cancelled"
        or current_pr["base"]["ref"] != pr["base"]["ref"]
        or not matches_pr(current_pr, run, repository_id, profile)
    ):
        print("::notice::Skipping feedback for a superseded run, closed PR, or changed head.")
        return False
    runs = api.pages(
        f"{root}/actions/workflows/{run['workflow_id']}/runs?"
        + urlencode({"event": "pull_request", "head_sha": run["head_sha"]}),
        "workflow_runs",
    )
    if any(
        candidate["run_number"] > run["run_number"]
        and (candidate.get("head_repository") or {}).get("id") == run["head_repository"]["id"]
        and candidate["head_branch"] == run["head_branch"]
        and any(
            association.get("number") == pr["number"]
            and (association.get("base") or {}).get("ref") == pr["base"]["ref"]
            for association in candidate.get("pull_requests", [])
            if isinstance(association, dict)
        )
        for candidate in runs
    ):
        print("::notice::Skipping feedback because a newer validation run exists.")
        return False
    return True


def latest_jobs(
    api: GitHub, root: str, run: dict[str, Any], profile: SourceProfile = PR_REVIEW,
) -> dict[str, Any]:
    jobs: dict[str, Any] = {}
    for job in api.pages(f"{root}/actions/runs/{run['id']}/jobs?filter=all", "jobs"):
        name = job["name"]
        if name not in profile.required_jobs or job["run_attempt"] > run["run_attempt"]:
            continue
        previous = jobs.get(name)
        if previous and previous["run_attempt"] == job["run_attempt"]:
            raise ReportError(f"Ambiguous source job: {name}.")
        if not previous or previous["run_attempt"] < job["run_attempt"]:
            jobs[name] = job
    if set(jobs) != profile.required_jobs or any(job["status"] != "completed" for job in jobs.values()):
        raise ReportError("Source run is missing completed required validation jobs.")
    return jobs


def labels_for(report: dict[str, Any], files: list[dict[str, Any]], passed: bool) -> list[str]:
    paths = [file["filename"] for file in files]
    catalog = any(path.startswith(("agents/", "starter-kits/")) for path in paths)
    labels = []
    if catalog:
        for flag, label in {
            "has_1p": "1p-contribution", "has_3p": "3p-contribution",
            "has_markdown_only": "markdown-only", "has_dockerfile": "contains-dockerfile",
            "has_code": "contains-code", "has_images": "needs-image-review",
        }.items():
            if report.get(flag, False):
                labels.append(label)
    elif paths and all(path.startswith("docs/schemas/") for path in paths):
        labels.append("docs-only")
    labels.append("pr-validation-passed" if passed else "pr-validation-failed")
    return labels


def literal(value: str) -> str:
    escaped = html.escape(value, quote=True).replace("|", "&#124;").replace("@", "&#64;")
    return f"<code>{escaped.replace(chr(10), '<br>')}</code>"


def failure_details(failure: dict[str, Any], repository_url: str, base_sha: str) -> str:
    remediation = failure.get("remediation") or (
        "Correct the issue described above, then push the fix to rerun validation."
    )
    details = f"{literal(failure['message'])}\n\n**How to fix:** {literal(remediation)}"
    if failure.get("docs"):
        details += (
            "\n\n**Guidance:** [Open the authoring guide]"
            f"({repository_url}/blob/{base_sha}/{failure['docs']})"
        )
    return details


def publish(
    api: GitHub, root: str, run: dict[str, Any], pr: dict[str, Any],
    report: dict[str, Any], jobs: dict[str, Any], files: list[dict[str, Any]],
    repository_url: str,
) -> None:
    passed = (
        run["conclusion"] == "success" and report["passed"]
        and all(job["conclusion"] == "success" for job in jobs.values())
    )
    labels = labels_for(report, files, passed)
    issue = f"{root}/issues/{pr['number']}"
    for label in api.pages(f"{issue}/labels"):
        if label["name"] in LABELS and label["name"] not in labels:
            api.request(f"{issue}/labels/{quote(label['name'], safe='')}", method="DELETE")
    existing = {label["name"] for label in api.pages(f"{root}/labels")}
    for label in labels:
        if label not in existing:
            color, description = LABELS[label]
            api.request(
                f"{root}/labels", method="POST",
                payload={"name": label, "color": color, "description": description},
            )
    api.request(f"{issue}/labels", method="POST", payload={"labels": labels})

    failures = report["failures"]
    comments = []
    diff_paths = {file["filename"] for file in files}
    for failure in failures:
        if failure["file"] in diff_paths and len(comments) < MAX_INLINE_COMMENTS:
            body = f"**[{literal(failure['rule_id'])}]** " + failure_details(
                failure, repository_url, pr["base"]["sha"]
            )
            if len(body) > MAX_COMMENT_CHARS:
                body = body[:MAX_COMMENT_CHARS - 100] + "\n\nDetails truncated; download the validation artifact."
            comments.append({
                "path": failure["file"], "line": failure.get("line", 1), "side": "RIGHT",
                "body": body,
            })
    if comments:
        try:
            api.request(
                f"{root}/pulls/{pr['number']}/reviews", method="POST",
                payload={"commit_id": run["head_sha"], "event": "COMMENT", "comments": comments},
            )
        except subprocess.CalledProcessError as error:
            print(
                "::warning::Inline feedback could not be posted; the summary retains "
                f"the diagnostics. {error.stderr.decode(errors='replace')}"
            )
    if not passed:
        rows = []
        if jobs["Secret Scan"]["conclusion"] != "success":
            rows.append("| SEC-SCAN | (repository) | Secret scan failed or did not run; inspect the source run logs. |")
        for failure in failures:
            row = (
                f"| {literal(failure['rule_id'])} "
                f"| {literal(failure['file'] + ':' + str(failure.get('line', 1)))} "
                f"| {failure_details(failure, repository_url, pr['base']['sha']).replace(chr(10), '<br>')} |"
            )
            if sum(map(len, rows)) + len(row) > MAX_COMMENT_CHARS - 2000:
                rows.append("| ... | ... | Additional findings omitted; download the validation artifact for the complete report. |")
                break
            rows.append(row)
        if not failures:
            rows.append("| WORKFLOW | (workflow) | Validation or setup failed; inspect the source run logs. |")
        body = "\n".join([
            "## Automated Check Results", "",
            f"[Source validation run]({repository_url}/actions/runs/{run['id']}) "
            f"for commit `{run['head_sha']}`.", "",
            "| Rule ID | Location | Details |", "|---|---|---|",
            *rows, "",
            "Push a fix to rerun validation. Required checks, not these diagnostic labels, "
            "determine merge eligibility. CODEOWNERS review requirements still apply.",
        ])
        api.request(f"{issue}/comments", method="POST", payload={"body": body})


def publish_removal(
    api: GitHub, root: str, run: dict[str, Any], pr: dict[str, Any],
    report: dict[str, Any], jobs: dict[str, Any], repository_url: str,
) -> None:
    expected = "success" if report["exit_code"] == 0 else "failure"
    if run["conclusion"] != expected or any(job["conclusion"] != expected for job in jobs.values()):
        raise ReportError("Removal report contradicts the source job or run conclusion.")
    if report["outcome"] in {"success", "not_applicable"}:
        return
    title = "Agent Removal Blocked" if report["outcome"] == "blocked" else "Validation Error"
    sections = [
        f"## Starter Kit Impact: {title}", "",
        f"[Source validation run]({repository_url}/actions/runs/{run['id']}) "
        f"for commit `{run['head_sha']}`.", "",
    ]
    details = [
        f"**{literal(kit['path'])}**: required agents removed: "
        + ", ".join(literal(ref) for ref in kit["required_refs"])
        for kit in report["impacted_kits"]
    ]
    details.extend(literal(issue) for issue in report["issues"])
    details.append("**Override decision:** " + literal(report["override"]["reason"]))
    length = len("\n".join(sections))
    for detail in details:
        if length + len(detail) > MAX_COMMENT_CHARS - 2000:
            sections.append("Additional findings omitted; download the source run's report artifact for complete details.")
            break
        sections.extend([detail, ""])
        length += len(detail) + 2
    sections.extend([
        "**Option A:** Update the affected starter kits: replace required references with "
        "valid agents, archive/delete the kit, or remove the required flag.",
        "",
        "**Option B (non-fork PRs only):** A maintainer with write, maintain, or admin "
        "permission may apply `starter-kit-impact-approved` and rerun the check. Fork PRs must use Option A.",
        "",
        "For setup or validation errors, inspect the source run logs and rerun after fixing the error.",
        f"[Starter-kit guidance]({repository_url}/blob/{pr['base']['sha']}/{report['guidance']})",
        "",
        "This comment is diagnostic only. The removal check remains authoritative; "
        "review and approval requirements are unchanged.",
    ])
    api.request(
        f"{root}/issues/{pr['number']}/comments", method="POST",
        payload={"body": "\n".join(sections)},
    )


def report_run(api: GitHub, event: dict[str, Any], repository: str, server_url: str) -> None:
    if event["repository"]["full_name"] != repository:
        raise ReportError("Reporting event belongs to another repository.")
    root = f"repos/{repository}"
    source = event["workflow_run"]
    run = api.request(f"{root}/actions/runs/{source['id']}")
    profile = SOURCES.get(run.get("path"))
    if profile is None:
        raise ReportError("Source workflow path is not allowlisted.")
    workflow = api.request(f"{root}/actions/workflows/{profile.path.rsplit('/', 1)[1]}")
    if (
        run["repository"]["id"] != event["repository"]["id"]
        or run["workflow_id"] != workflow["id"]
        or workflow["path"] != profile.path
        or run["event"] != "pull_request" or run["status"] != "completed"
    ):
        raise ReportError("Source is not a completed allowlisted validation run in this repository.")
    if run["run_attempt"] != source["run_attempt"] or run["conclusion"] == "cancelled":
        print("::notice::Skipping cancelled or superseded source attempt.")
        return
    if not run.get("head_repository"):
        print("::notice::Source fork no longer exists; skipping feedback.")
        return
    repository_id = event["repository"]["id"]
    head = f"{run['head_repository']['owner']['login']}:{run['head_branch']}"
    query = {"state": "open", "head": head}
    if profile.base_branch is not None:
        query["base"] = profile.base_branch
    candidates = [
        pr for pr in api.pages(
            f"{root}/pulls?" + urlencode(query)
        )
        if matches_pr(pr, run, repository_id, profile)
    ]
    if not candidates:
        print("::notice::No open PR matches the source repository, branch, and current head.")
        return
    if len(candidates) != 1:
        raise ReportError("Source run does not identify a unique open PR.")
    pr = candidates[0]
    if not is_current(api, root, run, pr, repository_id, profile):
        return
    jobs = latest_jobs(api, root, run, profile)
    artifacts = [
        artifact for artifact in api.pages(f"{root}/actions/runs/{run['id']}/artifacts", "artifacts")
        if artifact["name"] == f"{profile.artifact_prefix}-{run['run_attempt']}"
    ]
    expected_origin = {
        "id": run["id"], "repository_id": repository_id,
        "head_repository_id": run["head_repository"]["id"],
        "head_branch": run["head_branch"], "head_sha": run["head_sha"],
    }
    if (
        len(artifacts) != 1 or artifacts[0]["expired"]
        or artifacts[0]["size_in_bytes"] > MAX_REPORT_BYTES
        or any(artifacts[0]["workflow_run"].get(key) != value for key, value in expected_origin.items())
    ):
        raise ReportError("Missing, ambiguous, expired, or oversized attempt-scoped report.")
    archive = api.request(f"{root}/actions/artifacts/{artifacts[0]['id']}/zip", raw=True)
    report = read_report(archive, profile)
    files = api.pages(f"{root}/pulls/{pr['number']}/files") if profile == PR_REVIEW else []
    if not is_current(api, root, run, pr, repository_id, profile):
        return
    repository_url = f"{server_url.rstrip('/')}/{repository}"
    if profile == AGENT_REMOVAL:
        publish_removal(api, root, run, pr, report, jobs, repository_url)
    else:
        publish(api, root, run, pr, report, jobs, files, repository_url)


def main() -> int:
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        report_run(GitHub(), event, os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SERVER_URL"])
    except (ValueError, zipfile.BadZipFile, OSError, subprocess.CalledProcessError) as error:
        message = str(error)
        if isinstance(error, subprocess.CalledProcessError):
            message += f"\n{error.stderr.decode(errors='replace')}"
        print(f"::error::PR feedback failed: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
