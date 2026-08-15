"""compute_tags — CI-derived capability, provenance, and assurance tags.

These tags are only meaningful if they are facts. The tests below pin the
derivation rules so a change that makes a tier easier to reach has to be
deliberate.
"""

from __future__ import annotations

import shutil

import pytest
from conftest import write

from compute_tags import compute_all, compute_for_agent
from rules.base import PolicyConfig

META = """\
name: demo
type: agent
version: 1.0.0
publisher:
  name: Example
  contact: a@example.com
  support_url: https://example.com
  party: {party}
description: A demo agent used in tests.
tags:
  - cheminformatics
"""

TOOL = """\
name: demo
description: A demo tool.
version: 1.0.0
category: "Scientific Computing"
infra:
  - name: worker
    infra_type: container
    image:
      acr: "{{name}}.azurecr.io/demo:1.0.0"
    compute:
      min_resources:
        cpu: 1
        ram: 4Gi
        gpu: {gpu}
"""


def _agent(repo, *, party="1p", tools=True, gpu=0, tests=False,
           examples=False, notices=False, base="ubuntu:24.04"):
    # Rebuild from scratch so tests that call this twice stay independent.
    shutil.rmtree(repo / "agents" / "demo", ignore_errors=True)
    write(repo, "agents/demo/metadata.yaml", META.format(party=party))
    write(repo, "agents/demo/README.md", "# Demo\n")
    if tools:
        write(repo, "agents/demo/tools/t/tool.yaml", TOOL.format(gpu=gpu))
        write(repo, "agents/demo/tools/t/Dockerfile", f"FROM {base}\n")
        if tests:
            write(repo, "agents/demo/tools/t/test_demo_utils.py", "def test_x():\n    pass\n")
        if examples:
            write(repo, "agents/demo/tools/t/example-input-files/in.dat", "1\n")
    if notices:
        write(repo, "agents/demo/THIRD_PARTY_NOTICES.md", "# Notices\n")
    return repo / "agents" / "demo"


def _compute(repo, agent):
    return compute_for_agent(repo, agent, PolicyConfig.load(repo))


# ── Capability tags ──────────────────────────────────────────────────────────

def test_agent_with_tools_is_tagged(repo):
    result = _compute(repo, _agent(repo))
    assert "auto:has-tools" in result["computed_tags"]
    assert "auto:no-tools" not in result["computed_tags"]


def test_prompt_only_agent_is_tagged(repo):
    result = _compute(repo, _agent(repo, tools=False))
    assert "auto:no-tools" in result["computed_tags"]


def test_tests_are_detected(repo):
    assert "auto:has-tests" in _compute(repo, _agent(repo, tests=True))["computed_tags"]
    assert "auto:has-tests" not in _compute(repo, _agent(repo))["computed_tags"]


def test_example_inputs_are_detected(repo):
    result = _compute(repo, _agent(repo, examples=True))
    assert "auto:has-example-inputs" in result["computed_tags"]


def test_third_party_notices_are_detected(repo):
    result = _compute(repo, _agent(repo, notices=True))
    assert "auto:third-party-notices" in result["computed_tags"]


def test_gpu_requirement_is_detected(repo):
    assert "auto:gpu-required" in _compute(repo, _agent(repo, gpu=1))["computed_tags"]
    assert "auto:gpu-required" not in _compute(repo, _agent(repo, gpu=0))["computed_tags"]


# ── Base image posture ───────────────────────────────────────────────────────

def test_docker_official_base_is_tagged(repo):
    result = _compute(repo, _agent(repo, base="ubuntu:24.04"))
    assert "auto:official-base-image" in result["computed_tags"]


def test_namespaced_base_is_not_official(repo):
    result = _compute(repo, _agent(repo, base="nvidia/cuda:12.6.3-devel-ubuntu22.04"))
    assert "auto:official-base-image" not in result["computed_tags"]


def test_pinned_and_floating_bases_are_distinguished(repo):
    assert "auto:pinned-base-image" in _compute(repo, _agent(repo, base="ubuntu:24.04"))["computed_tags"]
    assert "auto:pinned-base-image" not in _compute(repo, _agent(repo, base="ubuntu:latest"))["computed_tags"]


# ── Provenance ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("party", ["1p", "3p"])
def test_party_is_taken_from_metadata(repo, party):
    result = _compute(repo, _agent(repo, party=party))
    assert f"party:{party}" in result["computed_tags"]


# ── Assurance tiers ──────────────────────────────────────────────────────────

def test_bare_agent_is_bronze(repo):
    assert _compute(repo, _agent(repo))["tier"] == "bronze"


def test_floating_base_cannot_reach_silver(repo):
    result = _compute(repo, _agent(repo, tests=True, base="ubuntu:latest"))
    assert result["tier"] == "bronze"


def test_tests_plus_pinned_base_is_silver(repo):
    result = _compute(repo, _agent(repo, tests=True, base="ubuntu:24.04"))
    assert result["tier"] == "silver"


def test_full_complement_is_gold(repo):
    result = _compute(repo, _agent(
        repo, tests=True, examples=True, notices=True, base="ubuntu:24.04"))
    assert result["tier"] == "gold"


def test_gold_requires_example_inputs(repo):
    result = _compute(repo, _agent(repo, tests=True, notices=True, base="ubuntu:24.04"))
    assert result["tier"] == "silver"


def test_prompt_only_agent_is_bronze_not_penalised(repo):
    # No build to pin and no tool to test — it must not be held below bronze.
    result = _compute(repo, _agent(repo, tools=False))
    assert result["tier"] == "bronze"


def test_tier_tag_matches_tier_field(repo):
    result = _compute(repo, _agent(repo, tests=True, base="ubuntu:24.04"))
    assert f"tier:{result['tier']}" in result["computed_tags"]


# ── Whole-catalog output ─────────────────────────────────────────────────────
#
# .auto-registry/agent-tags.json is generated and committed by the registry bot
# (update-registry.yml), never by a contributor — POL-011 blocks hand-edits
# under .auto-registry/. So these assert on the computation, not on a file.

def _catalog_tags():
    from pathlib import Path

    return compute_all(Path(__file__).resolve().parents[3])


def test_computation_is_deterministic():
    """The bot regenerates this on every push; unstable output would churn."""
    from compute_tags import render

    assert render(_catalog_tags()) == render(_catalog_tags())


def test_every_catalog_agent_gets_exactly_one_tier():
    data = _catalog_tags()
    assert data["count"] == 46
    for entry in data["agents"]:
        tiers = [t for t in entry["computed_tags"] if t.startswith("tier:")]
        assert len(tiers) == 1, f"{entry['name']} has {tiers}"


def test_computed_tags_never_collide_with_declared_tags():
    """A declared tag must never land in the computed namespace, or TAG-002 lied."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    prefixes = PolicyConfig.load(repo_root).reserved_tag_prefixes
    for entry in _catalog_tags()["agents"]:
        for tag in entry["declared_tags"]:
            assert not any(tag.lower().startswith(p) for p in prefixes), entry["name"]
