"""POL-019 — catalog email-domain DNS validation."""

from __future__ import annotations

from conftest import files, run_rule, write

from rules import pol_019


def test_invalid_agent_contact_domain_is_reported(repo, monkeypatch):
    rel = write(
        repo,
        "agents/demo/metadata.yaml",
        "publisher:\n  contact: owner@example.invalid\n",
    )
    monkeypatch.setattr(pol_019, "validate_email_domain", lambda *_: "domain does not exist")

    result = run_rule(repo, pol_019.RULE, [rel])

    assert files(result) == [rel]
    assert result.findings[0].line == 2
    assert "publisher.contact" in result.findings[0].message


def test_same_email_domain_is_resolved_once(repo, monkeypatch):
    agent_rel = write(
        repo,
        "agents/demo/metadata.yaml",
        "publisher:\n  contact: agent@example.com\n",
    )
    kit_rel = write(
        repo,
        "starter-kits/demo/kit.json",
        '{"author": {"email": "kit@example.com"}}\n',
    )
    checked: list[str] = []

    def validate(value, policy):
        checked.append(value)
        return None

    monkeypatch.setattr(pol_019, "validate_email_domain", validate)

    result = run_rule(repo, pol_019.RULE, [agent_rel, kit_rel])

    assert result.findings == []
    assert checked == ["agent@example.com"]


def test_untouched_catalog_entries_are_not_checked(repo, monkeypatch):
    write(
        repo,
        "agents/demo/metadata.yaml",
        "publisher:\n  contact: owner@example.com\n",
    )
    monkeypatch.setattr(
        pol_019,
        "validate_email_domain",
        lambda *_: (_ for _ in ()).throw(AssertionError("network call was not expected")),
    )

    result = run_rule(repo, pol_019.RULE, ["README.md"])

    assert result.findings == []