"""Tests for ``discovery job history`` and ``--mine`` filter integration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from discovery.common import job_history
from discovery.poll import cli_submit
from discovery.poll.cli import app
from discovery.poll.models.tool_response import AzureCoreOperationState


runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_history(workspace: str = "https://ws.example") -> None:
    job_history.record_submission(
        "op-1",
        command="echo first",
        workspace_url=workspace,
        project_name="proj-1",
        mode="start",
        submitted_at="2026-05-31T10:00:00Z",
        hostname="laptop-a",
    )
    job_history.record_submission(
        "op-2",
        command="echo second",
        workspace_url=workspace,
        project_name="proj-1",
        mode="batch",
        submitted_at="2026-06-01T10:00:00Z",
        hostname="laptop-a",
    )
    job_history.record_submission(
        "op-3",
        command="echo third",
        workspace_url="https://other.example",
        project_name="proj-1",
        mode="start",
        submitted_at="2026-06-01T11:00:00Z",
        hostname="laptop-a",
    )


# ---------------------------------------------------------------------------
# `discovery job history`
# ---------------------------------------------------------------------------


class TestHistoryCommand:
    def test_path_prints_location(self) -> None:
        result = runner.invoke(app, ["job", "history", "--path"])
        assert result.exit_code == 0
        # The autouse conftest fixture isolates the home dir, so the
        # printed path should be under it.
        assert "job-history.jsonl" in result.stdout

    def test_empty_history_prints_friendly_message(self) -> None:
        result = runner.invoke(
            app, ["job", "history", "--all-workspaces"]
        )
        assert result.exit_code == 0
        assert "No local job-history entries" in result.stdout

    def test_lists_entries_newest_first(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_history()
        # --all-workspaces avoids triggering load_project_config (which
        # needs a real config file).
        result = runner.invoke(
            app, ["job", "history", "--all-workspaces"]
        )
        assert result.exit_code == 0
        # All three op IDs visible
        for op in ("op-1", "op-2", "op-3"):
            assert op in result.stdout
        # Newest first: op-3 should appear before op-1
        assert result.stdout.index("op-3") < result.stdout.index("op-1")

    def test_limit_truncates_results(self) -> None:
        _seed_history()
        result = runner.invoke(
            app,
            ["job", "history", "--all-workspaces", "--limit", "1"],
        )
        assert result.exit_code == 0
        # Only the newest entry (op-3) should be in the table.
        assert "op-3" in result.stdout
        assert "op-1" not in result.stdout
        assert "op-2" not in result.stdout

    def test_since_filter_shorthand(self) -> None:
        _seed_history()
        # 30d back from now (2026) is still well after May 2026 entries,
        # so '30000d' is a safer "include everything" sentinel.
        # We instead verify the filter works by using a future cutoff
        # that excludes everything.
        far_future = (datetime.now(tz=timezone.utc) + timedelta(days=1)).strftime(
            "%Y-%m-%d"
        )
        result = runner.invoke(
            app,
            ["job", "history", "--all-workspaces", "--since", far_future],
        )
        assert result.exit_code == 0
        assert "No local job-history entries" in result.stdout

    def test_workspace_scoping_is_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_history()
        fake_cfg = MagicMock()
        fake_cfg.workspace_url = "https://ws.example"
        monkeypatch.setattr(
            "discovery.poll.cli_history.load_project_config",
            lambda *_a, **_k: fake_cfg,
        )
        monkeypatch.setattr(
            "discovery.poll.cli_history.get_config_file_path",
            lambda: Path("/tmp/ignored"),
        )
        result = runner.invoke(app, ["job", "history"])
        assert result.exit_code == 0
        assert "op-1" in result.stdout
        assert "op-2" in result.stdout
        # op-3 is on a different workspace — filtered out by default.
        assert "op-3" not in result.stdout

    def test_clear_requires_confirmation(self) -> None:
        _seed_history()
        # Decline confirmation; file should be untouched.
        result = runner.invoke(app, ["job", "history", "--clear"], input="n\n")
        assert result.exit_code == 0
        entries = job_history.load_history()
        assert len(entries) == 3

    def test_clear_with_confirmation_wipes_file(self) -> None:
        _seed_history()
        result = runner.invoke(app, ["job", "history", "--clear"], input="y\n")
        assert result.exit_code == 0
        assert not job_history.history_path().exists()


# ---------------------------------------------------------------------------
# --mine filter on `discovery job list`
# ---------------------------------------------------------------------------


class TestMineFilter:
    def test_mine_exits_friendly_when_history_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_cfg = MagicMock()
        fake_cfg.workspace_url = "https://ws.example"
        monkeypatch.setattr(
            "discovery.poll.cli_status.load_project_config",
            lambda *_a, **_k: fake_cfg,
        )
        monkeypatch.setattr(
            "discovery.poll.cli_status.get_config_file_path",
            lambda: Path("/tmp/ignored"),
        )
        monkeypatch.setattr(
            "discovery.poll.cli_status.emit_env", lambda *_a, **_k: None
        )
        result = runner.invoke(app, ["job", "running", "--mine"])
        assert result.exit_code == 0
        assert "No locally-recorded jobs" in result.stdout

    def test_list_mine_invokes_paginator_with_mine_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Seed history for the configured workspace.
        _seed_history(workspace="https://ws.example")
        fake_cfg = MagicMock()
        fake_cfg.workspace_url = "https://ws.example"
        fake_cfg.nodepools = []
        monkeypatch.setattr(
            "discovery.poll.cli_status.load_project_config",
            lambda *_a, **_k: fake_cfg,
        )
        monkeypatch.setattr(
            "discovery.poll.cli_status.get_config_file_path",
            lambda: Path("/tmp/ignored"),
        )
        monkeypatch.setattr(
            "discovery.poll.cli_status.emit_env", lambda *_a, **_k: None
        )

        captured = {}

        async def fake_paginated(*, env_cfg, filter_fn, limit=0, page_size=0):
            captured["filter_fn"] = filter_fn

        monkeypatch.setattr(
            "discovery.poll.cli_status._paginated_list", fake_paginated
        )
        result = runner.invoke(app, ["job", "list", "--mine"])
        assert result.exit_code == 0

        fn = captured["filter_fn"]
        # op-1 and op-2 are in history; op-3 (other workspace) is not.
        op_known = MagicMock(
            id="op-1",
            created_by="someone",
            nodepool_id="x",
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        op_unknown = MagicMock(
            id="op-3",
            created_by="someone",
            nodepool_id="x",
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        assert fn(op_known) is True
        assert fn(op_unknown) is False

    def test_running_mine_invokes_paginator_with_mine_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_history(workspace="https://ws.example")
        fake_cfg = MagicMock()
        fake_cfg.workspace_url = "https://ws.example"
        monkeypatch.setattr(
            "discovery.poll.cli_status.load_project_config",
            lambda *_a, **_k: fake_cfg,
        )
        monkeypatch.setattr(
            "discovery.poll.cli_status.get_config_file_path",
            lambda: Path("/tmp/ignored"),
        )
        monkeypatch.setattr(
            "discovery.poll.cli_status.emit_env", lambda *_a, **_k: None
        )

        captured = {}

        async def fake_paginated(*, env_cfg, filter_fn, limit=0, page_size=0):
            captured["filter_fn"] = filter_fn

        monkeypatch.setattr(
            "discovery.poll.cli_status._paginated_list", fake_paginated
        )
        # ``--all`` disables the per-user filter so the only thing the
        # filter_fn ends up applying is the mine_ids set we care about.
        result = runner.invoke(app, ["job", "running", "--mine", "--all"])
        assert result.exit_code == 0

        fn = captured["filter_fn"]
        op = MagicMock(
            id="op-1",
            created_by="me",
            status=AzureCoreOperationState.RUNNING,
        )
        assert fn(op) is True
        op_other = MagicMock(
            id="not-in-history",
            created_by="me",
            status=AzureCoreOperationState.RUNNING,
        )
        assert fn(op_other) is False


# ---------------------------------------------------------------------------
# Submit-site integration
# ---------------------------------------------------------------------------


class TestRecorderIntegration:
    """Verify the recorder helper writes a usable record on a fake submit."""

    def test_record_job_submission_writes_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_cfg = MagicMock()
        env_cfg.tool_id = "tool/xyz"
        env_cfg.project_name = "demo"
        env_cfg.workspace_url = "https://ws.example"

        monkeypatch.setattr(
            "discovery.poll.cli_submit.sys.argv",
            ["discovery", "job", "start", "echo hi"],
        )
        cli_submit._record_job_submission(
            "fresh-op-id",
            env_cfg,
            command="echo hi",
            nodepool_id="np/123",
            mode=job_history.MODE_START,
        )
        entries = job_history.load_history()
        assert len(entries) == 1
        e = entries[0]
        assert e.operation_id == "fresh-op-id"
        assert e.command == "echo hi"
        assert e.tool_id == "tool/xyz"
        assert e.project_name == "demo"
        assert e.workspace_url == "https://ws.example"
        assert e.nodepool_id == "np/123"
        assert e.mode == job_history.MODE_START
        assert e.cli_argv == ["discovery", "job", "start", "echo hi"]

    def test_record_swallows_exceptions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A crashing record_submission must not propagate."""
        def boom(*_a, **_kw):
            msg = "boom"
            raise RuntimeError(msg)

        monkeypatch.setattr(
            "discovery.poll.cli_submit.record_submission", boom
        )
        cli_submit._record_job_submission(
            "op-x",
            MagicMock(tool_id="t", project_name="p", workspace_url="w"),
            command="x",
            nodepool_id="np",
            mode=job_history.MODE_START,
        )
        # If we got here, no exception escaped.
