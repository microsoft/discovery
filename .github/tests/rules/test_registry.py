"""Rule engine: discovery, waivers, and the ratchet.

Includes the meta-test that keeps the system honest — every discovered rule
must have a matching test module, so a new rule cannot ship untested.
"""

from __future__ import annotations

import ast
import datetime as _dt
from dataclasses import replace
import json
from pathlib import Path
import re

import pytest
from conftest import ELF_BYTES, run_rule, write, write_policy

from catalog_validation.runner import LEGACY_RULE_IDS, _rule_ownership_failures
from rules.base import Finding, Rule, Scope, Severity
from rules.pol_008 import RULE as POL_008
from rules.registry import (
    MAX_WAIVER_DAYS,
    build_context,
    discover_rules,
    load_waivers,
    run_rules,
)

RULES_DIR = Path(__file__).resolve().parents[2] / "scripts" / "rules"
TESTS_DIR = Path(__file__).resolve().parent
CATALOG_VALIDATION_DIR = RULES_DIR.parent / "catalog_validation"
RULE_ID_RE = re.compile(r"^(?:CFG|STR|SCH|POL|DOC|TAG)-\d{3}$")


def _iso(days_from_now: int) -> str:
    return (_dt.date.today() + _dt.timedelta(days=days_from_now)).isoformat()


# ── Discovery ────────────────────────────────────────────────────────────────

def test_discovery_finds_every_rule_module():
    discovered = {r.id for r in discover_rules()}
    modules = {
        p.stem for p in RULES_DIR.glob("*.py")
        if p.stem not in {"__init__", "base", "registry"}
    }
    assert len(discovered) == len(modules)


def test_every_rule_is_well_formed():
    for rule in discover_rules():
        assert isinstance(rule, Rule)
        assert rule.id.strip(), "rule id must not be empty"
        assert rule.summary.strip(), f"{rule.id} needs a summary for docs generation"
        assert rule.remediation.strip(), f"{rule.id} needs actionable remediation text"
        assert isinstance(rule.scope, Scope)
        assert isinstance(rule.severity, Severity)


def test_rule_ids_are_unique():
    ids = [r.id for r in discover_rules()]
    assert len(ids) == len(set(ids))


def _implemented_legacy_rule_ids() -> set[str]:
    implemented: set[str] = set()
    for path in CATALOG_VALIDATION_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            values: list[object] = []
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"Failure", "_schema_findings"}
                and node.args
            ):
                values.append(node.args[0])
            elif isinstance(node, ast.Return) and node.value is not None:
                values.append(node.value)
            for value in values:
                for candidate in ast.walk(value):
                    if (
                        isinstance(candidate, ast.Constant)
                        and isinstance(candidate.value, str)
                        and RULE_ID_RE.fullmatch(candidate.value)
                    ):
                        implemented.add(candidate.value)
    return implemented


def test_legacy_and_modular_rule_ownership_is_complete_and_disjoint():
    modular_ids = {rule.id for rule in discover_rules()}

    assert _implemented_legacy_rule_ids() == LEGACY_RULE_IDS
    assert LEGACY_RULE_IDS.isdisjoint(modular_ids)
    assert _rule_ownership_failures(discover_rules()) == []


def test_rule_ownership_conflict_fails_closed():
    conflicting_rule = replace(POL_008, id="POL-009")

    failures = _rule_ownership_failures([conflicting_rule])

    assert [failure.rule_id for failure in failures] == ["CFG-004"]
    assert "POL-009" in failures[0].message


def test_every_rule_module_has_a_test_module():
    """A rule without a test is a rule nobody has proven works."""
    missing = []
    for path in RULES_DIR.glob("*.py"):
        if path.stem in {"__init__", "base", "registry"}:
            continue
        if not (TESTS_DIR / f"test_{path.stem}.py").exists():
            missing.append(f".github/tests/rules/test_{path.stem}.py")
    assert not missing, f"Missing test module(s): {missing}"


def test_generated_rule_docs_are_current():
    """docs/validation-rules.md is generated; a stale page misleads contributors."""
    from generate_rule_docs import DOCS_PATH, render

    repo_root = Path(__file__).resolve().parents[3]
    committed = (repo_root / DOCS_PATH).read_text(encoding="utf-8")
    assert committed == render(discover_rules()), (
        "Regenerate with: python .github/scripts/generate_rule_docs.py"
    )


