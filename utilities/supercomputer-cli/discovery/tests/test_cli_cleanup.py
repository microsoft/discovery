"""Tests for the cleanup-anf command."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from discovery.poll import cli_cleanup
from discovery.poll.cli import app
from discovery.poll.models.tool_response import (
    AzureCoreOperationState,
    OperationsListResponse,
    OperationsResultModel,
)


runner = CliRunner()


def _make_env_cfg() -> MagicMock:
    """Create a mock EnvConfig with sensible defaults."""
    cfg = MagicMock()
    cfg.project_name = "test-project"
    cfg.workspace_url = "https://example.com"
    cfg.tool_id = "tool-123"
    cfg.nodepool_id = "nodepool-123"
    cfg.datacontainer_id = "dc-123"
    cfg.project_ready = True
    cfg.nodepools = []
    return cfg


def _make_ops_response(
    ops: list[tuple[str, str, datetime]],
    next_link: str | None = None,
) -> OperationsListResponse:
    """Build an OperationsListResponse from (id, status, created_at) tuples."""
    values = []
    for op_id, status, created_at in ops:
        values.append(
            OperationsResultModel.model_validate(
                {
                    "nodepoolId": "np-1",
                    "id": op_id,
                    "status": status,
                    "createdAt": created_at.isoformat(),
                    "completedAt": None,
                    "createdBy": "user@test.com",
                }
            )
        )
    return OperationsListResponse(values=values, nextLink=next_link)


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests for _find_stale_operations
# ─────────────────────────────────────────────────────────────────────────────


class TestFindStaleOperations:
    """Tests for stale operation identification."""

    def test_finds_old_terminal_ops(self):
        now = datetime.now(tz=timezone.utc)
        ops = [
            ("op-1", AzureCoreOperationState.SUCCEEDED, now - timedelta(days=10), "user"),
            ("op-2", AzureCoreOperationState.FAILED, now - timedelta(days=8), "user"),
            ("op-3", AzureCoreOperationState.SUCCEEDED, now - timedelta(days=3), "user"),
        ]
        stale = cli_cleanup._find_stale_operations(ops, age_days=7)
        assert len(stale) == 2
        assert stale[0][0] == "op-1"
        assert stale[1][0] == "op-2"

    def test_skips_active_ops(self):
        now = datetime.now(tz=timezone.utc)
        ops = [
            ("op-1", AzureCoreOperationState.RUNNING, now - timedelta(days=30), "user"),
            ("op-2", AzureCoreOperationState.ACTIVE, now - timedelta(days=30), "user"),
            ("op-3", AzureCoreOperationState.PENDING, now - timedelta(days=30), "user"),
        ]
        stale = cli_cleanup._find_stale_operations(ops, age_days=7)
        assert len(stale) == 0

    def test_skips_recent_ops(self):
        now = datetime.now(tz=timezone.utc)
        ops = [
            ("op-1", AzureCoreOperationState.SUCCEEDED, now - timedelta(days=1), "user"),
        ]
        stale = cli_cleanup._find_stale_operations(ops, age_days=7)
        assert len(stale) == 0

    def test_empty_ops(self):
        stale = cli_cleanup._find_stale_operations([], age_days=7)
        assert stale == []

    def test_custom_age_threshold(self):
        now = datetime.now(tz=timezone.utc)
        ops = [
            ("op-1", AzureCoreOperationState.SUCCEEDED, now - timedelta(days=5), "user"),
            ("op-2", AzureCoreOperationState.SUCCEEDED, now - timedelta(days=3), "user"),
        ]
        stale = cli_cleanup._find_stale_operations(ops, age_days=4)
        assert len(stale) == 1
        assert stale[0][0] == "op-1"

    def test_sorts_oldest_first(self):
        now = datetime.now(tz=timezone.utc)
        ops = [
            ("op-new", AzureCoreOperationState.SUCCEEDED, now - timedelta(days=8), "user"),
            ("op-old", AzureCoreOperationState.SUCCEEDED, now - timedelta(days=20), "user"),
            ("op-mid", AzureCoreOperationState.SUCCEEDED, now - timedelta(days=14), "user"),
        ]
        stale = cli_cleanup._find_stale_operations(ops, age_days=7)
        assert [s[0] for s in stale] == ["op-old", "op-mid", "op-new"]


# ─────────────────────────────────────────────────────────────────────────────
# Unit tests for _collect_all_operations
# ─────────────────────────────────────────────────────────────────────────────


class TestCollectAllOperations:
    """Tests for operation collection with pagination."""

    def test_collects_all_states(self):
        now = datetime.now(tz=timezone.utc)
        ops = _make_ops_response([
            ("op-1", AzureCoreOperationState.RUNNING, now),
            ("op-2", AzureCoreOperationState.SUCCEEDED, now - timedelta(days=10)),
        ])
        with patch.object(cli_cleanup, "list_operations", return_value=ops):
            result = cli_cleanup._collect_all_operations("proj", "https://example.com")
        assert len(result) == 2

    def test_follows_pagination(self):
        now = datetime.now(tz=timezone.utc)
        page1 = _make_ops_response(
            [("op-1", AzureCoreOperationState.RUNNING, now)],
            next_link="https://example.com/next",
        )
        page2 = _make_ops_response(
            [("op-2", AzureCoreOperationState.SUCCEEDED, now - timedelta(days=10))],
        )

        with (
            patch.object(cli_cleanup, "list_operations", return_value=page1),
            patch.object(cli_cleanup, "list_operations_page", return_value=page2),
        ):
            result = cli_cleanup._collect_all_operations("proj", "https://example.com")
        assert len(result) == 2

    def test_empty_operations(self):
        ops = _make_ops_response([])
        with patch.object(cli_cleanup, "list_operations", return_value=ops):
            result = cli_cleanup._collect_all_operations("proj", "https://example.com")
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests for the CLI command
# ─────────────────────────────────────────────────────────────────────────────


class TestCleanupAnfCommand:
    """Tests for the cleanup-anf CLI command."""

    def test_help(self):
        result = runner.invoke(app, ["job", "cleanup-anf", "--help"])
        assert result.exit_code == 0
        assert "age-days" in result.output

    def test_no_stale_operations(self):
        """All ops are recent or active -> nothing to report."""
        cfg = _make_env_cfg()
        now = datetime.now(tz=timezone.utc)

        ops = _make_ops_response([
            ("op-1", AzureCoreOperationState.RUNNING, now),
            ("op-2", AzureCoreOperationState.SUCCEEDED, now - timedelta(hours=1)),
        ])

        with (
            patch.object(cli_cleanup, "load_project_config", return_value=cfg),
            patch.object(cli_cleanup, "emit_env"),
            patch.object(cli_cleanup, "list_operations", return_value=ops),
        ):
            result = runner.invoke(app, ["job", "cleanup-anf"])

        assert result.exit_code == 0
        assert "No stale operations" in result.output

    def test_shows_stale_operations(self):
        """Old completed ops are listed in the table."""
        cfg = _make_env_cfg()
        now = datetime.now(tz=timezone.utc)

        ops = _make_ops_response([
            ("op-active", AzureCoreOperationState.RUNNING, now),
            ("op-stale1", AzureCoreOperationState.SUCCEEDED, now - timedelta(days=14)),
            ("op-stale2", AzureCoreOperationState.FAILED, now - timedelta(days=10)),
            ("op-recent", AzureCoreOperationState.SUCCEEDED, now - timedelta(days=3)),
        ])

        with (
            patch.object(cli_cleanup, "load_project_config", return_value=cfg),
            patch.object(cli_cleanup, "emit_env"),
            patch.object(cli_cleanup, "list_operations", return_value=ops),
        ):
            result = runner.invoke(app, ["job", "cleanup-anf"])

        assert result.exit_code == 0
        assert "op-stale1" in result.output
        assert "op-stale2" in result.output
        assert "op-active" not in result.output
        assert "op-recent" not in result.output

    def test_custom_age_days(self):
        """Custom --age-days filters correctly."""
        cfg = _make_env_cfg()
        now = datetime.now(tz=timezone.utc)

        ops = _make_ops_response([
            ("op-3day", AzureCoreOperationState.SUCCEEDED, now - timedelta(days=3)),
            ("op-5day", AzureCoreOperationState.SUCCEEDED, now - timedelta(days=5)),
        ])

        with (
            patch.object(cli_cleanup, "load_project_config", return_value=cfg),
            patch.object(cli_cleanup, "emit_env"),
            patch.object(cli_cleanup, "list_operations", return_value=ops),
        ):
            result = runner.invoke(app, ["job", "cleanup-anf", "--age-days", "4"])

        assert result.exit_code == 0
        assert "op-5day" in result.output
        assert "op-3day" not in result.output

    def test_empty_operations(self):
        """No operations at all -> clean exit."""
        cfg = _make_env_cfg()
        ops = _make_ops_response([])

        with (
            patch.object(cli_cleanup, "load_project_config", return_value=cfg),
            patch.object(cli_cleanup, "emit_env"),
            patch.object(cli_cleanup, "list_operations", return_value=ops),
        ):
            result = runner.invoke(app, ["job", "cleanup-anf"])

        assert result.exit_code == 0
        assert "No stale operations" in result.output


__all__ = [
    "TestCleanupAnfCommand",
    "TestCollectAllOperations",
    "TestFindStaleOperations",
]
