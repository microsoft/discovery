"""Regression coverage for validation behavior outside catalog roots."""

from __future__ import annotations

from catalog_validation import policy_checks
from catalog_validation.runner import run_validation


def test_non_catalog_change_skips_new_catalog_configuration(tmp_path):
    policy = tmp_path / ".github" / "policy"
    policy.mkdir(parents=True)
    (policy / "source-allowlist.yaml").write_text(
        "not: [valid: yaml\n",
        encoding="utf-8",
    )
    (policy / "base-images.yaml").write_text(
        "not: [valid: yaml\n",
        encoding="utf-8",
    )
    (policy / "tag-taxonomy.yaml").write_text(
        "not: [valid: yaml\n",
        encoding="utf-8",
    )

    files = {
        "utilities/example/Dockerfile": "FROM unapproved.example/image:latest\n",
        "utilities/example/tool.py": "print('utility')\n",
        "docs/examples/payload.py": "print('documentation example')\n",
        "includes/media/active.svg": "<svg><script>alert(1)</script></svg>\n",
    }
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    result = run_validation(tmp_path, list(files))

    assert result.passed
    assert result.blocking == []
    assert result.setup_warnings == []
    assert result.contribution.has_agents is False
    assert result.contribution.has_markdown_only is False
    assert result.contribution.has_dockerfile is False
    assert result.contribution.has_code is False
    assert result.contribution.has_1p is False
    assert result.contribution.has_3p is False
    assert result.contribution.image_files == []


def test_non_catalog_change_keeps_legacy_hidden_artifact_check(tmp_path):
    path = tmp_path / "utilities" / "example" / ".env"
    path.parent.mkdir(parents=True)
    path.write_text("SECRET=placeholder\n", encoding="utf-8")

    result = run_validation(tmp_path, ["utilities/example/.env"])

    assert [failure.rule_id for failure in result.blocking] == ["POL-010"]


def test_non_catalog_change_keeps_legacy_model_weight_check(
    tmp_path, monkeypatch
):
    path = tmp_path / "utilities" / "example" / "model.pt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a model")
    monkeypatch.setattr(
        policy_checks,
        "_is_lfs_tracked_strict",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        policy_checks,
        "sniff",
        lambda path: (False, "invalid header"),
    )

    result = run_validation(tmp_path, ["utilities/example/model.pt"])

    assert [failure.rule_id for failure in result.blocking] == ["POL-009"]