def test_catalog_rules_ignore_files_outside_catalog_trees(repo):
    changed = [
        write(repo, "utilities/toolbox/Dockerfile", "FROM ubuntu:latest\n"),
        write(repo, "docs/examples/payload.py", "print('example')\n"),
        write(repo, "includes/media/diagram.svg", "<svg><script/></svg>\n"),
    ]

    result = run_rules(build_context(repo, changed), discover_rules())

    assert result.findings == []


# ── Waiver validation ────────────────────────────────────────────────────────

def test_valid_waiver_suppresses_a_finding(repo):
    rel = write(repo, "agents/demo/notes.txt", ELF_BYTES)
    write_policy(repo, "waivers.yaml", f"""
waivers:
  - rule_id: POL-008
    path: agents/demo/notes.txt
    reason: Vendor-supplied fixture required to reproduce a parser CVE.
    approver: some-codeowner
    expires: "{_iso(30)}"
""")
    result = run_rule(repo, POL_008, [rel])
    assert result.findings == []
    assert result.config_errors == []


def test_waiver_glob_matches_paths(repo):
    rel = write(repo, "agents/demo/tools/t/notes.txt", ELF_BYTES)
    write_policy(repo, "waivers.yaml", f"""
waivers:
  - rule_id: POL-008
    path: agents/demo/tools/**
    reason: Temporary exception while the upstream fixture is repackaged.
    approver: some-codeowner
    expires: "{_iso(30)}"
""")
    result = run_rule(repo, POL_008, [rel])
    assert result.findings == []


def test_waiver_for_a_different_rule_does_not_suppress(repo):
    rel = write(repo, "agents/demo/notes.txt", ELF_BYTES)
    write_policy(repo, "waivers.yaml", f"""
waivers:
  - rule_id: POL-999
    path: agents/demo/notes.txt
    reason: Unrelated waiver that must not affect POL-008 enforcement.
    approver: some-codeowner
    expires: "{_iso(30)}"
""")
    result = run_rule(repo, POL_008, [rel])
    assert [f.rule_id for f in result.findings] == ["POL-008"]


def test_expired_waiver_is_a_config_error_and_does_not_suppress(repo):
    rel = write(repo, "agents/demo/notes.txt", ELF_BYTES)
    write_policy(repo, "waivers.yaml", f"""
waivers:
  - rule_id: POL-008
    path: agents/demo/notes.txt
    reason: This waiver lapsed and must stop suppressing the finding.
    approver: some-codeowner
    expires: "{_iso(-1)}"
""")
    result = run_rule(repo, POL_008, [rel])
    assert [f.rule_id for f in result.findings] == ["POL-008"]
    assert any("expired" in e for e in result.config_errors)


def test_waiver_beyond_max_window_is_rejected(repo):
    write_policy(repo, "waivers.yaml", f"""
waivers:
  - rule_id: POL-008
    path: agents/demo/notes.txt
    reason: Attempting to make a suppression effectively permanent.
    approver: some-codeowner
    expires: "{_iso(MAX_WAIVER_DAYS + 10)}"
""")
    waivers, errors = load_waivers(repo)
    assert waivers == []
    assert any(str(MAX_WAIVER_DAYS) in e for e in errors)


def test_waiver_with_thin_reason_is_rejected(repo):
    write_policy(repo, "waivers.yaml", f"""
waivers:
  - rule_id: POL-008
    path: agents/demo/notes.txt
    reason: needed
    approver: some-codeowner
    expires: "{_iso(30)}"
""")
    waivers, errors = load_waivers(repo)
    assert waivers == []
    assert any("20 characters" in e for e in errors)


@pytest.mark.parametrize("missing_field", ["rule_id", "path", "reason", "approver", "expires"])
def test_waiver_missing_required_field_is_rejected(repo, missing_field):
    fields = {
        "rule_id": "POL-008",
        "path": "agents/demo/notes.txt",
        "reason": "A sufficiently descriptive justification for the exception.",
        "approver": "some-codeowner",
        "expires": _iso(30),
    }
    del fields[missing_field]
    body = "\n".join(f'    {k}: "{v}"' for k, v in fields.items())
    write_policy(repo, "waivers.yaml", f"waivers:\n  -\n{body}\n")
    waivers, errors = load_waivers(repo)
    assert waivers == []
    assert any(missing_field in e for e in errors)


