"""Policy loaders must fail loud, never fail open.

A malformed or wrongly-shaped policy file (``source-allowlist.yaml``,
``base-images.yaml``, ``tag-taxonomy.yaml``) previously parsed to ``{}`` and
silently disabled the checks that depend on it. These tests pin the corrected
behaviour: a parse failure or a non-mapping top-level document is surfaced as a
structured configuration error, and the runner turns it into a blocking
``CFG-002`` failure.
"""

from __future__ import annotations

from pathlib import Path

from conftest import write, write_policy

from catalog_validation.runner import run_validation
from rules.base import PolicyConfig

POLICY_FILES = ["source-allowlist.yaml", "base-images.yaml", "tag-taxonomy.yaml"]


def _errored_files(policy: PolicyConfig) -> set[str]:
    return {rel for rel, _ in policy.config_errors}


def test_real_policy_loads_without_config_errors(repo):
    """The shipped policy files must always load as mappings."""
    assert PolicyConfig.load(repo).config_errors == ()


def test_missing_policy_file_is_not_a_config_error(repo):
    """An absent optional policy file is unconfigured, not broken."""
    (repo / ".github" / "policy" / "tag-taxonomy.yaml").unlink()
    policy = PolicyConfig.load(repo)
    assert ".github/policy/tag-taxonomy.yaml" not in _errored_files(policy)
    assert policy.domain_tags == frozenset()


def test_malformed_source_allowlist_is_a_config_error(repo):
    write_policy(repo, "source-allowlist.yaml", "extensions: [ .py, .md\n")
    policy = PolicyConfig.load(repo)
    assert ".github/policy/source-allowlist.yaml" in _errored_files(policy)


def test_non_mapping_base_images_is_a_config_error(repo):
    # A top-level list, not a mapping.
    write_policy(repo, "base-images.yaml", "- alpine\n- ubuntu\n")
    policy = PolicyConfig.load(repo)
    errors = dict(policy.config_errors)
    assert ".github/policy/base-images.yaml" in errors
    assert "mapping" in errors[".github/policy/base-images.yaml"]


def test_non_mapping_tag_taxonomy_is_a_config_error(repo):
    # A bare scalar, not a mapping.
    write_policy(repo, "tag-taxonomy.yaml", "just-a-string\n")
    policy = PolicyConfig.load(repo)
    assert ".github/policy/tag-taxonomy.yaml" in _errored_files(policy)


def test_malformed_policy_blocks_validation_with_cfg_002(repo):
    """The runner promotes a policy config error to a blocking failure."""
    changed = write(repo, "agents/demo/README.md", "# demo\n")
    write_policy(repo, "tag-taxonomy.yaml", "domains: [ unterminated\n")
    result = run_validation(repo, [changed])
    cfg = [f for f in result.blocking if f.rule_id == "CFG-002"]
    assert cfg, "a malformed policy must produce a blocking CFG-002 failure"
    assert any("tag-taxonomy.yaml" in f.file for f in cfg)
