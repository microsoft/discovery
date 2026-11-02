"""TAG-002 — the CI-computed tag namespace is reserved."""

from __future__ import annotations

import pytest
from conftest import files, run_rule, write

from rules.tag_002 import RULE

META = "name: demo\ntype: agent\nversion: 1.0.0\ntags:\n{items}\n"


def _meta(repo, *tags):
    items = "\n".join(f"  - {t!r}" for t in tags)
    return write(repo, "agents/demo/metadata.yaml", META.format(items=items))


@pytest.mark.parametrize("tag", [
    "auto:has-tests",
    "auto:gpu-required",
    "tier:gold",
    "party:1p",
    "capability:anything",
])
def test_reserved_prefix_tags_are_blocked(repo, tag):
    rel = _meta(repo, tag)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "reserved prefix" in result.findings[0].message


def test_message_explains_why_self_assertion_is_rejected(repo):
    rel = _meta(repo, "tier:gold")
    result = run_rule(repo, RULE, [rel])
    assert "computed by CI" in result.findings[0].message


@pytest.mark.parametrize("tag", [
    "cheminformatics",
    "trained-model",
    "autodock",       # starts with "auto" but is not the "auto:" namespace
    "partytime",
    "tiered-storage",
])
def test_ordinary_tags_pass(repo, tag):
    rel = _meta(repo, tag)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_every_reserved_tag_is_reported(repo):
    rel = _meta(repo, "auto:has-tests", "tier:gold", "cheminformatics")
    result = run_rule(repo, RULE, [rel])
    assert len(result.findings) == 2


def test_no_shipped_agent_declares_a_reserved_tag(repo):
    from pathlib import Path

    import yaml

    from rules.base import PolicyConfig

    repo_root = Path(__file__).resolve().parents[3]
    prefixes = PolicyConfig.load(repo_root).reserved_tag_prefixes
    assert prefixes, "reserved prefixes failed to load"

    offenders = {}
    for meta in sorted((repo_root / "agents").glob("*/metadata.yaml")):
        data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
        bad = [
            str(t) for t in (data.get("tags") or [])
            if any(str(t).lower().startswith(p) for p in prefixes)
        ]
        if bad:
            offenders[meta.parent.name] = bad

    assert not offenders, f"Agents declaring reserved tags: {offenders}"
