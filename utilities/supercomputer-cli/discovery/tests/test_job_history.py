"""Tests for :mod:`discovery.common.job_history`."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from discovery.common import job_history


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict]:
    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    return [json.loads(line) for line in lines]


# ---------------------------------------------------------------------------
# record_submission
# ---------------------------------------------------------------------------


class TestRecordSubmission:
    def test_appends_entry_with_all_fields(self) -> None:
        entry = job_history.record_submission(
            "op-1",
            command="echo hello",
            tool_id="tool/123",
            nodepool_id="np/abc",
            project_name="proj-x",
            workspace_url="https://ws.example",
            mode=job_history.MODE_START,
            cli_argv=["discovery", "job", "start", "echo hello"],
            hostname="laptop-1",
            submitted_at="2026-06-01T12:00:00Z",
        )
        assert entry is not None
        assert entry.operation_id == "op-1"

        records = _read_jsonl(job_history.history_path())
        assert len(records) == 1
        r = records[0]
        assert r["operation_id"] == "op-1"
        assert r["command"] == "echo hello"
        assert r["tool_id"] == "tool/123"
        assert r["nodepool_id"] == "np/abc"
        assert r["project_name"] == "proj-x"
        assert r["workspace_url"] == "https://ws.example"
        assert r["mode"] == "start"
        assert r["cli_argv"] == ["discovery", "job", "start", "echo hello"]
        assert r["hostname"] == "laptop-1"
        assert r["submitted_at"] == "2026-06-01T12:00:00Z"
        assert r["schema_version"] == job_history.SCHEMA_VERSION

    def test_returns_none_when_opted_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(job_history.ENV_OPT_OUT, "1")
        entry = job_history.record_submission("op-1", command="x")
        assert entry is None
        assert not job_history.history_path().exists()

    def test_skips_empty_operation_id(self) -> None:
        assert job_history.record_submission("") is None
        assert not job_history.history_path().exists()

    def test_swallows_io_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_a, **_kw):
            msg = "disk full"
            raise OSError(msg)

        monkeypatch.setattr(
            "discovery.common.job_history.Path.open", boom
        )
        # Should not raise — recording is opportunistic.
        result = job_history.record_submission("op-1", command="x")
        assert result is None


# ---------------------------------------------------------------------------
# Concurrent submits (the batch case)
# ---------------------------------------------------------------------------


class TestConcurrentAppends:
    def test_thread_safe_under_concurrent_writes(self) -> None:
        """All records from N threads must land in the file intact."""
        threads = []
        n = 50
        for i in range(n):
            t = threading.Thread(
                target=job_history.record_submission,
                args=(f"op-{i}",),
                kwargs={"command": f"cmd {i}", "mode": job_history.MODE_BATCH},
            )
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        records = _read_jsonl(job_history.history_path())
        assert len(records) == n
        # Every operation_id must be present exactly once and the lines
        # must be parseable (no torn writes).
        ids = {r["operation_id"] for r in records}
        assert ids == {f"op-{i}" for i in range(n)}


# ---------------------------------------------------------------------------
# load_history filtering
# ---------------------------------------------------------------------------


class TestLoadHistory:
    @pytest.fixture
    def _seeded(self) -> None:
        job_history.record_submission(
            "op-a",
            workspace_url="ws-1",
            project_name="proj-1",
            hostname="host-a",
            submitted_at="2026-05-01T00:00:00Z",
        )
        job_history.record_submission(
            "op-b",
            workspace_url="ws-1",
            project_name="proj-2",
            hostname="host-a",
            submitted_at="2026-05-15T00:00:00Z",
        )
        job_history.record_submission(
            "op-c",
            workspace_url="ws-2",
            project_name="proj-1",
            hostname="host-b",
            submitted_at="2026-06-01T00:00:00Z",
        )

    @pytest.mark.usefixtures("_seeded")
    def test_loads_all_when_unfiltered(self) -> None:
        entries = job_history.load_history()
        assert {e.operation_id for e in entries} == {"op-a", "op-b", "op-c"}

    @pytest.mark.usefixtures("_seeded")
    def test_filters_by_workspace(self) -> None:
        entries = job_history.load_history(workspace_url="ws-1")
        assert {e.operation_id for e in entries} == {"op-a", "op-b"}

    @pytest.mark.usefixtures("_seeded")
    def test_filters_by_project(self) -> None:
        entries = job_history.load_history(project_name="proj-1")
        assert {e.operation_id for e in entries} == {"op-a", "op-c"}

    @pytest.mark.usefixtures("_seeded")
    def test_filters_by_hostname(self) -> None:
        entries = job_history.load_history(hostname="host-b")
        assert {e.operation_id for e in entries} == {"op-c"}

    @pytest.mark.usefixtures("_seeded")
    def test_filters_by_since(self) -> None:
        since = datetime(2026, 5, 10, tzinfo=timezone.utc)
        entries = job_history.load_history(since=since)
        assert {e.operation_id for e in entries} == {"op-b", "op-c"}

    @pytest.mark.usefixtures("_seeded")
    def test_combined_filters(self) -> None:
        entries = job_history.load_history(
            workspace_url="ws-1", project_name="proj-2"
        )
        assert {e.operation_id for e in entries} == {"op-b"}

    def test_returns_empty_when_no_file(self) -> None:
        assert job_history.load_history() == []

    def test_skips_corrupt_lines(self) -> None:
        path = job_history.history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "{not json}\n"
            + json.dumps({"operation_id": "op-1", "submitted_at": "2026-01-01T00:00:00Z"})
            + "\n"
            + json.dumps({"no_id": True})
            + "\n",
            encoding="utf-8",
        )
        entries = job_history.load_history()
        assert len(entries) == 1
        assert entries[0].operation_id == "op-1"

    def test_ignores_unknown_keys_in_records(self) -> None:
        path = job_history.history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "operation_id": "op-1",
                "submitted_at": "2026-01-01T00:00:00Z",
                "future_field_we_dont_know_about": 42,
            })
            + "\n",
            encoding="utf-8",
        )
        entries = job_history.load_history()
        assert len(entries) == 1
        assert entries[0].operation_id == "op-1"


# ---------------------------------------------------------------------------
# local_operation_ids
# ---------------------------------------------------------------------------


class TestLocalOperationIds:
    def test_returns_set_of_ids(self) -> None:
        job_history.record_submission("op-1", workspace_url="w")
        job_history.record_submission("op-2", workspace_url="w")
        assert job_history.local_operation_ids(workspace_url="w") == {
            "op-1",
            "op-2",
        }

    def test_scoped_by_workspace(self) -> None:
        job_history.record_submission("op-1", workspace_url="w1")
        job_history.record_submission("op-2", workspace_url="w2")
        assert job_history.local_operation_ids(workspace_url="w1") == {"op-1"}


# ---------------------------------------------------------------------------
# prune + clear
# ---------------------------------------------------------------------------


class TestPruneAndClear:
    def test_prune_by_count(self) -> None:
        for i in range(5):
            job_history.record_submission(
                f"op-{i}", submitted_at=f"2026-05-0{i+1}T00:00:00Z"
            )
        removed = job_history.prune(keep_count=2)
        assert removed == 3
        remaining = {e.operation_id for e in job_history.load_history()}
        # Newest two retained (load_history preserves write order).
        assert remaining == {"op-3", "op-4"}

    def test_prune_by_since(self) -> None:
        job_history.record_submission(
            "old", submitted_at="2025-01-01T00:00:00Z"
        )
        job_history.record_submission(
            "new", submitted_at="2026-06-01T00:00:00Z"
        )
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        removed = job_history.prune(keep_since=since)
        assert removed == 1
        remaining = {e.operation_id for e in job_history.load_history()}
        assert remaining == {"new"}

    def test_prune_noop_when_nothing_to_remove(self) -> None:
        job_history.record_submission("op-1")
        assert job_history.prune(keep_count=10) == 0

    def test_clear_deletes_file_and_returns_count(self) -> None:
        for i in range(3):
            job_history.record_submission(f"op-{i}")
        assert job_history.clear() == 3
        assert not job_history.history_path().exists()

    def test_clear_on_missing_file_returns_zero(self) -> None:
        assert job_history.clear() == 0


# ---------------------------------------------------------------------------
# is_disabled
# ---------------------------------------------------------------------------


class TestIsDisabled:
    def test_default_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(job_history.ENV_OPT_OUT, raising=False)
        assert job_history.is_disabled() is False

    def test_recognizes_truthy_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for v in ("1", "true", "yes", "on", "TRUE"):
            monkeypatch.setenv(job_history.ENV_OPT_OUT, v)
            assert job_history.is_disabled() is True

    def test_ignores_other_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(job_history.ENV_OPT_OUT, "0")
        assert job_history.is_disabled() is False


# ---------------------------------------------------------------------------
# parse_since (used by --since shorthand on history and cancel)
# ---------------------------------------------------------------------------


class TestParseSince:
    def test_supports_seconds(self) -> None:
        result = job_history.parse_since("30s")
        # Should be ~30 seconds in the past, within a generous tolerance
        # to absorb test-runner latency.
        delta = (datetime.now(tz=timezone.utc) - result).total_seconds()
        assert 25 <= delta <= 60

    def test_supports_minutes(self) -> None:
        result = job_history.parse_since("10m")
        delta = (datetime.now(tz=timezone.utc) - result).total_seconds()
        # 10 minutes = 600s; allow ±60s slack
        assert 540 <= delta <= 660

    def test_supports_hours(self) -> None:
        result = job_history.parse_since("24h")
        delta = (datetime.now(tz=timezone.utc) - result).total_seconds()
        # 24h = 86400s; allow ±300s
        assert 86100 <= delta <= 86700

    def test_supports_days_and_weeks(self) -> None:
        a = job_history.parse_since("7d")
        b = job_history.parse_since("1w")
        # 7d and 1w are identical
        assert abs((a - b).total_seconds()) < 5

    def test_absolute_date(self) -> None:
        result = job_history.parse_since("2026-01-15")
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 15
        assert result.tzinfo is not None

    @pytest.mark.parametrize(
        "bad",
        ["", "   ", "10x", "abc", "10", "min", "2026-13-99"],
    )
    def test_raises_on_empty_or_garbage(self, bad: str) -> None:
        with pytest.raises(ValueError, match=r"(Invalid|empty)"):
            job_history.parse_since(bad)
