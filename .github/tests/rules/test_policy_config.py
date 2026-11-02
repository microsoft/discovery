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


def test_missing_required_policy_file_is_a_config_error(repo):
    """A required security-control policy file must fail closed when absent.

    ``source-allowlist.yaml``, ``base-images.yaml`` and ``tag-taxonomy.yaml``
    back TAG/POL enforcement; deleting one must not silently skip those checks.
    """
    for name in POLICY_FILES:
        scratch = repo
        target = scratch / ".github" / "policy" / name
        backup = target.read_text(encoding="utf-8")
        target.unlink()
        try:
            policy = PolicyConfig.load(scratch)
            assert f".github/policy/{name}" in _errored_files(policy), name
        finally:
            target.write_text(backup, encoding="utf-8")


def test_empty_required_policy_file_is_a_config_error(repo):
    """An empty required policy file disables enforcement just like a missing
    one, so it must also be a config error rather than an empty policy."""
    write_policy(repo, "tag-taxonomy.yaml", "\n")
    policy = PolicyConfig.load(repo)
    assert ".github/policy/tag-taxonomy.yaml" in _errored_files(policy)


def test_missing_required_file_blocks_validation_with_cfg_002(repo):
    """A missing required policy file must surface as a blocking CFG-002."""
    changed = write(repo, "agents/demo/README.md", "# demo\n")
    (repo / ".github" / "policy" / "tag-taxonomy.yaml").unlink()
    result = run_validation(repo, [changed])
    cfg = [f for f in result.blocking if f.rule_id == "CFG-002"]
    assert cfg, "a missing required policy must produce a blocking CFG-002 failure"
    assert any("tag-taxonomy.yaml" in f.file for f in cfg)


def test_empty_mapping_required_policy_file_is_a_config_error(repo):
    """A required policy reduced to an empty mapping (``{}``) disables its
    checks just like an empty or missing file, so it must be a config error."""
    write_policy(repo, "tag-taxonomy.yaml", "{}\n")
    policy = PolicyConfig.load(repo)
    assert ".github/policy/tag-taxonomy.yaml" in _errored_files(policy)


def test_taxonomy_without_control_keys_is_a_config_error(repo):
    """A tag-taxonomy that parses as a mapping but omits ``domains`` and
    ``reserved_prefixes`` would silently pass TAG-001/TAG-002, so its missing
    control keys must be a config error."""
    write_policy(repo, "tag-taxonomy.yaml", "unrelated: true\n")
    policy = PolicyConfig.load(repo)
    errors = dict(policy.config_errors)
    assert ".github/policy/tag-taxonomy.yaml" in errors
    joined = errors[".github/policy/tag-taxonomy.yaml"]
    assert "domains" in joined or "reserved_prefixes" in joined


def test_wrong_typed_extensions_is_a_config_error(repo):
    """A scalar where a list of extensions is expected must be rejected, not
    coerced into a one-element string list."""
    write_policy(repo, "source-allowlist.yaml", "extensions: .py\n")
    policy = PolicyConfig.load(repo)
    assert ".github/policy/source-allowlist.yaml" in _errored_files(policy)


def test_wrong_typed_bool_is_a_config_error(repo):
    """``allow_docker_official_images: "false"`` must not silently become
    ``True`` via ``bool("false")``."""
    write_policy(
        repo,
        "base-images.yaml",
        "registries:\n  - host: mcr.microsoft.com\n"
        'allow_docker_official_images: "false"\n',
    )
    policy = PolicyConfig.load(repo)
    assert ".github/policy/base-images.yaml" in _errored_files(policy)


def test_wrong_typed_domains_is_a_config_error(repo):
    """``domains`` must be a mapping of tag-lists, not a bare list."""
    write_policy(repo, "tag-taxonomy.yaml", "domains:\n  - chemistry\n  - biology\n")
    policy = PolicyConfig.load(repo)
    assert ".github/policy/tag-taxonomy.yaml" in _errored_files(policy)


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
