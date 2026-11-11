"""Contributor identity does not gate paths; content checks still apply."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from validate_pr import main


@pytest.mark.parametrize(("author", "permission", "association"), [
    ("employee", "read", "NONE"),
    ("employee", "unknown", "NONE"),
    ("employee", "read", "MEMBER"),
    ("Copilot", "none", "CONTRIBUTOR"),
    ("octocat", "read", "CONTRIBUTOR"),
])
def test_author_identity_cannot_block_repository_paths(
    tmp_path: Path, monkeypatch, author: str, permission: str, association: str,
) -> None:
    changed = [
        ".github/workflows/update-registry.yml",
        ".github/tests/test_security_automation.py",
        ".github/skills/example/SKILL.md",
        ".vscode/settings.json",
        ".config/dotnet-tools.json",
        ".gitattributes",
        "utilities/example/run.py",
        "utilities/terraform/main.tf",
        "utilities/README.md",
        "scripts/setup.py",
        "docs/schemas/example.json",
        "docs/validation-rules.md",
        "docs/discovery-services/setup.sh",
    ]
    for relative in changed:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "{}\n" if path.suffix == ".json" else "# Contributor fixture\n"
        if path.suffix == ".py":
            content = 'raise AssertionError("PR code must not execute")\n'
        path.write_text(content, encoding="utf-8")

    changed_file = tmp_path / "changed-files.txt"
    changed_file.write_text("\n".join(changed) + "\n", encoding="utf-8")
    output = tmp_path / "validation-results.json"
    monkeypatch.setenv("PR_AUTHOR", author)
    monkeypatch.setenv("PR_HEAD_REF", "contributor/change")
    monkeypatch.setenv("PR_AUTHOR_PERMISSION", permission)
    monkeypatch.setenv("PR_AUTHOR_ASSOCIATION", association)
    monkeypatch.setattr(sys, "argv", [
        "validate_pr.py", "--changed-files", str(changed_file),
        "--repo-root", str(tmp_path), "--output", str(output),
    ])

    with pytest.raises(SystemExit) as exited:
        main()

    result = json.loads(output.read_text(encoding="utf-8"))
    assert exited.value.code == 0, result
    assert result["passed"]
    assert result["failures"] == []
    assert result["warnings"] == []
