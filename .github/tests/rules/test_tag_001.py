"""TAG-001 — declared tags must come from the controlled vocabulary."""

from __future__ import annotations

import pytest
from conftest import files, run_rule, write

from rules.tag_001 import RULE

META = "name: demo\ntype: agent\nversion: 1.0.0\ntags:\n{items}\n"


def _meta(repo, *tags):
    items = "\n".join(f"  - {t}" for t in tags)
    return write(repo, "agents/demo/metadata.yaml", META.format(items=items))


@pytest.mark.parametrize("tag", [
    "cheminformatics",
    "trained-model",
    "protein-folding",
    "static-timing-analysis",
    "quantum-chemistry",
    "gpu",
])
def test_vocabulary_tags_pass(repo, tag):
    rel = _meta(repo, tag)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_unknown_tag_is_blocked(repo):
    rel = _meta(repo, "cheminformatics", "quantum-flux-capacitor")
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "quantum-flux-capacitor" in result.findings[0].message


def test_near_synonym_gets_a_suggestion(repo):
    rel = _meta(repo, "protein-folding-prediction")
    result = run_rule(repo, RULE, [rel])
    assert len(result.findings) == 1
    assert "Did you mean" in result.findings[0].message
    assert "protein-folding" in result.findings[0].message


def test_every_unknown_tag_is_reported(repo):
    rel = _meta(repo, "cheminformatics", "made-up-one", "made-up-two")
    result = run_rule(repo, RULE, [rel])
    assert len(result.findings) == 2


def test_reserved_prefix_tags_are_left_to_tag_002(repo):
    rel = _meta(repo, "auto:has-tests")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_agent_without_metadata_is_skipped(repo):
    rel = write(repo, "agents/demo/README.md", "# Demo\n")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_every_tag_in_the_catalog_is_in_the_taxonomy(repo):
    """The vocabulary must already cover all 46 shipped agents."""
    from pathlib import Path

    import yaml

    from rules.base import PolicyConfig

    repo_root = Path(__file__).resolve().parents[3]
    vocabulary = PolicyConfig.load(repo_root).domain_tags
    assert vocabulary, "tag taxonomy failed to load"

    missing: dict[str, list[str]] = {}
    for meta in sorted((repo_root / "agents").glob("*/metadata.yaml")):
        data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
        unknown = [
            str(t) for t in (data.get("tags") or [])
            if str(t).lower() not in vocabulary
        ]
        if unknown:
            missing[meta.parent.name] = unknown

    assert not missing, f"Tags used in the catalog but absent from the taxonomy: {missing}"
