"""Tests for the `discovery job debug` command."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from discovery.poll.cli_debug import app


def _env_cfg() -> MagicMock:
    cfg = MagicMock()
    cfg.project_name = "proj"
    cfg.workspace_url = "https://ws"
    return cfg


@pytest.fixture
def _stub_env():
    with (
        patch("discovery.poll.cli_debug.load_project_config", return_value=_env_cfg()),
        patch("discovery.poll.cli_debug.get_config_file_path"),
        patch("discovery.poll.cli_debug.emit_env"),
    ):
        yield


@pytest.mark.usefixtures("_stub_env")
def test_debug_banner_prefers_tunnel_name() -> None:
    with patch("discovery.poll.cli_debug.connect_debug_container") as mock_connect:
        mock_connect.return_value = {
            "tunnelId": "debug-abc",
            "tunnelName": "friendly-debug-name",
            "debugSessionId": "sess-1",
            "status": "Creating",
        }

        runner = CliRunner()
        result = runner.invoke(app, ["op-123"])

    assert result.exit_code == 0, result.output
    assert "friendly-debug-name" in result.output
    # The VS Code instruction line should point at the friendly name, not the id
    assert 'Find "friendly-debug-name"' in result.output


@pytest.mark.usefixtures("_stub_env")
def test_debug_banner_falls_back_to_tunnel_id_when_name_missing() -> None:
    captured: dict[str, Any] = {}

    with patch("discovery.poll.cli_debug.connect_debug_container") as mock_connect:
        mock_connect.return_value = {
            "tunnelId": "debug-xyz",
            # no tunnelName (older server)
            "debugSessionId": "sess-2",
            "status": "Creating",
        }

        runner = CliRunner()
        result = runner.invoke(app, ["op-123", "--pod", "2"])
        captured["kwargs"] = mock_connect.call_args.kwargs

    assert result.exit_code == 0, result.output
    assert 'Find "debug-xyz"' in result.output
    assert "Pod index:    2" in result.output
    assert captured["kwargs"]["pod_index"] == 2
