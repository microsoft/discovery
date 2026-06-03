"""Tests for ``discovery job history`` and ``--mine`` filter integration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from rich.console import Console as _RichConsole
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
# `discovery job history --status`
# ---------------------------------------------------------------------------


class TestHistoryStatusFlag:
    """``--status`` enriches the table with live status + runtime."""

    @pytest.fixture(autouse=True)
    def _wide_console(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Force a wide console so Rich doesn't truncate the table.

        Without this, ``CliRunner``'s captured stdout reports an 80-col
        terminal and Rich wraps / hides cells we want to assert on.
        """
        monkeypatch.setattr(
            "discovery.poll.cli_history.console",
            _RichConsole(width=200, highlight=False, soft_wrap=False),
        )

    def _setup_env(self, monkeypatch: pytest.MonkeyPatch, workspace: str) -> None:
        fake_cfg = MagicMock()
        fake_cfg.workspace_url = workspace
        fake_cfg.project_name = "demo"
        fake_cfg.api_version = "x"
        monkeypatch.setattr(
            "discovery.poll.cli_history.load_project_config",
            lambda *_a, **_k: fake_cfg,
        )
        monkeypatch.setattr(
            "discovery.poll.cli_history.get_config_file_path",
            lambda: Path("/tmp/ignored"),
        )

    def _fake_get_status(self, mapping: dict):
        """Build a fake get_operation_status that returns a stubbed response
        per op-id from ``mapping`` (id -> (status, created_at, completed_at))."""
        def _fn(project, op_id, workspace, *, api_version):
            entry = mapping.get(op_id)
            if entry is None:
                # Simulate 404 with a real httpx.Response so the
                # status_code attribute access goes through httpx's own
                # logic rather than MagicMock's attribute autocreation.
                req = httpx.Request("GET", "https://example/op")
                resp = httpx.Response(404, request=req)
                msg = "not found"
                raise httpx.HTTPStatusError(
                    msg, request=req, response=resp
                )
            status, created_at, completed_at = entry
            r = MagicMock()
            r.status = status
            r.result = MagicMock()
            r.result.created_at = created_at
            r.result.completed_at = completed_at
            return r
        return _fn

    def test_status_renders_runtime_for_completed_op(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = "https://ws.example"
        _seed_history(workspace=ws)
        self._setup_env(monkeypatch, ws)

        created = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        completed = created + timedelta(minutes=42, seconds=15)
        monkeypatch.setattr(
            "discovery.poll.cli_history.get_operation_status",
            self._fake_get_status({
                "op-1": ("Succeeded", created, completed),
                "op-2": ("Succeeded", created, completed),
            }),
        )

        result = runner.invoke(
            app, ["job", "history", "--status"]
        )
        assert result.exit_code == 0
        # Both rows must appear with a status + runtime cell.
        assert "Succeeded" in result.stdout
        # Runtime should render as "42m 15s" (two most-significant units).
        assert "42m 15s" in result.stdout

    def test_status_handles_running_ops(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = "https://ws.example"
        job_history.record_submission(
            "op-running",
            workspace_url=ws,
            project_name="demo",
            command="long job",
            submitted_at="2026-06-01T11:00:00Z",
        )
        self._setup_env(monkeypatch, ws)

        # In-progress: created_at set, completed_at None.
        created = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
        monkeypatch.setattr(
            "discovery.poll.cli_history.get_operation_status",
            self._fake_get_status({
                "op-running": ("Running", created, None),
            }),
        )

        result = runner.invoke(app, ["job", "history", "--status"])
        assert result.exit_code == 0
        assert "Running" in result.stdout
        # In-progress runtime ends with the "+" suffix.
        assert "+" in result.stdout

    def test_status_handles_404_as_expired(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = "https://ws.example"
        job_history.record_submission(
            "op-gone",
            workspace_url=ws,
            project_name="demo",
            submitted_at="2026-01-01T00:00:00Z",
        )
        self._setup_env(monkeypatch, ws)
        # Empty mapping → every lookup hits the simulated 404 path.
        monkeypatch.setattr(
            "discovery.poll.cli_history.get_operation_status",
            self._fake_get_status({}),
        )

        result = runner.invoke(app, ["job", "history", "--status"])
        assert result.exit_code == 0
        assert "expired" in result.stdout

    def test_status_handles_network_errors_gracefully(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = "https://ws.example"
        job_history.record_submission(
            "op-offline",
            workspace_url=ws,
            project_name="demo",
            submitted_at="2026-06-01T11:00:00Z",
        )
        self._setup_env(monkeypatch, ws)

        def boom(*_a, **_kw):
            msg = "no network"
            raise httpx.ConnectError(msg)

        monkeypatch.setattr(
            "discovery.poll.cli_history.get_operation_status", boom
        )
        result = runner.invoke(app, ["job", "history", "--status"])
        # Network errors do NOT fail the command — they just mark the row.
        assert result.exit_code == 0
        # The status column shows "?" when we can't reach the API.
        assert "?" in result.stdout

    def test_status_default_off_keeps_offline_behavior(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without --status the command must not hit the API at all."""
        ws = "https://ws.example"
        _seed_history(workspace=ws)
        self._setup_env(monkeypatch, ws)
        called = []

        def fail(*_a, **_kw):
            called.append(_a)
            msg = "get_operation_status must not be called"
            raise AssertionError(msg)

        monkeypatch.setattr(
            "discovery.poll.cli_history.get_operation_status", fail
        )
        result = runner.invoke(app, ["job", "history"])
        assert result.exit_code == 0
        assert called == []


# ---------------------------------------------------------------------------
# --mine filter on `discovery job list`
# ---------------------------------------------------------------------------


class TestDefaultMineBehavior:
    """`discovery job list / running / pending / done` should default to
    showing only this machine's locally-recorded jobs, and `--all`
    should opt out of that filter."""

    def test_running_default_hints_when_history_empty(
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
        result = runner.invoke(app, ["job", "running"])
        assert result.exit_code == 0
        assert "No locally-recorded jobs" in result.stdout
        assert "--all" in result.stdout

    def test_list_default_filters_to_local_history(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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

        async def fake_paginated(*, env_cfg, filter_fn, limit=0, page_size=0, target_ids=None, not_before=None):
            captured["filter_fn"] = filter_fn

        monkeypatch.setattr(
            "discovery.poll.cli_status._paginated_list", fake_paginated
        )
        # No --all => default to local history.
        result = runner.invoke(app, ["job", "list"])
        assert result.exit_code == 0

        fn = captured["filter_fn"]
        op_in_history = MagicMock(
            id="op-1",
            created_by="someone",
            nodepool_id="x",
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        op_outside_history = MagicMock(
            id="op-99",
            created_by="someone",
            nodepool_id="x",
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        assert fn(op_in_history) is True
        assert fn(op_outside_history) is False

    def test_list_all_skips_local_history_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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

        async def fake_paginated(*, env_cfg, filter_fn, limit=0, page_size=0, target_ids=None, not_before=None):
            captured["filter_fn"] = filter_fn

        monkeypatch.setattr(
            "discovery.poll.cli_status._paginated_list", fake_paginated
        )
        result = runner.invoke(app, ["job", "list", "--all"])
        assert result.exit_code == 0

        fn = captured["filter_fn"]
        # Both ops match — local-history filter is disabled.
        op_in = MagicMock(
            id="op-1",
            created_by="x",
            nodepool_id="x",
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        op_out = MagicMock(
            id="op-99",
            created_by="x",
            nodepool_id="x",
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        assert fn(op_in) is True
        assert fn(op_out) is True

    def test_list_user_flag_implies_all(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``--user X`` is a cross-user query, so the local-history
        default should be skipped automatically."""
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

        async def fake_paginated(*, env_cfg, filter_fn, limit=0, page_size=0, target_ids=None, not_before=None):
            captured["filter_fn"] = filter_fn

        monkeypatch.setattr(
            "discovery.poll.cli_status._paginated_list", fake_paginated
        )
        result = runner.invoke(app, ["job", "list", "--user", "someone"])
        assert result.exit_code == 0

        fn = captured["filter_fn"]
        # op-99 is NOT in local history, but --user implies --all so the
        # only effective filter is created_by="someone".
        op_match = MagicMock(
            id="op-99",
            created_by="someone",
            nodepool_id="x",
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        op_no_match = MagicMock(
            id="op-99",
            created_by="other",
            nodepool_id="x",
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        assert fn(op_match) is True
        assert fn(op_no_match) is False

    def test_running_default_filters_to_local_history(
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

        async def fake_paginated(*, env_cfg, filter_fn, limit=0, page_size=0, target_ids=None, not_before=None):
            captured["filter_fn"] = filter_fn

        monkeypatch.setattr(
            "discovery.poll.cli_status._paginated_list", fake_paginated
        )
        # No --all => default to local history (no Azure-user filter).
        result = runner.invoke(app, ["job", "running"])
        assert result.exit_code == 0

        fn = captured["filter_fn"]
        op = MagicMock(
            id="op-1",
            created_by="someone-else",  # not the current Azure user
            status=AzureCoreOperationState.RUNNING,
        )
        # Should match — default no longer filters by Azure user, only
        # by local history.
        assert fn(op) is True
        op_other = MagicMock(
            id="not-in-history",
            created_by="someone-else",
            status=AzureCoreOperationState.RUNNING,
        )
        assert fn(op_other) is False

    def test_running_all_includes_other_machines_jobs(
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

        async def fake_paginated(*, env_cfg, filter_fn, limit=0, page_size=0, target_ids=None, not_before=None):
            captured["filter_fn"] = filter_fn

        monkeypatch.setattr(
            "discovery.poll.cli_status._paginated_list", fake_paginated
        )
        result = runner.invoke(app, ["job", "running", "--all"])
        assert result.exit_code == 0

        fn = captured["filter_fn"]
        op_local = MagicMock(
            id="op-1",
            status=AzureCoreOperationState.RUNNING,
        )
        op_remote = MagicMock(
            id="not-in-history",
            status=AzureCoreOperationState.RUNNING,
        )
        assert fn(op_local) is True
        assert fn(op_remote) is True


# ---------------------------------------------------------------------------
# Submit-site integration
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Paginator early-exit (target_ids + not_before)
# ---------------------------------------------------------------------------


class TestPaginatorEarlyExit:
    """When the local-history filter is in effect the paginator should
    stop pulling pages as soon as it has matched every locally-known
    ID, and also stop when it scans past the oldest known submission."""

    def _make_op(self, op_id: str, *, age_seconds: int = 0):
        """Build a minimal OperationsResultModel-shaped mock."""
        op = MagicMock()
        op.id = op_id
        op.created_at = datetime.now(tz=timezone.utc) - timedelta(seconds=age_seconds)
        op.completed_at = None
        op.created_by = "someone"
        op.nodepool_id = "x"
        op.status = "Running"
        return op

    def _make_page(self, ops, next_link=None):
        page = MagicMock()
        page.values = ops
        page.next_link = next_link
        return page

    def test_stops_after_matching_all_target_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two ops on the first page match the local-history set; no
        further API pages should be fetched even though next_link is
        present."""
        _seed_history(workspace="https://ws.example")

        fake_cfg = MagicMock()
        fake_cfg.workspace_url = "https://ws.example"
        fake_cfg.project_name = "demo"
        fake_cfg.api_version = "x"
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
        # Force the display batch size to be large enough that fill-up
        # isn't the reason for the stop.
        monkeypatch.setattr(
            "discovery.poll.cli_status.shutil.get_terminal_size",
            lambda: MagicMock(lines=100),
        )

        first_page = self._make_page(
            [
                self._make_op("op-1"),
                self._make_op("op-2"),
                self._make_op("op-other"),
            ],
            next_link="https://api.example/next",
        )

        list_calls: list = []
        page_calls: list = []

        def fake_list_operations(*a, **kw):
            list_calls.append((a, kw))
            return first_page

        def fake_list_operations_page(link):
            page_calls.append(link)
            return self._make_page(
                [self._make_op("op-also-not-mine")], next_link=None
            )

        monkeypatch.setattr(
            "discovery.poll.cli_status.list_operations",
            fake_list_operations,
        )
        monkeypatch.setattr(
            "discovery.poll.cli_status.list_operations_page",
            fake_list_operations_page,
        )

        result = runner.invoke(app, ["job", "list"])
        assert result.exit_code == 0
        # Both seeded mine-IDs in the workspace are on the first page,
        # so list_operations_page should NEVER have been called.
        assert len(list_calls) == 1
        assert page_calls == [], (
            f"Expected no follow-up pages but got {page_calls!r}"
        )

    def test_stops_when_op_predates_oldest_mine_submission(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The single mine-id isn't on the first page, but the page
        crosses into ops older than our oldest local submission;
        the paginator should stop without fetching more."""
        # History: a single recent submission; the cutoff will be ~1h
        # before this timestamp.
        job_history.record_submission(
            "needle-op",
            workspace_url="https://ws.example",
            project_name="proj-1",
            submitted_at=(
                datetime.now(tz=timezone.utc) - timedelta(seconds=30)
            ).isoformat().replace("+00:00", "Z"),
        )

        fake_cfg = MagicMock()
        fake_cfg.workspace_url = "https://ws.example"
        fake_cfg.project_name = "demo"
        fake_cfg.api_version = "x"
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
        monkeypatch.setattr(
            "discovery.poll.cli_status.shutil.get_terminal_size",
            lambda: MagicMock(lines=100),
        )

        # First page: 3 ops, all far older (~2 days) than the local
        # submission cutoff. None match by ID either.
        old_ops = [
            self._make_op(f"unrelated-{i}", age_seconds=2 * 86400)
            for i in range(3)
        ]
        first_page = self._make_page(old_ops, next_link="https://api.example/next")

        list_calls: list = []
        page_calls: list = []

        def fake_list_operations(*a, **kw):
            list_calls.append((a, kw))
            return first_page

        def fake_list_operations_page(link):
            page_calls.append(link)
            return self._make_page([], next_link=None)

        monkeypatch.setattr(
            "discovery.poll.cli_status.list_operations",
            fake_list_operations,
        )
        monkeypatch.setattr(
            "discovery.poll.cli_status.list_operations_page",
            fake_list_operations_page,
        )

        result = runner.invoke(app, ["job", "list"])
        assert result.exit_code == 0
        # First op already predates the cutoff (~1h ago, ops are ~2d old),
        # so the not_before guard should fire on op #1 — no follow-up
        # pages and only one op actually scanned.
        assert len(list_calls) == 1
        assert page_calls == []


# ---------------------------------------------------------------------------
# `discovery job cancel --since`
# ---------------------------------------------------------------------------


class TestCancelSince:
    """Bulk-cancel mode: ``discovery job cancel --since DURATION``."""

    def _patch_cancel(self, monkeypatch: pytest.MonkeyPatch):
        """Install a no-op cancel_operation that records the IDs it was called with."""
        called: list[str] = []

        def fake_cancel(project, op_id, workspace_url, *, api_version):
            called.append(op_id)

        monkeypatch.setattr(
            "discovery.poll.cli_submit.cancel_operation", fake_cancel
        )
        return called

    def _setup_env(self, monkeypatch: pytest.MonkeyPatch, workspace: str, *, az_user: str = "alice@example.com"):
        fake_cfg = MagicMock()
        fake_cfg.workspace_url = workspace
        fake_cfg.project_name = "demo"
        fake_cfg.api_version = "x"
        fake_cfg.nodepools = []
        monkeypatch.setattr(
            "discovery.poll.cli_submit.load_project_config",
            lambda *_a, **_k: fake_cfg,
        )
        monkeypatch.setattr(
            "discovery.poll.cli_submit.get_config_file_path",
            lambda: Path("/tmp/ignored"),
        )
        monkeypatch.setattr(
            "discovery.poll.cli_submit.emit_env", lambda *_a, **_k: None
        )
        # The cancel path looks up the current Azure principal to scope
        # the filter to "this user only". Tests must stub this to keep
        # the behavior deterministic.
        monkeypatch.setattr(
            "discovery.poll.cli_submit.get_raw_azure_username",
            lambda: az_user,
        )

    def test_requires_either_op_id_or_since(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._setup_env(monkeypatch, "https://ws.example")
        result = runner.invoke(app, ["job", "cancel"])
        assert result.exit_code == 2

    def test_op_id_and_since_are_mutually_exclusive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._setup_env(monkeypatch, "https://ws.example")
        result = runner.invoke(
            app, ["job", "cancel", "op-abc", "--since", "10m"]
        )
        assert result.exit_code == 2

    def test_no_matches_exits_zero_with_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # History exists, but cutoff makes nothing match.
        _seed_history(workspace="https://ws.example")
        self._setup_env(monkeypatch, "https://ws.example")
        called = self._patch_cancel(monkeypatch)

        result = runner.invoke(
            app, ["job", "cancel", "--since", "1s", "--yes"]
        )
        assert result.exit_code == 0
        assert "No locally-recorded jobs" in result.stdout
        assert called == []

    def test_cancels_only_recent_local_history(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = "https://ws.example"
        # Two recent (within 5m) submissions, one old (an hour ago),
        # and one from a different workspace. All belong to the same
        # current Azure user.
        now = datetime.now(tz=timezone.utc)
        recent_iso = (
            (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        )
        old_iso = (
            (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        )
        job_history.record_submission(
            "op-recent-1",
            workspace_url=ws,
            project_name="demo",
            submitted_at=recent_iso,
            command="recent 1",
            azure_username="alice@example.com",
        )
        job_history.record_submission(
            "op-recent-2",
            workspace_url=ws,
            project_name="demo",
            submitted_at=recent_iso,
            command="recent 2",
            azure_username="alice@example.com",
        )
        job_history.record_submission(
            "op-old",
            workspace_url=ws,
            project_name="demo",
            submitted_at=old_iso,
            command="too old",
            azure_username="alice@example.com",
        )
        job_history.record_submission(
            "op-other-ws",
            workspace_url="https://other.example",
            project_name="demo",
            submitted_at=recent_iso,
            command="other workspace",
            azure_username="alice@example.com",
        )

        self._setup_env(monkeypatch, ws, az_user="alice@example.com")
        called = self._patch_cancel(monkeypatch)

        result = runner.invoke(
            app,
            ["job", "cancel", "--since", "10m", "--yes"],
        )
        assert result.exit_code == 0
        assert sorted(called) == ["op-recent-1", "op-recent-2"]

    def test_skips_jobs_from_other_azure_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Shared $HOME, different az logins: cancel must skip any
        entry recorded under a different Azure principal."""
        ws = "https://ws.example"
        now = datetime.now(tz=timezone.utc)
        recent = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")

        # alice's recent job
        job_history.record_submission(
            "op-alice",
            workspace_url=ws,
            project_name="demo",
            submitted_at=recent,
            command="alice's job",
            azure_username="alice@example.com",
        )
        # bob's recent job, also recorded into this shared history file
        job_history.record_submission(
            "op-bob",
            workspace_url=ws,
            project_name="demo",
            submitted_at=recent,
            command="bob's job",
            azure_username="bob@example.com",
        )

        # We're currently signed in as alice — bob's op must not be touched.
        self._setup_env(monkeypatch, ws, az_user="alice@example.com")
        called = self._patch_cancel(monkeypatch)

        result = runner.invoke(
            app, ["job", "cancel", "--since", "10m", "--yes"]
        )
        assert result.exit_code == 0
        assert called == ["op-alice"]
        assert "Skipping 1 entry" in result.stdout
        assert "bob@example.com" not in result.stdout  # we don't leak other users' identities

    def test_includes_legacy_entries_with_no_azure_username(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Entries written before the azure_username field existed
        should still be eligible — we have no way to verify them so we
        treat them as 'whoever owns this HOME'."""
        ws = "https://ws.example"
        now = datetime.now(tz=timezone.utc)
        recent = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")

        # Hand-written entry mimicking a pre-azure-username record:
        # empty azure_username field.
        job_history.record_submission(
            "op-legacy",
            workspace_url=ws,
            project_name="demo",
            submitted_at=recent,
            command="legacy entry",
            azure_username="",
        )

        self._setup_env(monkeypatch, ws, az_user="alice@example.com")
        called = self._patch_cancel(monkeypatch)

        result = runner.invoke(
            app, ["job", "cancel", "--since", "10m", "--yes"]
        )
        assert result.exit_code == 0
        assert called == ["op-legacy"]

    def test_falls_back_when_az_lookup_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If we can't determine the current Azure user, degrade to
        the previous behavior (cancel everything) rather than refusing
        to do anything."""
        ws = "https://ws.example"
        now = datetime.now(tz=timezone.utc)
        recent = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        job_history.record_submission(
            "op-alice",
            workspace_url=ws,
            project_name="demo",
            submitted_at=recent,
            azure_username="alice@example.com",
        )
        job_history.record_submission(
            "op-bob",
            workspace_url=ws,
            project_name="demo",
            submitted_at=recent,
            azure_username="bob@example.com",
        )

        self._setup_env(monkeypatch, ws)
        # Override the stub from _setup_env to simulate a failed az lookup.
        def boom():
            msg = "az missing"
            raise RuntimeError(msg)

        monkeypatch.setattr(
            "discovery.poll.cli_submit.get_raw_azure_username", boom
        )
        called = self._patch_cancel(monkeypatch)

        result = runner.invoke(
            app, ["job", "cancel", "--since", "10m", "--yes"]
        )
        assert result.exit_code == 0
        # No filter possible → both ops cancelled (previous behavior).
        assert sorted(called) == ["op-alice", "op-bob"]

    def test_decline_confirmation_aborts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = "https://ws.example"
        now = datetime.now(tz=timezone.utc)
        job_history.record_submission(
            "op-recent",
            workspace_url=ws,
            project_name="demo",
            submitted_at=(now - timedelta(minutes=2))
            .isoformat()
            .replace("+00:00", "Z"),
        )
        self._setup_env(monkeypatch, ws)
        called = self._patch_cancel(monkeypatch)

        # Pipe 'n' to the confirm prompt.
        result = runner.invoke(
            app, ["job", "cancel", "--since", "10m"], input="n\n"
        )
        assert result.exit_code == 0
        assert "aborted" in result.stdout.lower()
        assert called == []

    def test_treats_404_as_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the op is already in a terminal state the service returns
        404/409 — the user's goal ("make it stop") is already true, so
        don't fail the command."""
        ws = "https://ws.example"
        now = datetime.now(tz=timezone.utc)
        job_history.record_submission(
            "op-already-done",
            workspace_url=ws,
            project_name="demo",
            submitted_at=(now - timedelta(minutes=1))
            .isoformat()
            .replace("+00:00", "Z"),
        )
        self._setup_env(monkeypatch, ws)

        def fake_cancel(*_a, **_kw):
            resp = MagicMock()
            resp.status_code = 404
            resp.text = "not found"
            msg = "404"
            raise httpx.HTTPStatusError(
                msg, request=MagicMock(), response=resp
            )

        monkeypatch.setattr(
            "discovery.poll.cli_submit.cancel_operation", fake_cancel
        )
        result = runner.invoke(
            app, ["job", "cancel", "--since", "10m", "--yes"]
        )
        assert result.exit_code == 0
        # The op shows in the succeeded summary, not failed.
        assert "1 of 1" in result.stdout
        assert "failed" not in result.stdout.lower()

    def test_invalid_since_value_exits_2(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._setup_env(monkeypatch, "https://ws.example")
        result = runner.invoke(
            app, ["job", "cancel", "--since", "not-a-duration"]
        )
        assert result.exit_code == 2


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
