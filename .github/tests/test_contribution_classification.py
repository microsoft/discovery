"""Tests for PR-only change-type labels."""

from pathlib import Path

from catalog_validation.contribution import classify_contribution


def classify(repo: Path, files: list[str]):
    return classify_contribution(repo, files, set(), set())


def test_only_markdown_files_get_markdown_only_label(tmp_path: Path):
    summary = classify(tmp_path, ["README.md", "agents/demo/GUIDE.MD"])
    assert summary.has_markdown_only
    assert not summary.has_code
    assert not summary.has_dockerfile


def test_markdown_mixed_with_any_other_file_is_not_markdown_only(tmp_path: Path):
    summary = classify(tmp_path, ["README.md", "agents/demo/metadata.yaml"])
    assert not summary.has_markdown_only


def test_empty_change_set_is_not_markdown_only(tmp_path: Path):
    assert not classify(tmp_path, []).has_markdown_only


def test_dockerfile_names_get_docker_label(tmp_path: Path):
    for name in ("Dockerfile", "Dockerfile.cpu", "build.windows.dockerfile"):
        summary = classify(tmp_path, [f"agents/demo/tools/demo/{name}"])
        assert summary.has_dockerfile, name


def test_code_extensions_get_code_label(tmp_path: Path):
    summary = classify(
        tmp_path,
        ["agents/demo/tool.py", "web/component.tsx", "scripts/build.ps1"],
    )
    assert summary.has_code
    assert not summary.has_markdown_only


def test_configuration_is_not_misclassified_as_code(tmp_path: Path):
    summary = classify(tmp_path, ["agent.yaml", "kit.json", "config.toml"])
    assert not summary.has_code
    assert not summary.has_dockerfile