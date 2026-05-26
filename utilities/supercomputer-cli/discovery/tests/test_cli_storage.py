"""Tests for cli_storage module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from discovery.poll.cli_storage import (
    StorageType,
    _format_size,
    parse_storage_path,
    remove_blobs_az,
)


class TestParseStoragePath:
    """Tests for parse_storage_path function."""

    def test_user_prefix(self) -> None:
        """Test parsing path with user: prefix."""
        container, path = parse_storage_path("user:data/file.txt", "testuser")
        assert container == "testuser"
        assert path == "data/file.txt"

    def test_shared_prefix(self) -> None:
        """Test parsing path with shared: prefix."""
        container, path = parse_storage_path("shared:models/model.bin", "testuser")
        assert container == "shared"
        assert path == "models/model.bin"

    def test_no_prefix_defaults_to_user(self) -> None:
        """Test parsing path without prefix defaults to user storage."""
        container, path = parse_storage_path("data/file.txt", "testuser")
        assert container == "testuser"
        assert path == "data/file.txt"

    def test_user_prefix_with_leading_slash(self) -> None:
        """Test parsing path with user: prefix and leading slash."""
        container, path = parse_storage_path("user:/data/file.txt", "testuser")
        assert container == "testuser"
        assert path == "data/file.txt"

    def test_shared_prefix_with_leading_slash(self) -> None:
        """Test parsing path with shared: prefix and leading slash."""
        container, path = parse_storage_path("shared:/models/", "testuser")
        assert container == "shared"
        assert path == "models/"

    def test_empty_path_with_user_prefix(self) -> None:
        """Test parsing empty path with user: prefix."""
        container, path = parse_storage_path("user:", "testuser")
        assert container == "testuser"
        assert path == ""

    def test_empty_path_with_shared_prefix(self) -> None:
        """Test parsing empty path with shared: prefix."""
        container, path = parse_storage_path("shared:", "testuser")
        assert container == "shared"
        assert path == ""

    def test_empty_path_defaults_to_user(self) -> None:
        """Test parsing empty path defaults to user storage."""
        container, path = parse_storage_path("", "testuser")
        assert container == "testuser"
        assert path == ""

    def test_path_with_leading_slash(self) -> None:
        """Test parsing path with leading slash."""
        container, path = parse_storage_path("/data/file.txt", "testuser")
        assert container == "testuser"
        assert path == "data/file.txt"

    def test_dot_notation_defaults_to_user_root(self) -> None:
        """Test parsing '.' as root of user storage."""
        container, path = parse_storage_path(".", "testuser")
        assert container == "testuser"
        assert path == ""

    def test_user_dot_notation(self) -> None:
        """Test parsing 'user:.' as root of user storage."""
        container, path = parse_storage_path("user:.", "testuser")
        assert container == "testuser"
        assert path == ""

    def test_shared_dot_notation(self) -> None:
        """Test parsing 'shared:.' as root of shared storage."""
        container, path = parse_storage_path("shared:.", "testuser")
        assert container == "shared"
        assert path == ""


class TestFormatSize:
    """Tests for _format_size function."""

    def test_bytes(self) -> None:
        """Test formatting size in bytes."""
        assert _format_size(0) == "0 B"
        assert _format_size(512) == "512 B"
        assert _format_size(1023) == "1023 B"

    def test_kilobytes(self) -> None:
        """Test formatting size in kilobytes."""
        assert _format_size(1024) == "1.0 KB"
        assert _format_size(1536) == "1.5 KB"

    def test_megabytes(self) -> None:
        """Test formatting size in megabytes."""
        assert _format_size(1024 * 1024) == "1.0 MB"
        assert _format_size(int(1.5 * 1024 * 1024)) == "1.5 MB"

    def test_gigabytes(self) -> None:
        """Test formatting size in gigabytes."""
        assert _format_size(1024 * 1024 * 1024) == "1.0 GB"
        assert _format_size(int(2.5 * 1024 * 1024 * 1024)) == "2.5 GB"

    def test_terabytes(self) -> None:
        """Test formatting size in terabytes."""
        assert _format_size(1024 * 1024 * 1024 * 1024) == "1.0 TB"


class TestStorageType:
    """Tests for StorageType enum."""

    def test_user_value(self) -> None:
        """Test USER storage type value."""
        assert StorageType.USER.value == "user"

    def test_shared_value(self) -> None:
        """Test SHARED storage type value."""
        assert StorageType.SHARED.value == "shared"


class TestUploadCommand:
    """Tests for upload command."""

    @patch("discovery.poll.cli_storage.load_project_config")
    @patch("discovery.poll.cli_storage.get_azure_username")
    @patch("discovery.poll.cli_storage.get_storage_account_name")
    @patch("discovery.poll.cli_storage.run_azcopy_command")
    def test_upload_to_user_storage(
        self,
        mock_azcopy: MagicMock,
        mock_storage_name: MagicMock,
        mock_username: MagicMock,
        mock_config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test upload to user storage."""
        from typer.testing import CliRunner

        from discovery.poll.cli_storage import app

        # Setup mocks
        mock_config.return_value = MagicMock(datacontainer_id="test-container-id")
        mock_username.return_value = "testuser"
        mock_storage_name.return_value = "teststorageaccount"
        mock_azcopy.return_value = MagicMock(returncode=0)

        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        runner = CliRunner()
        result = runner.invoke(app, ["upload", str(test_file), "user:data/test.txt"])

        assert result.exit_code == 0
        mock_azcopy.assert_called_once()
        call_args = mock_azcopy.call_args[0][0]
        assert "copy" in call_args
        assert str(test_file) in call_args
        assert "testuser" in call_args[2]

    @patch("discovery.poll.cli_storage.load_project_config")
    def test_upload_no_datacontainer(
        self,
        mock_config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test upload fails when datacontainer not configured."""
        from typer.testing import CliRunner

        from discovery.poll.cli_storage import app

        mock_config.return_value = MagicMock(datacontainer_id="")

        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        runner = CliRunner()
        result = runner.invoke(app, ["upload", str(test_file), "data/test.txt"])

        assert result.exit_code == 1


class TestDownloadCommand:
    """Tests for download command."""

    @patch("discovery.poll.cli_storage.load_project_config")
    @patch("discovery.poll.cli_storage.get_azure_username")
    @patch("discovery.poll.cli_storage.get_storage_account_name")
    @patch("discovery.poll.cli_storage.run_azcopy_command")
    def test_download_from_shared_storage(
        self,
        mock_azcopy: MagicMock,
        mock_storage_name: MagicMock,
        mock_username: MagicMock,
        mock_config: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test download from shared storage."""
        from typer.testing import CliRunner

        from discovery.poll.cli_storage import app

        # Setup mocks
        mock_config.return_value = MagicMock(datacontainer_id="test-container-id")
        mock_username.return_value = "testuser"
        mock_storage_name.return_value = "teststorageaccount"
        mock_azcopy.return_value = MagicMock(returncode=0)

        runner = CliRunner()
        result = runner.invoke(app, ["download", "shared:models/model.bin", str(tmp_path)])

        assert result.exit_code == 0
        mock_azcopy.assert_called_once()
        call_args = mock_azcopy.call_args[0][0]
        assert "copy" in call_args
        assert "shared" in call_args[1]


class TestLsCommand:
    """Tests for ls command."""

    @patch("discovery.poll.cli_storage.load_project_config")
    @patch("discovery.poll.cli_storage.get_azure_username")
    @patch("discovery.poll.cli_storage.get_storage_account_name")
    @patch("discovery.poll.cli_storage.list_blobs_az")
    def test_ls_user_storage(
        self,
        mock_list_blobs: MagicMock,
        mock_storage_name: MagicMock,
        mock_username: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test listing user storage."""
        from typer.testing import CliRunner

        from discovery.poll.cli_storage import app

        # Setup mocks
        mock_config.return_value = MagicMock(
            datacontainer_id="test-container-id",
            subscription="test-subscription",
        )
        mock_username.return_value = "testuser"
        mock_storage_name.return_value = "teststorageaccount"
        mock_list_blobs.return_value = [
            {"name": "data/file1.txt", "properties": {"contentLength": 1024, "lastModified": "2024-01-01T00:00:00Z"}},
            {"name": "data/file2.txt", "properties": {"contentLength": 2048, "lastModified": "2024-01-02T00:00:00Z"}},
        ]

        runner = CliRunner()
        result = runner.invoke(app, ["ls", "user:data/"])

        assert result.exit_code == 0
        assert "2 item(s)" in result.output

    @patch("discovery.poll.cli_storage.load_project_config")
    @patch("discovery.poll.cli_storage.get_azure_username")
    @patch("discovery.poll.cli_storage.get_storage_account_name")
    @patch("discovery.poll.cli_storage.list_blobs_az")
    def test_ls_long_format(
        self,
        mock_list_blobs: MagicMock,
        mock_storage_name: MagicMock,
        mock_username: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test listing with long format (default, detailed output)."""
        from typer.testing import CliRunner

        from discovery.poll.cli_storage import app

        # Setup mocks
        mock_config.return_value = MagicMock(
            datacontainer_id="test-container-id",
            subscription="test-subscription",
        )
        mock_username.return_value = "testuser"
        mock_storage_name.return_value = "teststorageaccount"
        mock_list_blobs.return_value = [
            {"name": "file.txt", "properties": {"contentLength": 1024, "lastModified": "2024-01-01T00:00:00Z"}},
        ]

        runner = CliRunner()
        # Long format is the default (no flags needed)
        result = runner.invoke(app, ["ls"])

        assert result.exit_code == 0
        # Long format should include size information
        assert "1.0 KB" in result.output or "1024" in result.output

    @patch("discovery.poll.cli_storage.load_project_config")
    @patch("discovery.poll.cli_storage.get_azure_username")
    @patch("discovery.poll.cli_storage.get_storage_account_name")
    @patch("discovery.poll.cli_storage.list_blobs_az")
    def test_ls_empty_directory(
        self,
        mock_list_blobs: MagicMock,
        mock_storage_name: MagicMock,
        mock_username: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test listing empty directory."""
        from typer.testing import CliRunner

        from discovery.poll.cli_storage import app

        # Setup mocks
        mock_config.return_value = MagicMock(
            datacontainer_id="test-container-id",
            subscription="test-subscription",
        )
        mock_username.return_value = "testuser"
        mock_storage_name.return_value = "teststorageaccount"
        mock_list_blobs.return_value = []

        runner = CliRunner()
        result = runner.invoke(app, ["ls", "user:empty/"])

        assert result.exit_code == 0
        assert "No files found" in result.output


class TestRemoveCommand:
    """Tests for remove command."""

    @patch("discovery.poll.cli_storage.load_project_config")
    @patch("discovery.poll.cli_storage.get_azure_username")
    @patch("discovery.poll.cli_storage.get_storage_account_name")
    @patch("discovery.poll.cli_storage.list_blobs_az")
    @patch("discovery.poll.cli_storage.remove_blobs_az")
    def test_remove_single_file_with_force(
        self,
        mock_remove_blobs: MagicMock,
        mock_list_blobs: MagicMock,
        mock_storage_name: MagicMock,
        mock_username: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test removing a single file with --force."""
        from typer.testing import CliRunner

        from discovery.poll.cli_storage import app

        # Setup mocks
        mock_config.return_value = MagicMock(
            datacontainer_id="test-container-id",
            subscription="test-subscription",
        )
        mock_username.return_value = "testuser"
        mock_storage_name.return_value = "teststorageaccount"
        mock_list_blobs.return_value = [
            {"name": "data/file.txt", "properties": {"contentLength": 1024}},
        ]
        mock_remove_blobs.return_value = (True, "")

        runner = CliRunner()
        result = runner.invoke(app, ["remove", "user:data/file.txt", "-f"])

        assert result.exit_code == 0
        assert "Removed" in result.output
        mock_remove_blobs.assert_called_once()

    @patch("discovery.poll.cli_storage.load_project_config")
    @patch("discovery.poll.cli_storage.get_azure_username")
    @patch("discovery.poll.cli_storage.get_storage_account_name")
    @patch("discovery.poll.cli_storage.list_blobs_az")
    @patch("discovery.poll.cli_storage.remove_blobs_az")
    def test_remove_directory_recursive(
        self,
        mock_remove_blobs: MagicMock,
        mock_list_blobs: MagicMock,
        mock_storage_name: MagicMock,
        mock_username: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test removing directory with --recursive --force."""
        from typer.testing import CliRunner

        from discovery.poll.cli_storage import app

        # Setup mocks
        mock_config.return_value = MagicMock(
            datacontainer_id="test-container-id",
            subscription="test-subscription",
        )
        mock_username.return_value = "testuser"
        mock_storage_name.return_value = "teststorageaccount"
        mock_list_blobs.return_value = [
            {"name": "data/dir/file1.txt", "properties": {"contentLength": 1024}},
            {"name": "data/dir/file2.txt", "properties": {"contentLength": 2048}},
            {"name": "data/dir/subdir/file3.txt", "properties": {"contentLength": 512}},
        ]
        mock_remove_blobs.return_value = (True, "")

        runner = CliRunner()
        result = runner.invoke(app, ["remove", "user:data/dir/", "-rf"])

        assert result.exit_code == 0
        assert "Removed 3 file(s)" in result.output
        mock_remove_blobs.assert_called_once()

    @patch("discovery.poll.cli_storage.load_project_config")
    @patch("discovery.poll.cli_storage.get_azure_username")
    @patch("discovery.poll.cli_storage.get_storage_account_name")
    @patch("discovery.poll.cli_storage.list_blobs_az")
    def test_remove_directory_without_recursive_fails(
        self,
        mock_list_blobs: MagicMock,
        mock_storage_name: MagicMock,
        mock_username: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test removing directory without --recursive fails."""
        from typer.testing import CliRunner

        from discovery.poll.cli_storage import app

        # Setup mocks
        mock_config.return_value = MagicMock(
            datacontainer_id="test-container-id",
            subscription="test-subscription",
        )
        mock_username.return_value = "testuser"
        mock_storage_name.return_value = "teststorageaccount"
        mock_list_blobs.return_value = [
            {"name": "data/dir/file1.txt", "properties": {"contentLength": 1024}},
            {"name": "data/dir/file2.txt", "properties": {"contentLength": 2048}},
        ]

        runner = CliRunner()
        result = runner.invoke(app, ["remove", "user:data/dir/", "-f"])

        assert result.exit_code == 1
        assert "Use -r/--recursive" in result.output

    @patch("discovery.poll.cli_storage.load_project_config")
    @patch("discovery.poll.cli_storage.get_azure_username")
    @patch("discovery.poll.cli_storage.get_storage_account_name")
    @patch("discovery.poll.cli_storage.list_blobs_az")
    def test_remove_no_files_found(
        self,
        mock_list_blobs: MagicMock,
        mock_storage_name: MagicMock,
        mock_username: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test removing nonexistent file."""
        from typer.testing import CliRunner

        from discovery.poll.cli_storage import app

        # Setup mocks
        mock_config.return_value = MagicMock(
            datacontainer_id="test-container-id",
            subscription="test-subscription",
        )
        mock_username.return_value = "testuser"
        mock_storage_name.return_value = "teststorageaccount"
        mock_list_blobs.return_value = []

        runner = CliRunner()
        result = runner.invoke(app, ["remove", "user:nonexistent.txt", "-f"])

        assert result.exit_code == 1
        assert "No files found" in result.output

    @patch("discovery.poll.cli_storage.load_project_config")
    def test_remove_no_datacontainer(
        self,
        mock_config: MagicMock,
    ) -> None:
        """Test remove fails when datacontainer not configured."""
        from typer.testing import CliRunner

        from discovery.poll.cli_storage import app

        mock_config.return_value = MagicMock(datacontainer_id="")

        runner = CliRunner()
        result = runner.invoke(app, ["remove", "data/test.txt", "-f"])

        assert result.exit_code == 1

    @patch("discovery.poll.cli_storage.load_project_config")
    @patch("discovery.poll.cli_storage.get_azure_username")
    @patch("discovery.poll.cli_storage.get_storage_account_name")
    @patch("discovery.poll.cli_storage.list_blobs_az")
    @patch("discovery.poll.cli_storage.remove_blobs_az")
    def test_remove_with_confirmation_yes(
        self,
        mock_remove_blobs: MagicMock,
        mock_list_blobs: MagicMock,
        mock_storage_name: MagicMock,
        mock_username: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test removing file with confirmation (user says yes)."""
        from typer.testing import CliRunner

        from discovery.poll.cli_storage import app

        # Setup mocks
        mock_config.return_value = MagicMock(
            datacontainer_id="test-container-id",
            subscription="test-subscription",
        )
        mock_username.return_value = "testuser"
        mock_storage_name.return_value = "teststorageaccount"
        mock_list_blobs.return_value = [
            {"name": "data/file.txt", "properties": {"contentLength": 1024}},
        ]
        mock_remove_blobs.return_value = (True, "")

        runner = CliRunner()
        result = runner.invoke(app, ["remove", "user:data/file.txt"], input="y\n")

        assert result.exit_code == 0
        assert "Removed" in result.output
        mock_remove_blobs.assert_called_once()

    @patch("discovery.poll.cli_storage.load_project_config")
    @patch("discovery.poll.cli_storage.get_azure_username")
    @patch("discovery.poll.cli_storage.get_storage_account_name")
    @patch("discovery.poll.cli_storage.list_blobs_az")
    @patch("discovery.poll.cli_storage.remove_blobs_az")
    def test_remove_with_confirmation_no(
        self,
        mock_remove_blobs: MagicMock,
        mock_list_blobs: MagicMock,
        mock_storage_name: MagicMock,
        mock_username: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test removing file with confirmation (user says no)."""
        from typer.testing import CliRunner

        from discovery.poll.cli_storage import app

        # Setup mocks
        mock_config.return_value = MagicMock(
            datacontainer_id="test-container-id",
            subscription="test-subscription",
        )
        mock_username.return_value = "testuser"
        mock_storage_name.return_value = "teststorageaccount"
        mock_list_blobs.return_value = [
            {"name": "data/file.txt", "properties": {"contentLength": 1024}},
        ]

        runner = CliRunner()
        result = runner.invoke(app, ["remove", "user:data/file.txt"], input="n\n")

        assert result.exit_code == 0
        assert "Aborted" in result.output
        mock_remove_blobs.assert_not_called()
