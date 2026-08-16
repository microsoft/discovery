"""POL-018 — catalog webpage reachability."""

from __future__ import annotations

from conftest import files, run_rule, write

from rules import pol_018


def test_invalid_agent_support_page_is_reported(repo, monkeypatch):
    rel = write(
        repo,
        "agents/demo/metadata.yaml",
        "publisher:\n  support_url: https://example.invalid/support\n",
    )
    monkeypatch.setattr(pol_018, "validate_webpage", lambda *_: "host does not exist")

    result = run_rule(repo, pol_018.RULE, [rel])

    assert files(result) == [rel]
    assert result.findings[0].line == 2
    assert "publisher.support_url" in result.findings[0].message


def test_starter_kit_webpages_are_checked_once_per_unique_url(repo, monkeypatch):
    rel = write(
        repo,
        "starter-kits/demo/kit.json",
        '{\n  "author": {"url": "https://example.com"},\n'
        '  "homepage": "https://example.com",\n'
        '  "repository": "https://github.com/example/demo"\n}\n',
    )
    checked: list[str] = []

    def validate(value, policy):
        checked.append(value)
        return None

    monkeypatch.setattr(pol_018, "validate_webpage", validate)

    result = run_rule(repo, pol_018.RULE, [rel])

    assert result.findings == []
    assert checked == ["https://example.com", "https://github.com/example/demo"]


def test_starter_kit_author_url_reports_its_nested_source_line(repo, monkeypatch):
    rel = write(
        repo,
        "starter-kits/demo/kit.json",
        '{\n  "url": "https://example.com/unrelated",\n'
        '  "author": {\n    "url": "https://example.invalid/author"\n  }\n}\n',
    )
    monkeypatch.setattr(pol_018, "validate_webpage", lambda *_: "host does not exist")

    result = run_rule(repo, pol_018.RULE, [rel])

    assert result.findings[0].line == 4


def test_untouched_catalog_entries_are_not_checked(repo, monkeypatch):
    write(
        repo,
        "agents/demo/metadata.yaml",
        "publisher:\n  support_url: https://example.com/support\n",
    )
    monkeypatch.setattr(
        pol_018,
        "validate_webpage",
        lambda *_: (_ for _ in ()).throw(AssertionError("network call was not expected")),
    )

    result = run_rule(repo, pol_018.RULE, ["README.md"])

    assert result.findings == []