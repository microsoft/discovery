"""Rule engine: discovery, waivers, and the ratchet.

Includes the meta-test that keeps the system honest — every discovered rule
must have a matching test module, so a new rule cannot ship untested.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest
from conftest import ELF_BYTES, run_rule, write, write_policy

from rules.base import Rule, Scope, Severity
from rules.pol_008 import RULE as POL_008
from rules.registry import MAX_WAIVER_DAYS, discover_rules, load_waivers

RULES_DIR = Path(__file__).resolve().parents[2] / "scripts" / "rules"
TESTS_DIR = Path(__file__).resolve().parent


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
    path.write_text(json.dumps({"violations": entries}), encoding="utf-8")


def test_baselined_violation_is_downgraded_to_a_warning(repo):
    rel = write(repo, "agents/legacy/notes.txt", ELF_BYTES)
    _write_baseline(repo, [{"rule_id": "POL-008", "file": rel}])
    result = run_rule(repo, POL_008, [rel])
    assert result.blocking == []
    assert len(result.warnings) == 1
    assert "pre-existing" in result.warnings[0].message


def test_new_violation_still_blocks_when_a_baseline_exists(repo):
    old = write(repo, "agents/legacy/notes.txt", ELF_BYTES)
    new = write(repo, "agents/legacy/fresh.txt", ELF_BYTES)
    _write_baseline(repo, [{"rule_id": "POL-008", "file": old}])
    result = run_rule(repo, POL_008, [old, new])
    assert [f.file for f in result.blocking] == [new]
    assert [f.file for f in result.warnings] == [old]


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
