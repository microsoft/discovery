#!/usr/bin/env python3
"""Render structured CI results as actionable GitHub step summaries."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_DETAILS_CHARS = 16_000
MAX_FINDINGS = 50


@dataclass(frozen=True)
class TextCheck:
    name: str
    outcome: str
    log_path: Path
    rerun_command: str = ""


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True).replace("\n", "<br>")


def _code(value: object) -> str:
    return f"<code>{_escape(value)}</code>"


def _link_text(value: object) -> str:
    return _escape(value).replace("[", "&#91;").replace("]", "&#93;")


def _details(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) > MAX_DETAILS_CHARS:
        cleaned = (
            "... output truncated; download the result artifact for the full details ...\n"
            + cleaned[-MAX_DETAILS_CHARS:]
        )
    return html.escape(cleaned, quote=False)


def _outcome_label(outcome: str) -> str:
    labels = {
        "success": "Passed",
        "failure": "Failed",
        "cancelled": "Cancelled",
        "skipped": "Not run",
    }
    return labels.get(outcome.lower(), outcome.title() or "Unknown")


def _problem_element(testcase: ET.Element) -> ET.Element | None:
    failure = testcase.find("failure")
    return failure if failure is not None else testcase.find("error")


def _test_location(testcase: ET.Element, details: str) -> tuple[str, str]:
    file_name = testcase.get("file", "")
    line = testcase.get("line", "")
    if not file_name:
        match = re.search(r"(?m)^([^\r\n]+?\.py):(\d+):", details)
        if match:
            file_name, line = match.groups()
    return file_name, line


def render_pytest_summary(
    report_path: Path,
    *,
    title: str,
    outcome: str,
    rerun_command: str,
) -> str:
    lines = [f"## {_escape(title)}", ""]
    if not report_path.is_file():
        lines.extend([
            f"**Result:** {_outcome_label(outcome)} before a JUnit report was produced.",
            "",
            "The test process did not produce structured results. Open the failed setup or test step above for the first error.",
        ])
        if rerun_command:
            lines.extend(["", f"**Reproduce locally:** {_code(rerun_command)}"])
        return "\n".join(lines) + "\n"

    try:
        root = ET.parse(report_path).getroot()
    except (ET.ParseError, OSError) as error:
        lines.extend([
            "**Result:** The JUnit report could not be read.",
            "",
            f"**Report error:** {_escape(error)}",
        ])
        if rerun_command:
            lines.extend(["", f"**Reproduce locally:** {_code(rerun_command)}"])
        return "\n".join(lines) + "\n"

    testcases = list(root.iter("testcase"))
    problems = [
        (testcase, problem)
        for testcase in testcases
        if (problem := _problem_element(testcase)) is not None
    ]
    skipped = sum(testcase.find("skipped") is not None for testcase in testcases)
    errors = sum(problem.tag == "error" for _, problem in problems)
    failures = len(problems) - errors
    total = len(testcases)
    passed = max(total - failures - errors - skipped, 0)
    result = "Passed" if not problems and outcome == "success" else _outcome_label(outcome)

    lines.extend([
        f"**Result:** {result}",
        "",
        "| Total | Passed | Failed | Errors | Skipped |",
        "|---:|---:|---:|---:|---:|",
        f"| {total} | {passed} | {failures} | {errors} | {skipped} |",
    ])

    if problems:
        lines.extend(["", "### Failed tests", ""])
        for index, (testcase, problem) in enumerate(problems, start=1):
            details = problem.text or ""
            file_name, line = _test_location(testcase, details)
            test_name = testcase.get("name", "unknown test")
            node_id = f"{file_name}::{test_name}" if file_name else (
                f"{testcase.get('classname', 'unknown')}::{test_name}"
            )
            location = f"{file_name}:{line}" if file_name and line else file_name
            message = (problem.get("message") or "").strip()
            if not message:
                detail_lines = [item.strip() for item in details.splitlines() if item.strip()]
                message = detail_lines[-1] if detail_lines else "Test failed without an exception message."

            lines.extend([
                f"{index}. **{_code(node_id)}**",
                f"   - **Location:** {_code(location or 'not reported')}",
                f"   - **Failure:** {_escape(message)}",
                f"   - **Rerun this test:** {_code(f'python -m pytest {node_id} -vv')}",
            ])
            if details.strip():
                lines.extend([
                    "   <details>",
                    "   <summary>Traceback and captured output</summary>",
                    "",
                    f"   <pre>{_details(details)}</pre>",
                    "   </details>",
                ])

    if rerun_command:
        lines.extend(["", f"**Reproduce locally:** {_code(rerun_command)}"])
    return "\n".join(lines) + "\n"


def _load_report(report_path: Path) -> tuple[dict[str, Any] | None, str]:
    if not report_path.is_file():
        return None, "The validator did not produce its JSON result file."
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        return None, f"The validator result could not be read: {error}"
    if not isinstance(report, dict):
        return None, "The validator result must be a JSON object."
    return report, ""


def _docs_url(docs: str, repository_url: str, revision: str) -> str:
    if not docs:
        return ""
    if docs.startswith(("https://", "http://")):
        return docs
    if not repository_url or not revision:
        return ""
    path, separator, fragment = docs.partition("#")
    suffix = f"#{fragment}" if separator else ""
    return f"{repository_url.rstrip('/')}/blob/{revision}/{path}{suffix}"


def _render_findings(
    findings: list[dict[str, Any]],
    *,
    heading: str,
    repository_url: str,
    revision: str,
) -> list[str]:
    if not findings:
        return []

    lines = ["", heading, ""]
    for index, finding in enumerate(findings[:MAX_FINDINGS], start=1):
        rule_id = finding.get("rule_id", "UNKNOWN")
        file_name = finding.get("file", "unknown file")
        line = finding.get("line", 1)
        location = f"{file_name}:{line}" if line else file_name
        message = finding.get("message", "No failure message was reported.")
        remediation = finding.get("remediation", "")
        docs_url = _docs_url(
            str(finding.get("docs", "")), repository_url, revision
        )

        lines.extend([
            f"{index}. **{_code(rule_id)} at {_code(location)}**",
            f"   - **Issue:** {_escape(message)}",
        ])
        if remediation:
            lines.append(f"   - **How to fix:** {_escape(remediation)}")
        else:
            lines.append("   - **How to fix:** Correct the issue described above, then rerun validation.")
        if docs_url:
            lines.append(f"   - **Guidance:** [Open the relevant authoring guidance]({docs_url})")

    remaining = len(findings) - MAX_FINDINGS
    if remaining > 0:
        lines.extend([
            "",
            f"{remaining} additional finding(s) are omitted here. Download the JSON artifact for the complete result.",
        ])
    return lines


def render_catalog_summary(
    report_path: Path,
    *,
    title: str,
    outcome: str,
    rerun_command: str = "",
    repository_url: str = "",
    revision: str = "",
) -> str:
    lines = [f"## {_escape(title)}", ""]
    report, error = _load_report(report_path)
    if report is None:
        lines.extend([
            f"**Result:** {_outcome_label(outcome)} before structured validator results were produced.",
            "",
            _escape(error),
        ])
        if rerun_command:
            lines.extend(["", f"**Reproduce locally:** {_code(rerun_command)}"])
        return "\n".join(lines) + "\n"

    failures = [item for item in report.get("failures", []) if isinstance(item, dict)]
    warnings = [item for item in report.get("warnings", []) if isinstance(item, dict)]
    passed = bool(report.get("passed")) and not failures
    lines.extend([
        f"**Result:** {'Passed' if passed else 'Failed'}",
        "",
        f"**Blocking findings:** {len(failures)}  ",
        f"**Warnings:** {len(warnings)}",
    ])
    lines.extend(_render_findings(
        failures,
        heading="### Blocking findings",
        repository_url=repository_url,
        revision=revision,
    ))
    lines.extend(_render_findings(
        warnings,
        heading="### Non-blocking warnings",
        repository_url=repository_url,
        revision=revision,
    ))
    if passed and not warnings:
        lines.extend(["", "No blocking findings or warnings were reported."])
    if rerun_command:
        lines.extend(["", f"**Reproduce locally:** {_code(rerun_command)}"])
    return "\n".join(lines) + "\n"


def _read_log(log_path: Path) -> str:
    if not log_path.is_file():
        return "No log file was produced. Open the failed workflow step above for setup errors."
    try:
        return log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return f"The captured log could not be read: {error}"


def render_text_summary(check: TextCheck, *, heading_level: int = 2) -> str:
    heading = "#" * heading_level
    lines = [f"{heading} {_escape(check.name)}", "", f"**Result:** {_outcome_label(check.outcome)}"]
    if check.outcome != "success":
        lines.extend([
            "",
            "<details open>",
            "<summary>Failure details</summary>",
            "",
            f"<pre>{_details(_read_log(check.log_path))}</pre>",
            "</details>",
        ])
        if check.rerun_command:
            lines.extend(["", f"**Reproduce locally:** {_code(check.rerun_command)}"])
    return "\n".join(lines) + "\n"


def render_shadow_summary(
    *,
    pr_number: str,
    pr_url: str,
    pr_title: str,
    head_repository: str,
    is_fork: str,
    changed_count: str,
    integration: TextCheck,
    catalog_outcome: str,
    catalog_report: Path,
    schema: TextCheck,
    starter_kits: TextCheck,
    removal_impact: TextCheck,
    repository_url: str,
    revision: str,
) -> str:
    checks = [integration, schema, starter_kits, removal_impact]
    target = (
        f'<a href="{html.escape(pr_url, quote=True)}">'
        f'#{_link_text(pr_number)} - {_link_text(pr_title)}</a>'
    )
    lines = [
        "## Read-only PR shadow validation",
        "",
        f"**Target:** {target}  ",
        f"**Head repository:** {_code(head_repository)}  ",
        f"**Fork:** {_code(is_fork)}  ",
        f"**Changed files:** {_escape(changed_count)}",
        "",
        "| Check | Outcome |",
        "|---|---|",
        f"| Ephemeral integration | {_outcome_label(integration.outcome)} |",
        f"| Primary catalog validator | {_outcome_label(catalog_outcome)} |",
        f"| Schema regression suite | {_outcome_label(schema.outcome)} |",
        f"| Starter-kit validator | {_outcome_label(starter_kits.outcome)} |",
        f"| Agent removal impact | {_outcome_label(removal_impact.outcome)} |",
    ]

    report, error = _load_report(catalog_report)
    if report is not None:
        failures = [item for item in report.get("failures", []) if isinstance(item, dict)]
        warnings = [item for item in report.get("warnings", []) if isinstance(item, dict)]
        lines.extend(["", f"### Catalog findings ({len(failures)} blocking, {len(warnings)} warning)", ""])
        if not failures and not warnings:
            lines.append("No catalog findings were reported.")
        lines.extend(_render_findings(
            failures,
            heading="#### Blocking findings",
            repository_url=repository_url,
            revision=revision,
        ))
        lines.extend(_render_findings(
            warnings,
            heading="#### Non-blocking warnings",
            repository_url=repository_url,
            revision=revision,
        ))
    elif catalog_outcome != "skipped":
        lines.extend(["", "### Catalog validator details", "", _escape(error)])

    for check in checks:
        if check.outcome == "failure":
            lines.extend(["", render_text_summary(check, heading_level=3).rstrip()])

    if integration.outcome == "failure":
        lines.extend([
            "",
            "Checks marked Not run depend on a successful ephemeral merge. Resolve the merge conflict on the target PR before rerunning the shadow validation.",
        ])

    lines.extend([
        "",
        "**Next step:** Fix every blocking finding on the target PR, push the update, and rerun this workflow against the same PR number.",
        "",
        "> Report only: this workflow did not change or publish a check to the target PR.",
    ])
    return "\n".join(lines) + "\n"


def _write_summary(summary: str, output_path: str) -> None:
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as stream:
            stream.write(summary)
        return
    print(summary, end="")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=os.environ.get("GITHUB_STEP_SUMMARY", ""),
        help="Summary file to append to; defaults to GITHUB_STEP_SUMMARY.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    pytest_parser = subparsers.add_parser("pytest")
    pytest_parser.add_argument("--report", type=Path, required=True)
    pytest_parser.add_argument("--title", required=True)
    pytest_parser.add_argument("--outcome", required=True)
    pytest_parser.add_argument("--rerun-command", default="")

    catalog_parser = subparsers.add_parser("catalog")
    catalog_parser.add_argument("--report", type=Path, required=True)
    catalog_parser.add_argument("--title", required=True)
    catalog_parser.add_argument("--outcome", required=True)
    catalog_parser.add_argument("--rerun-command", default="")
    catalog_parser.add_argument("--repository-url", default="")
    catalog_parser.add_argument("--revision", default="")

    text_parser = subparsers.add_parser("text")
    text_parser.add_argument("--log", type=Path, required=True)
    text_parser.add_argument("--title", required=True)
    text_parser.add_argument("--outcome", required=True)
    text_parser.add_argument("--rerun-command", default="")

    shadow_parser = subparsers.add_parser("shadow")
    for argument in (
        "pr-number", "pr-url", "pr-title", "head-repository", "is-fork",
        "changed-count", "integration-outcome", "catalog-outcome",
        "schema-outcome", "starter-kit-outcome", "removal-outcome",
    ):
        shadow_parser.add_argument(f"--{argument}", required=True)
    for argument in (
        "integration-log", "catalog-report", "schema-log", "starter-kit-log",
        "removal-log",
    ):
        shadow_parser.add_argument(f"--{argument}", type=Path, required=True)
    shadow_parser.add_argument("--repository-url", default="")
    shadow_parser.add_argument("--revision", default="")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "pytest":
        summary = render_pytest_summary(
            args.report,
            title=args.title,
            outcome=args.outcome,
            rerun_command=args.rerun_command,
        )
    elif args.command == "catalog":
        summary = render_catalog_summary(
            args.report,
            title=args.title,
            outcome=args.outcome,
            rerun_command=args.rerun_command,
            repository_url=args.repository_url,
            revision=args.revision,
        )
    elif args.command == "text":
        summary = render_text_summary(TextCheck(
            name=args.title,
            outcome=args.outcome,
            log_path=args.log,
            rerun_command=args.rerun_command,
        ))
    else:
        summary = render_shadow_summary(
            pr_number=args.pr_number,
            pr_url=args.pr_url,
            pr_title=args.pr_title,
            head_repository=args.head_repository,
            is_fork=args.is_fork,
            changed_count=args.changed_count,
            integration=TextCheck(
                "Ephemeral integration", args.integration_outcome, args.integration_log
            ),
            catalog_outcome=args.catalog_outcome,
            catalog_report=args.catalog_report,
            schema=TextCheck(
                "Schema regression suite",
                args.schema_outcome,
                args.schema_log,
                "python -m pytest .github/tests/test_schema_security.py -q",
            ),
            starter_kits=TextCheck(
                "Starter-kit validator",
                args.starter_kit_outcome,
                args.starter_kit_log,
                "python .github/scripts/validate_starter_kits.py --repo-root .",
            ),
            removal_impact=TextCheck(
                "Agent removal impact", args.removal_outcome, args.removal_log
            ),
            repository_url=args.repository_url,
            revision=args.revision,
        )
    _write_summary(summary, args.output)


if __name__ == "__main__":
    main()