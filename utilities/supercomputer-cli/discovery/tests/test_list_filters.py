"""Tests for server-side filtering in list_operations and list_jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from discovery.poll.api import _resolve_since


class TestResolveSince:
    """Tests for the _resolve_since duration parser."""

    def test_duration_days(self):
        result = _resolve_since("7d")
        # Should be an ISO timestamp ~7 days ago
        assert "T" in result
        assert result.endswith("Z")

    def test_duration_hours(self):
        result = _resolve_since("24h")
        assert "T" in result
        assert result.endswith("Z")

    def test_duration_minutes(self):
        result = _resolve_since("30m")
        assert "T" in result
        assert result.endswith("Z")

    def test_duration_combined(self):
        result = _resolve_since("1d12h")
        assert "T" in result
        assert result.endswith("Z")

    def test_iso_date_passthrough(self):
        result = _resolve_since("2026-06-01")
        assert result == "2026-06-01T00:00:00Z"

    def test_iso_timestamp_passthrough(self):
        result = _resolve_since("2026-06-01T12:00:00Z")
        assert result == "2026-06-01T12:00:00Z"

    def test_unknown_format_passthrough(self):
        result = _resolve_since("foobar")
        assert result == "foobar"


class TestListOperationsFilters:
    """Tests that list_operations passes filter params correctly."""

    @patch("discovery.poll.dataplane_api._http_get")
    @patch("discovery.poll.dataplane_api.get_access_token", return_value="fake-token")
    def test_status_filter_passed_as_query_param(self, mock_token, mock_get):
        from discovery.poll.dataplane_api import list_operations

        mock_get.return_value = {"value": [], "nextLink": None}

        list_operations(
            "test-project",
            "https://workspace.example.com",
            api_version="2026-06-01",
            status="Running",
        )

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["status"] == "Running"

    @patch("discovery.poll.dataplane_api._http_get")
    @patch("discovery.poll.dataplane_api.get_access_token", return_value="fake-token")
    def test_created_by_filter_passed(self, mock_token, mock_get):
        from discovery.poll.dataplane_api import list_operations

        mock_get.return_value = {"value": [], "nextLink": None}

        list_operations(
            "test-project",
            "https://workspace.example.com",
            api_version="2026-06-01",
            created_by="alice@contoso.com",
        )

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["createdBy"] == "alice@contoso.com"

    @patch("discovery.poll.dataplane_api._http_get")
    @patch("discovery.poll.dataplane_api.get_access_token", return_value="fake-token")
    def test_date_filters_passed(self, mock_token, mock_get):
        from discovery.poll.dataplane_api import list_operations

        mock_get.return_value = {"value": [], "nextLink": None}

        list_operations(
            "test-project",
            "https://workspace.example.com",
            api_version="2026-06-01",
            created_after="2026-06-01T00:00:00Z",
            created_before="2026-06-20T00:00:00Z",
        )

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["createdAfter"] == "2026-06-01T00:00:00Z"
        assert params["createdBefore"] == "2026-06-20T00:00:00Z"

    @patch("discovery.poll.dataplane_api._http_get")
    @patch("discovery.poll.dataplane_api.get_access_token", return_value="fake-token")
    def test_nodepool_filter_passed(self, mock_token, mock_get):
        from discovery.poll.dataplane_api import list_operations

        mock_get.return_value = {"value": [], "nextLink": None}

        list_operations(
            "test-project",
            "https://workspace.example.com",
            api_version="2026-06-01",
            nodepool_id="/subscriptions/sub/rg/rg/np/np1",
        )

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert params["nodepoolId"] == "/subscriptions/sub/rg/rg/np/np1"

    @patch("discovery.poll.dataplane_api._http_get")
    @patch("discovery.poll.dataplane_api.get_access_token", return_value="fake-token")
    def test_no_filters_backward_compatible(self, mock_token, mock_get):
        from discovery.poll.dataplane_api import list_operations

        mock_get.return_value = {"value": [], "nextLink": None}

        list_operations(
            "test-project",
            "https://workspace.example.com",
            api_version="2026-06-01",
        )

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert "status" not in params
        assert "createdBy" not in params
        assert "createdAfter" not in params
        assert "createdBefore" not in params
        assert "nodepoolId" not in params
        # Default params should still be present
        assert params["reverse"] == "true"
        assert params["api-version"] == "2026-06-01"
