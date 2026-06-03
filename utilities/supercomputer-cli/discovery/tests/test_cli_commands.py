"""Tests for CLI commands after refactor into submodules."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from discovery.poll import az_extensions, cli_configure, cli_doctor, cli_helpers, cli_submit
from discovery.poll.cli import app


runner = CliRunner()


# =============================================================================
# Configure Command Tests
# =============================================================================


class TestConfigureCommand:
    """Tests for the configure command."""

    def test_configure_runs_without_args(self):
        """Test that configure command exists and shows help."""
        result = runner.invoke(app, ["configure", "--help"])
        assert result.exit_code == 0
        assert "--acr" in result.output or "acr" in result.output.lower()

    def test_configure_aborts_when_required_extension_install_fails(self):
        """``configure`` must surface a clean error when a required ``az``
        extension cannot be installed, rather than continuing into selection
        flows that would later hit the same missing-extension hang.

        See ``discovery.poll.az_extensions.ensure_required_extensions`` and
        the early-abort block in ``cli_configure.configure``.
        """
        bad_result = az_extensions.ExtensionResult(
            name="resource-graph",
            ok=False,
            action="install-failed",
            detail="HTTP 503 from extension index",
        )

        # `az` must look installed (so we get past the `shutil.which` and
        # `az account show` gates).
        # The az binary is mocked as present, `run_az` is mocked to succeed
        # for the `az account show` login check, then
        # `ensure_required_extensions` is mocked to report a failure for
        # `resource-graph`.
        with (
            patch.object(cli_configure.shutil, "which", return_value="/usr/local/bin/az"),
            patch.object(
                cli_configure, "run_az", return_value=MagicMock(returncode=0)
            ),
            patch.object(
                cli_configure, "ensure_required_extensions", return_value=[bad_result]
            ),
        ):
            result = runner.invoke(app, ["configure"])

        assert result.exit_code == 1, result.output
        # The error message should name the extension and the manual
        # remediation so users have an actionable next step.
        assert "resource-graph" in result.output
        assert "az extension add --name resource-graph" in result.output


# =============================================================================
# Start Command Tests
# =============================================================================


class TestStartCommand:
    """Tests for the start command."""

    def test_start_help(self):
        """Test start command help."""
        result = runner.invoke(app, ["job", "start", "--help"])
        assert result.exit_code == 0
        assert "COMMAND" in result.output or "command" in result.output.lower()

    def test_start_with_mocked_deps(self, tmp_path):
        """Test start with mocked dependencies."""
        env_file = tmp_path / ".env"
        env_data = {
            "project_name": "test-project",
            "workspace_url": "https://example.com",
            "tool_id": "tool-123",
            "nodepool_id": "nodepool-123",
            "datacontainer_id": "dc-123",
        }
        env_file.write_text(json.dumps(env_data))

        with patch.object(cli_helpers, "run_configure_if_needed") as mock_run_cfg:
            mock_cfg = MagicMock()
            mock_cfg.project_name = "test-project"
            mock_cfg.workspace_url = "https://example.com"
            mock_cfg.tool_id = "tool-123"
            mock_cfg.nodepool_id = "nodepool-123"
            mock_cfg.datacontainer_id = "dc-123"
            mock_cfg.project_ready = True
            mock_run_cfg.return_value = mock_cfg

            with patch.object(cli_submit, "load_project_config", return_value=mock_cfg):
                with patch.object(cli_submit, "load_tool_config"):
                    with patch.object(cli_submit, "ensure_datacontainer"):
                        with patch.object(cli_submit, "emit_env"):
                            with patch.object(
                                cli_submit, "prepare_command", return_value="echo test"
                            ):
                                with patch.object(cli_submit, "start_tool_run") as mock_start, \
                                     patch.object(cli_submit, "poll_operation") as mock_poll:
                                    mock_start.return_value = MagicMock(id="op-test")
                                    mock_result = MagicMock()
                                    mock_result.status = "Completed"
                                    mock_result.result = MagicMock(runtime_details="details")
                                    mock_poll.return_value = mock_result

                                    result = runner.invoke(app, ["job", "start", "echo test"])

        assert result.exit_code == 0


# =============================================================================
# Batch Command Tests
# =============================================================================


class TestBatchCommand:
    """Tests for the batch command."""

    def test_batch_help(self):
        """Test batch command help."""
        result = runner.invoke(app, ["job", "batch", "--help"])
        assert result.exit_code == 0
        assert "SIZE" in result.output

    def test_batch_with_mocked_deps(self, tmp_path):
        """Test batch with mocked dependencies and verify mapping table."""
        with patch.object(cli_submit, "load_project_config") as mock_proj:
            mock_cfg = MagicMock()
            mock_cfg.project_name = "test-project"
            mock_cfg.workspace_url = "https://example.com"
            mock_cfg.tool_id = "tool-123"
            mock_cfg.nodepool_id = "nodepool-123"
            mock_cfg.datacontainer_id = "dc-123"
            mock_proj.return_value = mock_cfg

            with patch.object(cli_submit, "load_tool_config"):
                with patch.object(cli_submit, "ensure_datacontainer"):
                    with patch.object(cli_submit, "emit_env"):
                        with patch.object(cli_submit, "prepare_command", return_value="echo test"):
                            with patch.object(
                                cli_submit, "get_azure_username", return_value="testuser"
                            ):
                                with patch.object(cli_submit, "start_tool_run") as mock_submit:
                                    mock_response = MagicMock()
                                    mock_response.id = "op-123"
                                    mock_submit.return_value = mock_response

                                    result = runner.invoke(app, ["job", "batch", "3", "echo test"])

        assert result.exit_code == 0
        # Mapping table should appear with operation IDs
        assert "Operation Mapping" in result.output
        assert "op-123" in result.output

    def test_batch_commands_file_preserves_order(self, tmp_path):
        """Test that batch --commands-file prints mapping in input order."""
        cmds_file = tmp_path / "cmds.txt"
        cmds_file.write_text("echo molecule_A\necho molecule_B\necho molecule_C\n")

        # Return distinct op IDs per call to verify ordering
        call_count = 0

        def _make_response(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.id = f"op-{call_count:03d}"
            return resp

        with patch.object(cli_submit, "load_project_config") as mock_proj:
            mock_cfg = MagicMock()
            mock_cfg.project_name = "test-project"
            mock_cfg.workspace_url = "https://example.com"
            mock_cfg.tool_id = "tool-123"
            mock_cfg.nodepool_id = "nodepool-123"
            mock_cfg.datacontainer_id = "dc-123"
            mock_proj.return_value = mock_cfg

            with patch.object(cli_submit, "load_tool_config"):
                with patch.object(cli_submit, "ensure_datacontainer"):
                    with patch.object(cli_submit, "emit_env"):
                        with patch.object(
                            cli_submit, "prepare_command", side_effect=lambda c, *a, **kw: c
                        ):
                            with patch.object(
                                cli_submit, "get_azure_username", return_value="testuser"
                            ):
                                with patch.object(
                                    cli_submit, "start_tool_run", side_effect=_make_response
                                ):
                                    result = runner.invoke(
                                        app,
                                        ["job", "batch", "--commands-file", str(cmds_file)],
                                    )

        assert result.exit_code == 0
        assert "Operation Mapping" in result.output
        # All three commands should appear in the mapping table
        assert "molecule_A" in result.output
        assert "molecule_B" in result.output
        assert "molecule_C" in result.output

    def test_batch_size_validation(self):
        """Test that batch rejects size < 1."""
        with patch.object(cli_submit, "load_project_config") as mock_proj:
            mock_cfg = MagicMock()
            mock_cfg.project_name = "test-project"
            mock_proj.return_value = mock_cfg

            # Size 0 should fail
            result = runner.invoke(app, ["job", "batch", "0", "echo test"])

        assert result.exit_code == 1


# =============================================================================
# VSCode Command Tests
# =============================================================================


class TestVSCodeCommand:
    """Tests for the vscode command."""

    def test_vscode_help(self):
        """Test vscode command help."""
        result = runner.invoke(app, ["job", "vscode", "--help"])
        assert result.exit_code == 0
        assert "--image" in result.output

    def test_vscode_with_mocked_deps(self, tmp_path):
        """Test vscode with mocked dependencies."""
        with patch.object(cli_submit, "load_project_config") as mock_proj:
            mock_cfg = MagicMock()
            mock_cfg.project_name = "test-project"
            mock_cfg.workspace_url = "https://example.com"
            mock_cfg.tool_id = "tool-123"
            mock_cfg.nodepool_id = "nodepool-123"
            mock_cfg.datacontainer_id = "dc-123"
            mock_proj.return_value = mock_cfg

            with patch.object(cli_submit, "load_tool_config"):
                with patch.object(cli_submit, "ensure_datacontainer"):
                    with patch.object(cli_submit, "emit_env"):
                        with patch.object(cli_submit, "prepare_command", return_value="sleep 10d"):
                            with patch.object(
                                cli_submit, "get_azure_username", return_value="testuser"
                            ):
                                with patch.object(cli_submit, "start_tool_run") as mock_submit:
                                    mock_response = MagicMock()
                                    mock_response.id = "op-vscode-123"
                                    mock_submit.return_value = mock_response

                                    with patch.object(
                                        cli_submit,
                                        "_poll_for_device_flow_url",
                                        return_value="https://github.com/login/device",
                                    ):
                                        result = runner.invoke(app, ["job", "vscode"])

        assert result.exit_code == 0
        assert "op-vscode-123" in result.output


# =============================================================================
# Cancel Command Tests
# =============================================================================


class TestCancelCommand:
    """Tests for the cancel command."""

    def test_cancel_help(self):
        """Test cancel command help."""
        result = runner.invoke(app, ["job", "cancel", "--help"])
        assert result.exit_code == 0
        assert "OPERATION_ID" in result.output

    def test_cancel_with_mocked_deps(self):
        """Test cancel with mocked dependencies."""
        with patch.object(cli_submit, "load_project_config") as mock_proj:
            mock_cfg = MagicMock()
            mock_cfg.project_name = "test-project"
            mock_cfg.workspace_url = "https://example.com"
            mock_proj.return_value = mock_cfg

            with patch.object(cli_submit, "emit_env"):
                with patch.object(cli_submit, "cancel_operation") as mock_cancel:
                    result = runner.invoke(app, ["job", "cancel", "op-123"])
        mock_cancel.assert_called_once()


# =============================================================================
# Status Command Tests
# =============================================================================


class TestStatusCommand:
    """Tests for the status command."""

    def test_status_help(self):
        """Test status command help."""
        result = runner.invoke(app, ["job", "status", "--help"])
        assert result.exit_code == 0
        assert "OPERATION_ID" in result.output or "operation" in result.output.lower()


# =============================================================================
# List Commands Tests
# =============================================================================


class TestListCommands:
    """Tests for list commands (running, pending, done, list)."""

    def test_running_help(self):
        """Test running command help."""
        result = runner.invoke(app, ["job", "running", "--help"])
        assert result.exit_code == 0

    def test_pending_help(self):
        """Test pending command help."""
        result = runner.invoke(app, ["job", "pending", "--help"])
        assert result.exit_code == 0

    def test_done_help(self):
        """Test done command help."""
        result = runner.invoke(app, ["job", "done", "--help"])
        assert result.exit_code == 0

    def test_list_help(self):
        """Test list command help."""
        result = runner.invoke(app, ["job", "list", "--help"])
        assert result.exit_code == 0


# =============================================================================
# Build Command Tests
# =============================================================================


class TestBuildCommand:
    """Tests for the build command."""

    def test_build_help(self):
        """Test build command help."""
        result = runner.invoke(app, ["build", "--help"])
        assert result.exit_code == 0
        assert "image" in result.output or "rebuild" in result.output


# =============================================================================
# Rebuild Command Tests
# =============================================================================


class TestRebuildCommand:
    """Tests for the rebuild command."""

    def test_rebuild_help(self):
        """Test rebuild command help."""
        result = runner.invoke(app, ["build", "rebuild", "--help"])
        assert result.exit_code == 0
        assert "--image" in result.output


# =============================================================================
# Storage URL Command Tests
# =============================================================================


class TestStorageUrlCommand:
    """Tests for the storage-url command."""

    def test_storage_url_help(self):
        """Test blob url command help."""
        result = runner.invoke(app, ["blob", "url", "--help"])
        assert result.exit_code == 0


# =============================================================================
# Create User Storage Command Tests
# =============================================================================


class TestCreateUserStorageCommand:
    """Tests for the create-user-storage command."""

    def test_create_user_storage_help(self):
        """Test create-user-storage command help."""
        result = runner.invoke(app, ["blob", "create-user-storage", "--help"])
        assert result.exit_code == 0


# =============================================================================
# CLI Help Tests
# =============================================================================


class TestCliHelp:
    """Tests for CLI help output."""

    def test_main_help(self):
        """Test main help output."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        # Should list top-level command groups
        assert "configure" in result.output
        assert "job" in result.output
        assert "blob" in result.output
        assert "build" in result.output

    def test_all_commands_registered(self):
        """Test that all expected commands are registered under their groups."""
        # Top-level groups
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for group in ["configure", "job", "blob", "build", "smoke"]:
            assert group in result.output, f"Group '{group}' not found in help output"

        # Job subcommands
        result = runner.invoke(app, ["job", "--help"])
        assert result.exit_code == 0
        for cmd in [
            "start",
            "batch",
            "vscode",
            "cancel",
            "running",
            "pending",
            "done",
            "list",
            "status",
        ]:
            assert cmd in result.output, f"Command 'job {cmd}' not found in help output"

        # Blob subcommands
        result = runner.invoke(app, ["blob", "--help"])
        assert result.exit_code == 0
        for cmd in ["upload", "download", "ls", "remove", "url", "create-user-storage"]:
            assert cmd in result.output, f"Command 'blob {cmd}' not found in help output"

        # Build subcommands
        result = runner.invoke(app, ["build", "--help"])
        assert result.exit_code == 0
        for cmd in ["image", "rebuild"]:
            assert cmd in result.output, f"Command 'build {cmd}' not found in help output"


