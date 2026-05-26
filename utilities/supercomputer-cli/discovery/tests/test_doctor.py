"""Tests for the ``discovery doctor`` command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from discovery.poll.cli import app
from discovery.poll.cli_doctor import (
    _check_az_auth,
    _check_external_tools,
    _check_modules,
    _check_templates,
)


runner = CliRunner()


class TestCheckModules:
    def test_all_expected_modules_importable(self) -> None:
        """All expected modules should be importable in a working installation."""
        results = _check_modules()
        failed = [(name, detail) for name, ok, detail in results if not ok]
        assert not failed, f"Failed to import: {failed}"
        assert len(results) >= 30

    def test_detects_missing_module(self) -> None:
        """Should report failure for a module that cannot be imported."""
        with patch(
            "discovery.poll.cli_doctor._EXPECTED_MODULES",
            ["discovery", "discovery.nonexistent_module_xyz"],
        ):
            results = _check_modules()
        assert results[0][1] is True  # discovery OK
        assert results[1][1] is False  # nonexistent fails


class TestCheckTemplates:
    def test_all_expected_templates_valid(self) -> None:
        """All expected template files should exist and be valid JSON."""
        results = _check_templates()
        failed = [(name, detail) for name, ok, detail in results if not ok]
        assert not failed, f"Failed templates: {failed}"
        assert len(results) >= 8


class TestCheckExternalTools:
    def test_reports_tool_presence(self) -> None:
        results = _check_external_tools()
        tool_names = [name for name, _, _ in results]
        assert "az" in tool_names
        assert "azcopy" in tool_names

    def test_reports_missing_tool(self) -> None:
        with patch("discovery.poll.cli_doctor.shutil.which", return_value=None):
            results = _check_external_tools()
        for _, ok, detail in results:
            assert not ok
            assert "not found" in detail


class TestCheckAzAuth:
    def test_authenticated(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "user@example.com\n"
        with patch("discovery.poll.cli_doctor.subprocess.run", return_value=mock_result):
            ok, detail = _check_az_auth()
        assert ok
        assert detail == "user@example.com"

    def test_not_authenticated(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Please run 'az login'"
        with patch("discovery.poll.cli_doctor.subprocess.run", return_value=mock_result):
            ok, _detail = _check_az_auth()
        assert not ok

    def test_az_not_installed(self) -> None:
        with patch(
            "discovery.poll.cli_doctor.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            ok, detail = _check_az_auth()
        assert not ok
        assert "not installed" in detail


class TestDoctorCLI:
    def test_doctor_runs(self) -> None:
        """The doctor command should execute without crashing."""
        result = runner.invoke(app, ["doctor"])
        assert "Discovery CLI" in result.output
        assert "Version:" in result.output

    def test_version_flag(self) -> None:
        """--version should print version and exit."""
        result = runner.invoke(app, ["--version"])
        assert "discovery" in result.output
        assert result.exit_code == 0
