"""Contracts connecting POL-022 remediation, contributor docs, and the skill."""

from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = (
    REPO_ROOT
    / ".github"
    / "skills"
    / "migrate-podman-containerfile"
    / "SKILL.md"
)
GUIDE_PATH = (
    REPO_ROOT
    / "docs"
    / "authoring-guides"
    / "podman-to-docker-migration.md"
)


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    _, frontmatter, _ = text.split("---", 2)
    data = yaml.safe_load(frontmatter)
    assert isinstance(data, dict)
    return data


def test_skill_frontmatter_and_fail_closed_contract():
    data = _frontmatter(SKILL_PATH)
    text = SKILL_PATH.read_text(encoding="utf-8")

    assert data["name"] == SKILL_PATH.parent.name
    assert "Containerfile" in data["description"]
    assert "Creates the Dockerfile directly" in data["description"]
    assert "Never overwrite" in text
    assert "make no changes" in text
    assert "git mv" in text
    assert "docker buildx build --check" in text


def test_guide_links_to_skill_and_contributor_surfaces():
    guide = GUIDE_PATH.read_text(encoding="utf-8")
    agent_guide = (
        REPO_ROOT / "docs" / "authoring-guides" / "agent-authoring-guide.md"
    ).read_text(encoding="utf-8")
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    skills_index = (
        REPO_ROOT / ".github" / "skills" / "README.md"
    ).read_text(encoding="utf-8")

    assert "../../.github/skills/migrate-podman-containerfile/SKILL.md" in guide
    assert "/migrate-podman-containerfile " in guide
    assert "./podman-to-docker-migration.md" in agent_guide
    assert "docs/authoring-guides/podman-to-docker-migration.md" in contributing
    assert "migrate-podman-containerfile" in skills_index


def test_pr_review_keeps_compatibility_check_in_trusted_validator():
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "pr-review.yml"
    ).read_text(encoding="utf-8")

    assert "Policy (including Containerfiles)" in workflow
    assert "python trusted/.github/scripts/validate_pr.py" in workflow
    assert "docker build" not in workflow
    assert "podman build" not in workflow
