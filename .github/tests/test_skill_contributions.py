"""Top-level skills receive catalog content checks without executing skill code."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from catalog_validation.runner import run_validation
from generate_baseline import tracked_files


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def skill_repo(tmp_path: Path) -> Path:
    for relative in (".github/policy", "docs/schemas"):
        shutil.copytree(REPO_ROOT / relative, tmp_path / relative)
    return tmp_path


def write(repo: Path, relative: str, content: str | bytes) -> str:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return relative


def test_public_skill_scripts_and_paper_templates_pass_without_execution(skill_repo):
    files = [
        write(skill_repo, "skills/paper/SKILL.md", "# Paper skill\n"),
        write(
            skill_repo,
            "skills/paper/scripts/build.sh",
            "#!/bin/bash\nexit 99\n",
        ),
        write(
            skill_repo,
            "skills/paper/templates/generate_figures.py",
            "raise RuntimeError('Skill code must not execute during validation')\n",
        ),
        write(skill_repo, "skills/paper/templates/main.tex", "\\documentclass{article}\n"),
        write(skill_repo, "skills/paper/templates/references.bib", "@article{demo,}\n"),
        write(skill_repo, "skills/paper/requirements.txt", "matplotlib>=3.9\n"),
    ]

    result = run_validation(skill_repo, files, author_permission="read", author="octocat")

    assert result.passed, result.to_dict()
    assert result.contribution.has_code
    assert not result.contribution.has_agents
    assert not result.contribution.has_1p
    assert not result.contribution.has_3p


def test_commonjs_only_skill_change_is_permitted_and_classified_as_code(skill_repo):
    relative = write(
        skill_repo, "skills/demo/scripts/helper.cjs",
        "throw new Error('Submitted CommonJS must not execute during validation');\n",
    )

    result = run_validation(skill_repo, [relative], author_permission="read")

    assert result.passed, result.to_dict()
    assert result.contribution.has_code


@pytest.mark.parametrize(("filename", "content", "rule_id"), [
    ("notes.txt", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< >>\nendobj\n", "POL-008"),
    ("notes.unknownext", "reviewable but unapproved type\n", "POL-015"),
    ("diagram.svg", '<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>', "POL-016"),
    ("SKILL.md", "# Unsafe \u202e text\n", "POL-020"),
    ("Dockerfile", "FROM unapproved.example/image:latest\n", "POL-014"),
    ("Containerfile", "FROM python:3.12-slim\n", "POL-022"),
    (".env", "SECRET=placeholder\n", "POL-010"),
    ("model.pt", b"not a model", "POL-009"),
])
def test_skill_content_violations_still_block(skill_repo, filename, content, rule_id):
    relative = write(skill_repo, f"skills/demo/{filename}", content)

    result = run_validation(
        skill_repo, [relative], author_permission="none", author="octocat"
    )

    assert not result.passed
    assert (rule_id, relative) in {
        (failure.rule_id, failure.file) for failure in result.blocking
    }
    assert not any(failure.rule_id == "POL-021" for failure in result.blocking)


def test_skill_dockerfiles_keep_reproducibility_warnings(skill_repo):
    relative = write(skill_repo, "skills/demo/Dockerfile", "FROM python:latest\n")

    result = run_validation(skill_repo, [relative], author_permission="read")

    assert result.passed, result.to_dict()
    assert [(failure.rule_id, failure.file) for failure in result.warnings] == [
        ("POL-017", relative),
    ]
    assert result.contribution.has_dockerfile


def test_skill_changes_fail_closed_on_invalid_policy(skill_repo):
    relative = write(skill_repo, "skills/demo/SKILL.md", "# Demo\n")
    write(skill_repo, ".github/policy/source-allowlist.yaml", "not: [valid: yaml\n")

    result = run_validation(skill_repo, [relative], author_permission="read")

    assert not result.passed
    assert any(failure.rule_id == "CFG-002" for failure in result.blocking)


def test_skill_images_are_classified_and_revalidated_on_markdown_edits(skill_repo):
    markdown = write(skill_repo, "skills/demo/SKILL.md", "![Diagram](diagram.svg)\n")
    image = write(
        skill_repo, "skills/demo/diagram.svg",
        '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>',
    )

    result = run_validation(skill_repo, [markdown, image], author_permission="read")

    assert result.passed, result.to_dict()
    assert result.contribution.image_files == [image]

    write(skill_repo, markdown, "# Diagram removed\n")
    result = run_validation(skill_repo, [markdown], author_permission="read")

    assert [(failure.rule_id, failure.file) for failure in result.blocking] == [
        ("POL-016", image),
    ]


@pytest.mark.parametrize("use_git", [False, True])
def test_full_catalog_file_lists_include_skills(tmp_path, use_git):
    relative = write(tmp_path, "skills/demo/SKILL.md", "# Demo\n")
    if use_git:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        subprocess.run(["git", "add", "--", relative], cwd=tmp_path, check=True)

    assert tracked_files(tmp_path) == [relative]


@pytest.mark.parametrize(("files", "expected"), [
    (["skills/demo/SKILL.md"], "true"),
    (["skills/demo/scripts/build.sh"], "true"),
    (["skills-other/demo/script.py"], "false"),
    ([".github/skills/demo/SKILL.md"], "false"),
])
def test_pr_workflow_classifies_top_level_skills_as_catalog(files, expected):
    workflow = yaml.load(
        (REPO_ROOT / ".github/workflows/pr-review.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    script = workflow["jobs"]["classify"]["steps"][0]["with"]["script"]
    harness = """
const outputs = {};
const core = {setOutput: (key, value) => {outputs[key] = value;}, info: () => {}};
const context = {repo: {owner: 'microsoft', repo: 'discovery'},
                 payload: {pull_request: {number: 1}}};
const github = {paginate: async () => FILES.map(filename => ({filename})),
                rest: {pulls: {listFiles: {}}}};
(async () => { SCRIPT
console.log(JSON.stringify(outputs)); })();
""".replace("FILES", json.dumps(files)).replace("SCRIPT", script)
    result = subprocess.run(
        ["node", "-e", harness], capture_output=True, text=True, check=True
    )

    assert json.loads(result.stdout)["has_catalog"] == expected
