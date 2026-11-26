"""Distribution boundaries, configuration, and actual workspace installer behavior."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from discovery_physics.core import config, integrity
from discovery_physics.openfoam import runner

ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")


@pytest.fixture
def private_config(tmp_path, monkeypatch):
    for name in ("DISCOVERY_PHYSICS_CONFIG", "DISCOVERY_PHYSICS_IMAGE",
                 "DISCOVERY_PHYSICS_RUNTIME", "DISCOVERY_PHYSICS_KEY_FILE",
                 "DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS", "DISCOVERY_PHYSICS_MAX_CONCURRENT",
                 "DISCOVERY_PHYSICS_RUNS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISCOVERY_PHYSICS_HOME", str(tmp_path / "private"))
    config.home().mkdir()
    return config.config_path()


def test_portable_data_root_does_not_copy_old_keys(private_config):
    assert integrity.key_path() == private_config.parent / "keys/journal.key"
    assert runner.runs_root() == private_config.parent / "runs"
    assert not integrity.key_path().exists()  # Selection alone must not create/read a key.
    assert config.load()["allow_unenforced_limits"] is False


def test_operator_selection_and_environment_precedence(private_config, monkeypatch):
    private_config.write_text(json.dumps({
        "image": "localhost/approved:1", "runtime": "docker", "max_concurrent_runs": 1,
    }), encoding="utf-8")
    assert runner.image() == "localhost/approved:1"
    monkeypatch.setattr(shutil, "which", lambda value: value if value == "docker" else None)
    assert runner.container_runtime() == "docker"
    monkeypatch.setenv("DISCOVERY_PHYSICS_IMAGE", "localhost/another:2")
    assert runner.image() == "localhost/another:2"
    monkeypatch.setenv("DISCOVERY_PHYSICS_RUNTIME", "missing-engine")
    with pytest.raises(RuntimeError, match="Configured container runtime is unavailable"):
        runner.container_runtime()
    assert config.load()["max_concurrent_runs"] == 1
    assert config.load()["allow_unenforced_limits"] is False


def test_absolute_runtime_executable_preserves_policy_and_podman_selection(private_config, monkeypatch):
    # Use a real installed executable for lookup only; no runtime/container is
    # invoked. shutil.which supports absolute paths without a production patch.
    executable = str(Path(sys.executable).resolve())
    private_config.write_text(json.dumps({"runtime": executable}), encoding="utf-8")
    monkeypatch.setenv("CONTAINER_CONNECTION", "synthetic-native-connection")
    assert runner.container_runtime() == executable
    cfg = config.load()
    assert cfg["allow_unenforced_limits"] is False and cfg["max_concurrent_runs"] == 2
    assert os.environ["CONTAINER_CONNECTION"] == "synthetic-native-connection"
    assert "CONTAINER_CONNECTION" not in cfg  # Podman, not the physics loader, owns this.


def test_public_operator_example_is_safe(private_config):
    example = (ROOT / "config/operator.example.json").read_bytes()
    private_config.write_bytes(example)
    cfg = config.load()
    assert cfg["image"] == runner.DEFAULT_IMAGE
    assert cfg["runtime"] == "auto" and cfg["allow_unenforced_limits"] is False


def test_standalone_skill_and_companion_identity():
    for file in (ROOT / "skills/phy-openfoam/SKILL.md", ROOT / "integrations/phy-openfoam.agent.md"):
        text = file.read_text(encoding="utf-8")
        frontmatter = yaml.safe_load(text.split("---", 2)[1])
        assert frontmatter["name"] == "phy-openfoam"
        assert "DISCOVERY_PHYSICS_CLI" in text
        assert "physics-openfoam" not in text
    assert ".github/skills/phy-openfoam/SKILL.md" in (ROOT / "docs/installation.md").read_text(encoding="utf-8")


def _install(project: Path, *args: str, entry: Path = ROOT):
    script = str(entry / "scripts/install-workspace.ps1")
    # pytest may use the Windows extended-length prefix for deep fixture data.
    # PowerShell's -File authorization layer rejects that prefix even when the
    # actual copied script has a valid ordinary path. Keep the same file/bytes;
    # do not change execution policy or skip installer execution.
    if os.name == "nt" and script.startswith("\\\\?\\") and not script.startswith("\\\\?\\UNC\\"):
        script = script[4:]
    return subprocess.run([
        PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
        script, "-ProjectPath", str(project), *args,
    ], capture_output=True, text=True, encoding="utf-8", check=False)


def _staged_workspace_entry(tmp_path: Path) -> Path:
    entry = tmp_path / "supplied entry"
    (entry / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/install-workspace.ps1", entry / "scripts/install-workspace.ps1")
    shutil.copytree(ROOT / "skills/phy-openfoam", entry / "skills/phy-openfoam")
    (entry / "integrations").mkdir()
    shutil.copy2(ROOT / "integrations/phy-openfoam.agent.md", entry / "integrations/phy-openfoam.agent.md")
    return entry


@pytest.mark.skipif(not PWSH, reason="PowerShell is required to exercise workspace installation")
def test_workspace_installation_is_separate_idempotent_and_collision_safe(tmp_path):
    project = tmp_path / "existing project"
    project.mkdir()
    instructions = project / ".github/copilot-instructions.md"
    instructions.parent.mkdir()
    instructions.write_bytes(b"existing project policy\r\n")
    other = project / ".github/agents/unrelated.agent.md"
    other.parent.mkdir()
    other.write_text("unrelated", encoding="utf-8")
    first = _install(project)
    assert first.returncode == 0, first.stderr
    skill = project / ".github/skills/phy-openfoam/SKILL.md"
    helper = project / ".github/skills/phy-openfoam/scripts/render_report.py"
    results_helper = project / ".github/skills/phy-openfoam/scripts/project_results.py"
    assert skill.read_bytes() == (ROOT / "skills/phy-openfoam/SKILL.md").read_bytes()
    assert helper.read_bytes() == (ROOT / "skills/phy-openfoam/scripts/render_report.py").read_bytes()
    assert results_helper.read_bytes() == (
        ROOT / "skills/phy-openfoam/scripts/project_results.py"
    ).read_bytes()
    installed_files = (skill, helper, results_helper)
    installed_times = tuple(file.stat().st_mtime_ns for file in installed_files)
    assert not (project / ".github/agents/phy-openfoam.agent.md").exists()
    assert _install(project).returncode == 0
    assert tuple(file.stat().st_mtime_ns for file in installed_files) == installed_times
    assert _install(project, "-IncludeAgent").returncode == 0
    assert (project / ".github/agents/phy-openfoam.agent.md").read_bytes() == (
        ROOT / "integrations/phy-openfoam.agent.md"
    ).read_bytes()
    skill.write_text("locally customized", encoding="utf-8")
    refused = _install(project)
    assert refused.returncode != 0 and "Existing file differs" in refused.stderr
    assert skill.read_text(encoding="utf-8") == "locally customized"
    assert _install(project, "-Force").returncode == 0
    assert instructions.read_bytes() == b"existing project policy\r\n"
    assert other.read_text(encoding="utf-8") == "unrelated"
    assert not list(project.rglob("*.exe")) and not (project / "venv").exists()


@pytest.mark.skipif(not PWSH, reason="PowerShell is required to exercise workspace installation")
def test_workspace_preflight_does_not_partially_copy(tmp_path):
    project = tmp_path / "project"
    agent = project / ".github/agents/phy-openfoam.agent.md"
    agent.parent.mkdir(parents=True)
    agent.write_text("existing custom agent", encoding="utf-8")
    result = _install(project, "-IncludeAgent")
    assert result.returncode != 0
    assert not (project / ".github/skills/phy-openfoam/SKILL.md").exists()
    assert agent.read_text(encoding="utf-8") == "existing custom agent"


@pytest.mark.skipif(not PWSH, reason="PowerShell is required to exercise workspace installation")
@pytest.mark.parametrize("helper_name", ("render_report.py", "project_results.py"))
def test_workspace_helper_collision_prevents_all_partial_copy(tmp_path, helper_name):
    project = tmp_path / "project"
    helper = project / ".github/skills/phy-openfoam/scripts" / helper_name
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b"existing custom skill helper\r\n")
    refused = _install(project, "-IncludeAgent")
    assert refused.returncode != 0 and "Existing file differs" in refused.stderr
    assert not (project / ".github/skills/phy-openfoam/SKILL.md").exists()
    assert not (project / ".github/agents").exists()
    assert helper.read_bytes() == b"existing custom skill helper\r\n"
    assert _install(project, "-IncludeAgent", "-Force").returncode == 0
    assert helper.read_bytes() == (ROOT / "skills/phy-openfoam/scripts" / helper_name).read_bytes()


@pytest.mark.skipif(not PWSH, reason="PowerShell is required to exercise workspace installation")
def test_workspace_helper_parent_collision_prevents_all_partial_copy(tmp_path):
    project = tmp_path / "project"
    scripts = project / ".github/skills/phy-openfoam/scripts"
    scripts.parent.mkdir(parents=True)
    scripts.write_bytes(b"existing file, not a directory\r\n")
    refused = _install(project, "-IncludeAgent", "-Force")
    assert refused.returncode != 0 and "Destination parent" in refused.stderr
    assert scripts.read_bytes() == b"existing file, not a directory\r\n"
    assert not (project / ".github/skills/phy-openfoam/SKILL.md").exists()
    assert not (project / ".github/agents").exists()


@pytest.mark.skipif(not PWSH, reason="PowerShell is required to exercise workspace installation")
def test_workspace_missing_helper_refuses_before_copy(tmp_path):
    entry = _staged_workspace_entry(tmp_path)
    (entry / "skills/phy-openfoam/scripts/render_report.py").unlink()
    project = tmp_path / "project"
    project.mkdir()
    refused = _install(project, "-IncludeAgent", entry=entry)
    assert refused.returncode != 0 and "Required skill resource is missing" in refused.stderr
    assert not (project / ".github").exists()


@pytest.mark.skipif(not PWSH, reason="PowerShell is required to exercise workspace installation")
def test_workspace_missing_project_results_helper_refuses_before_copy(tmp_path):
    entry = _staged_workspace_entry(tmp_path)
    (entry / "skills/phy-openfoam/scripts/project_results.py").unlink()
    project = tmp_path / "project"
    project.mkdir()
    refused = _install(project, "-IncludeAgent", "-Force", entry=entry)
    assert refused.returncode != 0 and "Required skill resource is missing" in refused.stderr
    assert "project_results.py" in refused.stderr
    assert not (project / ".github").exists()


@pytest.mark.skipif(not PWSH, reason="PowerShell is required to exercise workspace installation")
def test_workspace_copies_all_supplied_resources_but_not_caches(tmp_path):
    entry = _staged_workspace_entry(tmp_path)
    supplied = entry / "skills/phy-openfoam"
    asset = supplied / "assets/report-context.json"
    asset.parent.mkdir()
    asset.write_bytes(b'{"kind":"input geometry context"}\n')
    for name in ("__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".venv"):
        cache = supplied / "scripts" / name
        cache.mkdir(exist_ok=True)
        (cache / "do-not-copy.txt").write_bytes(b"generated cache\n")
    for name in ("loose.pyc", "loose.pyo"):
        (supplied / "scripts" / name).write_bytes(b"generated bytecode\n")
    project = tmp_path / "project"
    project.mkdir()
    installed = _install(project, entry=entry)
    assert installed.returncode == 0, installed.stderr
    destination = project / ".github/skills/phy-openfoam"
    assert (destination / "assets/report-context.json").read_bytes() == asset.read_bytes()
    for helper_name in ("render_report.py", "project_results.py"):
        assert (destination / "scripts" / helper_name).read_bytes() == (
            supplied / "scripts" / helper_name
        ).read_bytes()
    assert not list(destination.rglob("do-not-copy.txt"))
    assert not list(destination.rglob("*.pyc")) and not list(destination.rglob("*.pyo"))


@pytest.mark.skipif(not PWSH or os.name != "nt", reason="Windows PowerShell installer check")
def test_runtime_whatif_does_not_install_workspace_or_change_host(tmp_path):
    destination = tmp_path / "runtime"
    result = subprocess.run([
        PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
        str(ROOT / "scripts/install-runtime.ps1"), "-InstallRoot", str(destination), "-WhatIf",
    ], capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 0, result.stderr
    assert not destination.exists()


def test_documentation_does_not_link_private_history_or_parent_files():
    import re

    for file in ROOT.rglob("*.md"):
        if any(part in {"local-evidence", "__pycache__", ".pytest_cache"} for part in file.parts):
            continue
        # Ignore illustrative fenced paths. Check actual inline Markdown file links.
        text = re.sub(r"```[^\n]*\n.*?```", "", file.read_text(encoding="utf-8"), flags=re.S)
        for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^\s)]+)\)", text):
            if target.startswith(("https:", "http:", "mailto:", "#")):
                continue
            path = (file.parent / target.split("#", 1)[0].replace("%20", " ")).resolve()
            assert path.is_relative_to(ROOT.resolve()), (file, target)
            assert "local-evidence" not in path.relative_to(ROOT.resolve()).parts, (file, target)
            assert path.exists(), (file, target)