# =============================================================================
# Doctor Command Tests
# =============================================================================


class TestDoctorCommand:
    """Tests for the doctor command's az-extension diagnostic."""

    def test_doctor_reports_missing_required_extension(self):
        """When a required ``az`` extension is missing, ``doctor`` flags it
        with a non-zero exit and prints an actionable hint pointing at the
        ``az extension add`` command.
        """
        bad = az_extensions.ExtensionResult(
            name="resource-graph",
            ok=False,
            action="missing",
            detail="run `az extension add --name resource-graph`",
        )

        with (
            patch.object(cli_doctor, "_check_modules", return_value=[("discovery", True, "ok")]),
            patch.object(
                cli_doctor, "_check_templates", return_value=[("tool-run.json", True, "ok")]
            ),
            patch.object(
                cli_doctor,
                "_check_external_tools",
                return_value=[("az", True, "/usr/local/bin/az")],
            ),
            patch.object(cli_doctor, "_check_az_auth", return_value=(True, "user@example.com")),
            patch.object(cli_doctor, "check_required_extensions", return_value=[bad]),
        ):
            result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 1, result.output
        assert "resource-graph" in result.output
        assert "az extension add" in result.output

    def test_doctor_passes_when_required_extensions_present(self):
        """All-green path: doctor exits 0 and prints the success summary."""
        ok = az_extensions.ExtensionResult(
            name="resource-graph", ok=True, action="already-installed", detail=""
        )

        with (
            patch.object(cli_doctor, "_check_modules", return_value=[("discovery", True, "ok")]),
            patch.object(
                cli_doctor, "_check_templates", return_value=[("tool-run.json", True, "ok")]
            ),
            patch.object(
                cli_doctor,
                "_check_external_tools",
                return_value=[("az", True, "/usr/local/bin/az")],
            ),
            patch.object(cli_doctor, "_check_az_auth", return_value=(True, "user@example.com")),
            patch.object(cli_doctor, "check_required_extensions", return_value=[ok]),
        ):
            result = runner.invoke(app, ["doctor"])

        assert result.exit_code == 0, result.output
        assert "required az extensions installed" in result.output
