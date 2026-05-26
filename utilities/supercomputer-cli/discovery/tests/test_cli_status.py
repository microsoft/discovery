"""Tests for cli_status pagination and terminal size handling."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from discovery.poll import cli_status
from discovery.poll.cli_status import _format_duration
from discovery.poll.models.tool_response import OperationsListResponse, OperationsResultModel


def _make_operations(count: int) -> list[OperationsResultModel]:
    """Create *count* fake operation result models."""
    ops = []
    for i in range(count):
        # Spread across multiple days to avoid hour overflow
        day_offset = i // 1440  # 1440 = 24*60
        remainder = i % 1440
        hour, minute = divmod(remainder, 60)
        ops.append(
            OperationsResultModel.model_validate(
                {
                    "nodepoolId": "np",
                    "id": f"op-{i:04d}",
                    "status": "Succeeded",
                    "runtimeDetails": "done",
                    "createdAt": f"2025-01-{15 + day_offset:02d}T{hour:02d}:{minute:02d}:00Z",
                    "completedAt": f"2025-01-{15 + day_offset:02d}T{hour:02d}:{minute:02d}:30Z",
                    "createdBy": "user@example.com",
                }
            )
        )
    return ops


def _make_list_response(
    ops: list[OperationsResultModel], next_link: str | None = None
) -> OperationsListResponse:
    return OperationsListResponse(values=ops, next_link=next_link)


class TestPageSizeAutoDetection:
    """Ensure page_size adapts to small terminal heights."""

    @pytest.mark.parametrize(
        "term_lines, expected_page_size",
        [
            (80, 72),   # large terminal: 80 - 8 = 72
            (24, 16),   # standard terminal: 24 - 8 = 16
            (15, 7),    # small terminal: 15 - 8 = 7
            (12, 4),    # very small: 12 - 8 = 4
            (10, 2),    # tiny: 10 - 8 = 2
            (9, 1),     # minimum clamp: 9 - 8 = 1
            (5, 1),     # below minimum: max(1, -3) = 1
        ],
    )
    def test_page_size_scales_with_terminal_height(
        self, term_lines: int, expected_page_size: int
    ) -> None:
        """Page size should equal max(1, term_height - 8) for any terminal height.

        Previously used max(10, ...) which caused jobs to disappear in small
        terminals because the table exceeded the visible area.
        """
        # Use enough ops so even the largest page_size is smaller than total
        total_ops = 100
        ops = _make_operations(total_ops)

        fake_env = MagicMock()
        fake_env.project_name = "proj"
        fake_env.workspace_url = "https://example.com"

        displayed_batches: list[int] = []

        original_console_print = None

        class CapturingConsole:
            """Console that records how many rows each table has."""

            def __init__(self, *a, **kw):
                pass

            def print(self, renderable):
                from rich.table import Table
                if isinstance(renderable, Table):
                    displayed_batches.append(renderable.row_count)

            def status(self, *a, **kw):
                return MagicMock()

        mock_size = MagicMock()
        mock_size.lines = term_lines

        with (
            patch.object(cli_status.shutil, "get_terminal_size", return_value=mock_size),
            patch.object(cli_status, "Console", CapturingConsole),
            patch.object(
                cli_status,
                "list_operations",
                return_value=_make_list_response(ops),
            ),
            patch.object(cli_status, "info"),
            patch.object(cli_status, "typer") as mock_typer,
        ):
            # Decline to fetch more after first batch
            mock_typer.confirm.return_value = False

            asyncio.run(
                cli_status._paginated_list(
                    env_cfg=fake_env,
                    filter_fn=lambda op: True,
                    limit=total_ops,
                    page_size=0,  # trigger auto-detection
                )
            )

        # First batch should contain exactly expected_page_size rows
        assert len(displayed_batches) >= 1
        assert displayed_batches[0] == expected_page_size

    def test_explicit_page_size_skips_auto_detection(self) -> None:
        """When page_size > 0 is passed, terminal height should not be queried."""
        ops = _make_operations(5)

        fake_env = MagicMock()
        fake_env.project_name = "proj"
        fake_env.workspace_url = "https://example.com"

        displayed_batches: list[int] = []

        class CapturingConsole:
            def __init__(self, *a, **kw):
                pass

            def print(self, renderable):
                from rich.table import Table
                if isinstance(renderable, Table):
                    displayed_batches.append(renderable.row_count)

            def status(self, *a, **kw):
                return MagicMock()

        with (
            patch.object(
                cli_status.shutil,
                "get_terminal_size",
                side_effect=AssertionError("should not be called"),
            ),
            patch.object(cli_status, "Console", CapturingConsole),
            patch.object(
                cli_status,
                "list_operations",
                return_value=_make_list_response(ops),
            ),
            patch.object(cli_status, "info"),
            patch.object(cli_status.typer, "confirm", return_value=True),
        ):
            asyncio.run(
                cli_status._paginated_list(
                    env_cfg=fake_env,
                    filter_fn=lambda op: True,
                    limit=10,
                    page_size=3,  # explicit — no auto-detection
                )
            )

        assert displayed_batches[0] == 3


class TestFormatDuration:
    """Tests for the _format_duration helper."""

    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (0, "0s"),
            (5, "5s"),
            (59, "59s"),
            (60, "1m"),
            (90, "1m 30s"),
            (3600, "1h"),
            (3661, "1h 1m"),
            (7200, "2h"),
            (8100, "2h 15m"),
            (86400, "1d"),
            (90000, "1d 1h"),
            (259200, "3d"),
            (277200, "3d 5h"),
        ],
    )
    def test_completed_durations(self, seconds: int, expected: str) -> None:
        """Completed jobs should show compact two-unit duration without suffix."""
        assert _format_duration(timedelta(seconds=seconds)) == expected

    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (30, "30s+"),
            (3661, "1h 1m+"),
            (90000, "1d 1h+"),
        ],
    )
    def test_in_progress_suffix(self, seconds: int, expected: str) -> None:
        """In-progress jobs should append '+' suffix."""
        assert _format_duration(timedelta(seconds=seconds), in_progress=True) == expected

    def test_negative_duration_returns_zero(self) -> None:
        """Negative timedelta (clock skew) should return '0s'."""
        assert _format_duration(timedelta(seconds=-10)) == "0s"


class TestLargeWorkspacePagination:
    """Stress tests for workspaces with 1000+ operations (e.g. BHP)."""

    PAGE_SIZE = 128  # Server default page size

    def _make_paged_responses(
        self, total_ops: int, page_size: int = 128
    ) -> list[OperationsListResponse]:
        """Build a list of OperationsListResponse objects simulating server pages."""
        all_ops = _make_operations(total_ops)
        pages = []
        for i in range(0, total_ops, page_size):
            chunk = all_ops[i : i + page_size]
            has_next = i + page_size < total_ops
            next_link = f"https://example.com/next?skip={i + page_size}" if has_next else None
            pages.append(_make_list_response(chunk, next_link=next_link))
        return pages

    def test_5000_ops_no_duplicates_no_missing(self) -> None:
        """Paginating through 5000 ops must yield exactly 5000 unique IDs."""
        total = 5000
        pages = self._make_paged_responses(total)
        page_iter = iter(pages)

        fake_env = MagicMock()
        fake_env.project_name = "proj"
        fake_env.workspace_url = "https://example.com"
        fake_env.api_version = "2025-07-01-preview"
        fake_env.nodepools = []

        collected_ids: list[str] = []

        class CapturingConsole:
            def __init__(self, *a, **kw):
                pass

            def print(self, renderable):
                from rich.table import Table

                if isinstance(renderable, Table):
                    # Extract IDs from the first column of each row
                    for row_idx in range(renderable.row_count):
                        cells = renderable.columns[0]._cells
                        collected_ids.append(cells[row_idx])

            def status(self, *a, **kw):
                return MagicMock()

        def mock_list_ops(*args, **kwargs):
            return next(page_iter)

        def mock_list_page(next_link):
            return next(page_iter)

        with (
            patch.object(cli_status, "Console", CapturingConsole),
            patch.object(cli_status, "list_operations", side_effect=mock_list_ops),
            patch.object(cli_status, "list_operations_page", side_effect=mock_list_page),
            patch.object(cli_status, "info"),
            patch.object(cli_status, "debug"),
            patch.object(cli_status.typer, "confirm", return_value=True),
        ):
            asyncio.run(
                cli_status._paginated_list(
                    env_cfg=fake_env,
                    filter_fn=lambda op: True,
                    limit=total,
                    page_size=50,  # display 50 per batch
                )
            )

        assert len(collected_ids) == total, f"Expected {total} ops, got {len(collected_ids)}"
        unique = set(collected_ids)
        assert len(unique) == total, f"Found {total - len(unique)} duplicates"

    def test_1000_ops_with_filter_scans_all_pages(self) -> None:
        """Filter that matches 10% of 1000 ops must still scan all pages."""
        total = 1000
        pages = self._make_paged_responses(total)
        page_iter = iter(pages)

        fake_env = MagicMock()
        fake_env.project_name = "proj"
        fake_env.workspace_url = "https://example.com"
        fake_env.api_version = "2025-07-01-preview"
        fake_env.nodepools = []

        collected_ids: list[str] = []

        class CapturingConsole:
            def __init__(self, *a, **kw):
                pass

            def print(self, renderable):
                from rich.table import Table

                if isinstance(renderable, Table):
                    for row_idx in range(renderable.row_count):
                        cells = renderable.columns[0]._cells
                        collected_ids.append(cells[row_idx])

            def status(self, *a, **kw):
                return MagicMock()

        def mock_list_ops(*args, **kwargs):
            return next(page_iter)

        def mock_list_page(next_link):
            return next(page_iter)

        # Only match every 10th operation
        match_count = 0

        def sparse_filter(op):
            nonlocal match_count
            idx = int(op.id.split("-")[1])
            if idx % 10 == 0:
                match_count += 1
                return True
            return False

        with (
            patch.object(cli_status, "Console", CapturingConsole),
            patch.object(cli_status, "list_operations", side_effect=mock_list_ops),
            patch.object(cli_status, "list_operations_page", side_effect=mock_list_page),
            patch.object(cli_status, "info"),
            patch.object(cli_status, "debug"),
            patch.object(cli_status.typer, "confirm", return_value=True),
        ):
            asyncio.run(
                cli_status._paginated_list(
                    env_cfg=fake_env,
                    filter_fn=sparse_filter,
                    limit=total,
                    page_size=20,
                )
            )

        expected_matches = total // 10  # 100
        assert len(collected_ids) == expected_matches, (
            f"Expected {expected_matches} matches, got {len(collected_ids)}"
        )

    def test_5000_ops_limit_200_stops_early(self) -> None:
        """With --limit 200, should stop scanning after 200 ops regardless of total."""
        total = 5000
        pages = self._make_paged_responses(total)
        page_iter = iter(pages)

        fake_env = MagicMock()
        fake_env.project_name = "proj"
        fake_env.workspace_url = "https://example.com"
        fake_env.api_version = "2025-07-01-preview"
        fake_env.nodepools = []

        api_calls = {"count": 0}

        class CapturingConsole:
            def __init__(self, *a, **kw):
                pass

            def print(self, renderable):
                pass

            def status(self, *a, **kw):
                return MagicMock()

        def mock_list_ops(*args, **kwargs):
            api_calls["count"] += 1
            return next(page_iter)

        def mock_list_page(next_link):
            api_calls["count"] += 1
            return next(page_iter)

        with (
            patch.object(cli_status, "Console", CapturingConsole),
            patch.object(cli_status, "list_operations", side_effect=mock_list_ops),
            patch.object(cli_status, "list_operations_page", side_effect=mock_list_page),
            patch.object(cli_status, "info"),
            patch.object(cli_status, "debug"),
            patch.object(cli_status.typer, "confirm", return_value=True),
        ):
            asyncio.run(
                cli_status._paginated_list(
                    env_cfg=fake_env,
                    filter_fn=lambda op: True,
                    limit=200,
                    page_size=50,
                )
            )

        # With limit=200 and page_size=128, should fetch at most 2 API pages
        assert api_calls["count"] <= 2, (
            f"Fetched {api_calls['count']} API pages for limit=200 (expected <=2)"
        )

    def test_timeout_on_first_page_shows_helpful_error(self) -> None:
        """ReadTimeout on first API call should show actionable error message."""
        import httpx

        fake_env = MagicMock()
        fake_env.project_name = "proj"
        fake_env.workspace_url = "https://example.com"
        fake_env.api_version = "2025-07-01-preview"
        fake_env.nodepools = []

        def mock_list_ops(*args, **kwargs):
            raise httpx.ReadTimeout("Connection timed out")

        with (
            patch.object(cli_status, "Console", MagicMock),
            patch.object(cli_status, "list_operations", side_effect=mock_list_ops),
            patch.object(cli_status, "info"),
            patch.object(cli_status, "debug"),
            patch.object(cli_status, "error") as mock_error,
        ):
            with pytest.raises((SystemExit, Exception)):
                asyncio.run(
                    cli_status._paginated_list(
                        env_cfg=fake_env,
                        filter_fn=lambda op: True,
                        limit=5000,
                        page_size=50,
                    )
                )

        # Should show actionable guidance
        error_msg = mock_error.call_args[0][0]
        assert "--limit" in error_msg or "--pool" in error_msg
