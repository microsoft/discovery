"""Tests for actionable GitHub Actions validation summaries."""

from __future__ import annotations

import json
from pathlib import Path

from catalog_validation.findings import Failure
from render_ci_summary import (
    TextCheck,
    render_catalog_summary,
    render_pytest_summary,
    render_shadow_summary,
)


def test_failure_json_preserves_actionable_rule_guidance() -> None:
    result = Failure(
        "TAG-001",
        "agents/example/metadata.yaml",
        "Unknown tag.",
        remediation="Use a controlled tag.",
        docs="docs/authoring-guides/agent-authoring-guide.md#tags",
    ).to_dict()

    assert result["remediation"] == "Use a controlled tag."
    assert result["docs"] == "docs/authoring-guides/agent-authoring-guide.md#tags"


def test_pytest_summary_lists_counts_failure_location_and_rerun(tmp_path: Path) -> None:
    report = tmp_path / "pytest.xml"
    report.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite tests="3" failures="1" errors="0" skipped="1">
    <testcase classname="tests.test_rules" name="test_passes" file=".github/tests/test_rules.py" line="10" />
    <testcase classname="tests.test_rules" name="test_fails[value]" file=".github/tests/test_rules.py" line="20">
      <failure message="AssertionError: expected &lt;safe&gt;">.github/tests/test_rules.py:22: AssertionError
assert False</failure>
    </testcase>
    <testcase classname="tests.test_rules" name="test_skips"><skipped /></testcase>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )

    summary = render_pytest_summary(
        report,
        title="Unit tests",
        outcome="failure",
        rerun_command="python -m pytest .github/tests/ -vv",
    )

    assert "| 3 | 1 | 1 | 0 | 1 |" in summary
    assert ".github/tests/test_rules.py::test_fails[value]" in summary
    assert ".github/tests/test_rules.py:20" in summary
    assert "AssertionError: expected &lt;safe&gt;" in summary
    assert "python -m pytest .github/tests/test_rules.py::test_fails[value] -vv" in summary
    assert "python -m pytest .github/tests/ -vv" in summary


def test_catalog_summary_includes_remediation_and_guidance(tmp_path: Path) -> None:
    report = tmp_path / "catalog.json"
    report.write_text(json.dumps({
        "passed": False,
        "failure_count": 1,
        "warning_count": 0,
        "failures": [{
            "rule_id": "TAG-001",
            "file": "agents/example/metadata.yaml",
            "line": 7,
            "message": "Tag 'other' is not allowed.",
            "remediation": "Use a tag from the controlled vocabulary.",
            "docs": "docs/authoring-guides/agent-authoring-guide.md#tags",
        }],
        "warnings": [],
    }), encoding="utf-8")

    summary = render_catalog_summary(
        report,
        title="Catalog validation",
        outcome="failure",
        rerun_command="python .github/scripts/validate_pr.py ...",
        repository_url="https://github.com/microsoft/discovery",
        revision="abc123",
    )

    assert "TAG-001" in summary
    assert "agents/example/metadata.yaml:7" in summary
    assert "Use a tag from the controlled vocabulary." in summary
    assert "https://github.com/microsoft/discovery/blob/abc123/docs/authoring-guides/agent-authoring-guide.md#tags" in summary


def test_shadow_summary_expands_catalog_and_failed_subcheck_logs(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({
        "passed": False,
        "failures": [{
            "rule_id": "POL-021",
            "file": ".github/workflows/example.yml",
            "line": 1,
            "message": "Public contributors may only change catalog paths.",
        }],
        "warnings": [],
    }), encoding="utf-8")
    schema_log = tmp_path / "schema.txt"
    schema_log.write_text("FAILED test_schema.py::test_agent - invalid region", encoding="utf-8")

    summary = render_shadow_summary(
        pr_number="110",
        pr_url="https://github.com/microsoft/discovery/pull/110",
        pr_title="External ](https://example.invalid) <script>",
        head_repository="contributor/discovery",
        is_fork="true",
        changed_count="2",
        integration=TextCheck("Ephemeral integration", "success", tmp_path / "merge.txt"),
        catalog_outcome="failure",
        catalog_report=catalog,
        schema=TextCheck("Schema regression suite", "failure", schema_log),
        starter_kits=TextCheck("Starter-kit validator", "success", tmp_path / "kits.txt"),
        removal_impact=TextCheck("Agent removal impact", "success", tmp_path / "removal.txt"),
        repository_url="https://github.com/microsoft/discovery",
        revision="abc123",
    )

    assert "POL-021" in summary
    assert ".github/workflows/example.yml:1" in summary
    assert "FAILED test_schema.py::test_agent - invalid region" in summary
    assert "Starter-kit validator\n\n**Result:** Passed" not in summary
    assert "](https://example.invalid)" not in summary
    assert "&lt;script&gt;" in summary
    assert "Report only" in summary