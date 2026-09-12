"""Regression tests for the scheduled aka.ms release probe workflow."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "probe-aka-ms.yml"
UPSTREAM_MAIN_GUARD = (
    "github.repository == 'microsoft/discovery' && "
    "github.ref == 'refs/heads/main'"
)


def _workflow() -> dict:
    """Load strings without YAML 1.1 coercing the top-level ``on`` key."""
    return yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _probe_script() -> str:
    workflow = _workflow()
    steps = workflow["jobs"]["probe"]["steps"]
    return next(step["run"] for step in steps if step["name"] == "Probe aka.ms and decide")


def _bash_executable() -> str | None:
    """Prefer Git Bash on Windows; use PATH everywhere else."""
    git_bash = os.path.join(
        os.environ.get("ProgramFiles", ""), "Git", "bin", "bash.exe"
    )
    candidates = [git_bash, shutil.which("bash")] if os.name == "nt" else [shutil.which("bash")]
    return next((candidate for candidate in candidates if candidate and Path(candidate).is_file()), None)


def test_schedule_and_jobs_are_restricted_to_upstream_main() -> None:
    workflow = _workflow()

    assert workflow["on"]["schedule"] == [{"cron": "0 * * * *"}]
    assert workflow["jobs"]["probe"]["if"] == UPSTREAM_MAIN_GUARD

    failure_guard = workflow["jobs"]["report-failure"]["if"]
    assert "always()" in failure_guard
    assert "needs.probe.result == 'failure'" in failure_guard
    assert UPSTREAM_MAIN_GUARD in " ".join(failure_guard.split())


def test_probe_script_handles_newline_terminated_resolver_output(tmp_path: Path) -> None:
    """Exercise the exact Bash path that previously exited at the first ``read``.

    Bash ``read`` returns failure at EOF when command-substitution output has no
    terminating newline. With ``set -e`` that aborted the workflow immediately
    after parsing the README. This test executes the embedded workflow script,
    rather than a separately maintained reimplementation, to prevent regression.
    """
    bash = _bash_executable()
    if bash is None:
        pytest.skip("Bash is required to execute the workflow script")

    (tmp_path / "README.md").write_text(
        "Current release: <strong>v0.15.13</strong>\n", encoding="utf-8"
    )
    output_path = tmp_path / "github-output.txt"
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    curl = mock_bin / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
url="${!#}"
case "$url" in
  https://aka.ms/discovery/download/current)
    printf '%s' 'https://cdn.example/Discovery-app-0.15.13-preview-win-x64.exe'
    ;;
  https://aka.ms/discovery/download/previous)
    printf '%s' 'https://cdn.example/Discovery-app-0.15.12-preview-win-x64.exe'
    ;;
  *)
    printf '%s' 'Tue, 25 Aug 2026 14:21:41 GMT'
    ;;
esac
""",
        encoding="utf-8",
        newline="\n",
    )
    curl.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "CURRENT_URL": "https://aka.ms/discovery/download/current",
            "PREVIOUS_URL": "https://aka.ms/discovery/download/previous",
            "GITHUB_OUTPUT": str(output_path),
            "GH_TOKEN": "test-token",
            "PATH": f"{mock_bin}{os.pathsep}{env['PATH']}",
        }
    )
    result = subprocess.run(
        [bash, "-c", _probe_script()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "aka.ms current:  v0.15.13" in result.stdout
    assert "No change: README already at v0.15.13." in result.stdout
    assert output_path.read_text(encoding="utf-8").splitlines() == ["changed=false"]