def test_malformed_waiver_file_fails_closed(repo):
    write_policy(repo, "waivers.yaml", "waivers: [ this is not: valid: yaml\n")
    waivers, errors = load_waivers(repo)
    assert waivers == []
    assert errors, "a broken waiver file must surface an error, never fail open"


# ── Ratchet ──────────────────────────────────────────────────────────────────

def _write_baseline(repo: Path, entries: list[dict]) -> None:
    path = repo / ".github" / "policy" / "baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    governed = [
        {
            **entry,
            "owner": "Discovery catalog CODEOWNERS",
            "tracking_ref": (
                "docs/validation-baseline-debt.md#test-baseline-entry"
            ),
            "remove_by": "2099-12-31",
        }
        for entry in entries
    ]
    path.write_text(json.dumps({"violations": governed}), encoding="utf-8")


def _folder_rule(targets: list[str], rule_id: str = "ZZZ-001") -> Rule:
    """A synthetic agent-folder rule that flags fixed files.

    Folder-scoped rules scan an agent's whole folder, so they are the only
    rules that can report a violation in a file the PR does *not* change —
    exactly the case the ratchet is meant to keep quiet. Using a synthetic
    rule keeps these ratchet tests decoupled from any real rule's specifics.
    """

    def check(ctx):
        return [Finding(rule_id=rule_id, file=t, message="synthetic finding") for t in targets]

    return Rule(
        id=rule_id,
        summary="synthetic folder rule for ratchet tests",
        scope=Scope.AGENT_FOLDER,
        remediation="n/a",
        check=check,
    )


def test_baselined_violation_in_an_unchanged_file_is_downgraded(repo):
    """A pre-existing violation the PR does not touch stays a warning."""
    write(repo, "agents/legacy/agent.yaml", "name: legacy\n")
    unchanged = write(repo, "agents/legacy/legacy-artifact.bin", ELF_BYTES)
    _write_baseline(repo, [{"rule_id": "ZZZ-001", "file": unchanged}])
    # The PR touches the folder (agent.yaml) but not the offending artifact.
    result = run_rule(repo, _folder_rule([unchanged]), ["agents/legacy/agent.yaml"])
    assert result.blocking == []
    assert len(result.warnings) == 1
    assert "pre-existing" in result.warnings[0].message


def test_baselined_violation_in_a_changed_file_still_blocks(repo):
    """Touching a baselined file re-subjects it to full scrutiny — it blocks.

    Regression guard for the ratchet bypass: a new violation introduced into
    an already-baselined file must never be silently downgraded just because
    a stale baseline entry names it.
    """
    rel = write(repo, "agents/legacy/notes.txt", ELF_BYTES)
    _write_baseline(repo, [{"rule_id": "POL-008", "file": rel}])
    result = run_rule(repo, POL_008, [rel])
    assert [f.file for f in result.blocking] == [rel]
    assert result.warnings == []


def test_only_unchanged_baselined_files_are_downgraded(repo):
    """With two identical baselined findings, only the untouched file relaxes."""
    write(repo, "agents/legacy/agent.yaml", "name: legacy\n")
    unchanged = write(repo, "agents/legacy/old.bin", ELF_BYTES)
    changed = write(repo, "agents/legacy/new.bin", ELF_BYTES)
    _write_baseline(repo, [
        {"rule_id": "ZZZ-001", "file": unchanged},
        {"rule_id": "ZZZ-001", "file": changed},
    ])
    result = run_rule(
        repo,
        _folder_rule([unchanged, changed]),
        ["agents/legacy/agent.yaml", changed],
    )
    assert [f.file for f in result.blocking] == [changed]
    assert [f.file for f in result.warnings] == [unchanged]


def test_ratchet_can_be_disabled_for_full_repo_audits(repo):
    rel = write(repo, "agents/legacy/notes.txt", ELF_BYTES)
    _write_baseline(repo, [{"rule_id": "POL-008", "file": rel}])
    result = run_rule(repo, POL_008, [rel], apply_ratchet=False)
    assert len(result.blocking) == 1


def test_missing_baseline_file_is_not_an_error(repo):
    rel = write(repo, "agents/demo/notes.txt", ELF_BYTES)
    result = run_rule(repo, POL_008, [rel])
    assert len(result.blocking) == 1
    assert result.config_errors == []
