"""Tests for discovery._version module."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError
from unittest.mock import MagicMock, patch

from discovery._version import (
    _get_base_version,
    _get_commit_from_git,
    _get_commit_from_metadata,
    get_build_commit,
    get_version_string,
)


class TestGetBaseVersion:
    def test_returns_installed_version(self) -> None:
        version = _get_base_version()
        assert version == "0.1.0"

    def test_returns_fallback_on_missing_package(self) -> None:
        with patch(
            "discovery._version._md_version",
            side_effect=PackageNotFoundError("discovery"),
        ):
            result = _get_base_version()
            assert result == "0.0.0"


class TestGetCommitFromMetadata:
    def test_extracts_commit_from_vcs_info(self) -> None:
        """Simulate a git-URL install with PEP 610 direct_url.json."""
        direct_url = json.dumps({
            "url": "https://github.com/microsoft/discovery.git",
            "vcs_info": {
                "vcs": "git",
                "commit_id": "abcdef1234567890abcdef1234567890abcdef12",
                "requested_revision": "main",
            },
        })
        mock_dist = MagicMock()
        mock_dist.read_text.return_value = direct_url

        with patch("discovery._version._md_distribution", return_value=mock_dist):
            result = _get_commit_from_metadata()
        assert result == "abcdef12"

    def test_returns_none_for_editable_install(self) -> None:
        """Editable installs have dir_info, not vcs_info."""
        direct_url = json.dumps({
            "url": "file:///some/path",
            "dir_info": {"editable": True},
        })
        mock_dist = MagicMock()
        mock_dist.read_text.return_value = direct_url

        with patch("discovery._version._md_distribution", return_value=mock_dist):
            result = _get_commit_from_metadata()
        assert result is None

    def test_returns_none_when_no_direct_url(self) -> None:
        """Package installed from PyPI has no direct_url.json."""
        mock_dist = MagicMock()
        mock_dist.read_text.return_value = None

        with patch("discovery._version._md_distribution", return_value=mock_dist):
            result = _get_commit_from_metadata()
        assert result is None

    def test_returns_none_on_invalid_json(self) -> None:
        mock_dist = MagicMock()
        mock_dist.read_text.return_value = "not json"

        with patch("discovery._version._md_distribution", return_value=mock_dist):
            result = _get_commit_from_metadata()
        assert result is None


class TestGetCommitFromGit:
    def test_returns_short_hash_when_git_available(self) -> None:
        result = _get_commit_from_git()
        # In this repo, git should be available
        assert result is not None
        assert len(result) == 8

    def test_returns_none_when_git_missing(self) -> None:
        with patch(
            "discovery._version.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            result = _get_commit_from_git()
        assert result is None

    def test_returns_none_on_git_failure(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 128
        with patch("discovery._version.subprocess.run", return_value=mock_result):
            result = _get_commit_from_git()
        assert result is None


class TestGetBuildCommit:
    def test_prefers_metadata_over_git(self) -> None:
        with (
            patch("discovery._version._get_commit_from_metadata", return_value="aabbccdd"),
            patch("discovery._version._get_commit_from_git", return_value="11223344"),
        ):
            assert get_build_commit() == "aabbccdd"

    def test_falls_back_to_git(self) -> None:
        with (
            patch("discovery._version._get_commit_from_metadata", return_value=None),
            patch("discovery._version._get_commit_from_git", return_value="11223344"),
        ):
            assert get_build_commit() == "11223344"

    def test_falls_back_to_dev(self) -> None:
        with (
            patch("discovery._version._get_commit_from_metadata", return_value=None),
            patch("discovery._version._get_commit_from_git", return_value=None),
        ):
            assert get_build_commit() == "dev"


class TestGetVersionString:
    def test_version_with_commit(self) -> None:
        with (
            patch("discovery._version._get_base_version", return_value="1.2.3"),
            patch("discovery._version.get_build_commit", return_value="aabbccdd"),
        ):
            assert get_version_string() == "1.2.3+gaabbccdd"

    def test_version_with_dev(self) -> None:
        with (
            patch("discovery._version._get_base_version", return_value="1.2.3"),
            patch("discovery._version.get_build_commit", return_value="dev"),
        ):
            assert get_version_string() == "1.2.3+dev"
