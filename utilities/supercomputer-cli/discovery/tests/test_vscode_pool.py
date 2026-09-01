"""Regression tests for ``discovery job vscode --pool`` resolution.

Covers ICM 822609036: the ``--pool`` flag was silently ignored by the
``vscode`` command when the pool name was not present in the cached
nodepool list, so the job landed on the default configured pool instead
of the requested one. ``start`` and ``batch`` already errored loudly /
honored a full resource ID in that case; ``vscode`` now matches them.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from typer.testing import CliRunner

from discovery.poll import cli_submit
from discovery.poll.cli import app
from discovery.poll.models.compute import NodepoolInfo
from discovery.poll.models.config import EnvConfig


runner = CliRunner()

DEFAULT_POOL_ID = "/subscriptions/s/nodepools/default"
TARGET_POOL_ID = "/subscriptions/s/nodepools/poolA"


def _env(tmp_path: Path) -> EnvConfig:
    """Build a ready config whose default pool differs from the target pool."""
    env = EnvConfig(path=tmp_path / ".env")
    env.project_id = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Discovery/projects/demo"
    env.workspace_url = "https://ws.example"
    env.datacontainer_id = "/subscriptions/s/datacontainers/dc"
    env.storagecontainer_id = "/subscriptions/s/storagecontainers/sc"
    env.tool_id = "/subscriptions/s/tools/tool1"
    env.nodepool_id = DEFAULT_POOL_ID
    env.nodepools = [
        NodepoolInfo(id=DEFAULT_POOL_ID, name="default", supercomputer_name="sc1"),
        NodepoolInfo(id=TARGET_POOL_ID, name="PoolA", supercomputer_name="sc1"),
    ]
    return env


def _patch_submit(monkeypatch, env: EnvConfig, recorder: list):
    """Stub everything the vscode command touches around pool resolution."""
    monkeypatch.setattr(cli_submit, "load_project_config", lambda *_a, **_k: env)
    monkeypatch.setattr(cli_submit, "get_config_file_path", lambda: Path("/tmp/ignored"))
    monkeypatch.setattr(cli_submit, "load_tool_config", lambda *_a, **_k: None)
    monkeypatch.setattr(cli_submit, "get_azure_username", lambda: "u")
    monkeypatch.setattr(cli_submit, "ensure_datacontainer", lambda *_a, **_k: None)
    monkeypatch.setattr(cli_submit, "emit_env", lambda *_a, **_k: None)
    monkeypatch.setattr(cli_submit, "prepare_command", lambda *_a, **_k: "sleep 7d")
    monkeypatch.setattr(cli_submit, "_record_job_submission", lambda *_a, **_k: None)
    monkeypatch.setattr(cli_submit, "_poll_for_device_flow_url", lambda *_a, **_k: None)

    def fake_start(project, payload, workspace_url, *, api_version=None, **_k):
        recorder.append(payload)
        return MagicMock(id="op-1")

    monkeypatch.setattr(cli_submit, "start_tool_run", fake_start)


def test_vscode_resolvable_pool_overrides_default(tmp_path, monkeypatch):
    """A resolvable ``--pool`` must set nodePoolIds to that pool, not the default."""
    env = _env(tmp_path)
    submitted: list = []
    _patch_submit(monkeypatch, env, submitted)

    result = runner.invoke(
        app,
        ["job", "vscode", "--username", "u", "--pool", "PoolA",
         "--cpus", "8", "--gpus", "0", "--memory", "32Gi"],
    )

    assert result.exit_code == 0, result.output
    assert len(submitted) == 1
    assert submitted[0].node_pool_ids == [TARGET_POOL_ID]


def test_vscode_unknown_pool_errors_instead_of_silent_default(tmp_path, monkeypatch):
    """An unknown ``--pool`` must fail loudly, not silently use the default pool.

    This is the core ICM 822609036 regression: previously the job was
    submitted to ``DEFAULT_POOL_ID`` and the flag was ignored.
    """
    env = _env(tmp_path)
    submitted: list = []
    _patch_submit(monkeypatch, env, submitted)

    result = runner.invoke(
        app,
        ["job", "vscode", "--username", "u", "--pool", "DoesNotExist",
         "--cpus", "8", "--gpus", "0", "--memory", "32Gi"],
    )

    assert result.exit_code == 1
    assert "not found" in result.output
    # Crucially, no job was submitted to the default pool.
    assert submitted == []


def test_vscode_full_id_pool_used_as_is(tmp_path, monkeypatch):
    """A full resource-ID ``--pool`` not in the cache is used verbatim."""
    env = _env(tmp_path)
    submitted: list = []
    _patch_submit(monkeypatch, env, submitted)
    uncached_id = "/subscriptions/s/nodepools/uncached"

    result = runner.invoke(
        app,
        ["job", "vscode", "--username", "u", "--pool", uncached_id,
         "--cpus", "8", "--gpus", "0", "--memory", "32Gi"],
    )

    assert result.exit_code == 0, result.output
    assert len(submitted) == 1
    assert submitted[0].node_pool_ids == [uncached_id]
