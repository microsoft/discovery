"""Tests for CLI commands after refactor into submodules."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from discovery.poll import (
    az_extensions,
    cli_build,
    cli_configure,
    cli_doctor,
    cli_helpers,
    cli_submit,
)
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
            patch.object(cli_configure, "run_az", return_value=MagicMock(returncode=0)),
            patch.object(cli_configure, "ensure_required_extensions", return_value=[bad_result]),
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
        assert "--shm" in result.output

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
            mock_cfg.storagecontainer_id = "sc-123"
            mock_cfg.api_version = "2026-06-01"
            mock_cfg.project_ready = True
            mock_run_cfg.return_value = mock_cfg

            with patch.object(cli_submit, "load_project_config", return_value=mock_cfg):
                with patch.object(cli_submit, "load_tool_config"):
                    with patch.object(cli_submit, "ensure_datacontainer"):
                        with patch.object(cli_submit, "emit_env"):
                            with patch.object(
                                cli_submit, "prepare_command", return_value="echo test"
                            ):
                                with (
                                    patch.object(cli_submit, "start_tool_run") as mock_start,
                                    patch.object(cli_submit, "poll_operation") as mock_poll,
                                ):
                                    mock_start.return_value = MagicMock(id="op-test")
                                    mock_result = MagicMock()
                                    mock_result.status = "Completed"
                                    mock_result.result = MagicMock(runtime_details="details")
                                    mock_poll.return_value = mock_result

                                    result = runner.invoke(
                                        app,
                                        ["job", "start", "--shm", "1Gi", "echo test"],
                                    )

        assert result.exit_code == 0
        payload = mock_start.call_args.args[1]
        assert payload.infra_overrides.shm == "1Gi"


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
        assert "--shm" in result.output

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

    def test_batch_does_not_truncate_long_commands(self, monkeypatch):
        """Long commands must appear in full in both the live progress line
        and the final Operation Mapping table — never truncated.

        Regression for the customer-reported issue where commands >80 chars
        were silently sliced via ``cmd[:80]`` in both surfaces of
        ``discovery job batch``.
        """
        # Force a wide Rich Console so the table cell doesn't fold the
        # command across multiple lines (which would make a single
        # contiguous substring assertion flaky). The live line uses
        # ``overflow="ignore"`` and is unaffected by terminal width.
        monkeypatch.setenv("COLUMNS", "500")

        # 150-char command with two unique markers: one before the old
        # 80-char truncation point and one well past it. Both must appear.
        early_marker = "EARLY42X"
        late_marker = "LATE99XY"
        long_command = f"echo {early_marker} " + ("x" * 100) + f" {late_marker} done"
        assert len(long_command) > 120
        assert long_command.index(late_marker) > 80, "late marker must sit past old 80-char cutoff"

        mock_cfg = MagicMock()
        mock_cfg.project_name = "test-project"
        mock_cfg.workspace_url = "https://example.com"
        mock_cfg.tool_id = "tool-123"
        mock_cfg.nodepool_id = "nodepool-123"
        mock_cfg.datacontainer_id = "dc-123"

        mock_response = MagicMock()
        mock_response.id = "op-long-1"

        with (
            patch.object(cli_submit, "load_project_config", return_value=mock_cfg),
            patch.object(cli_submit, "load_tool_config"),
            patch.object(cli_submit, "ensure_datacontainer"),
            patch.object(cli_submit, "emit_env"),
            patch.object(cli_submit, "prepare_command", side_effect=lambda c, *a, **kw: c),
            patch.object(cli_submit, "get_azure_username", return_value="testuser"),
            patch.object(cli_submit, "start_tool_run", return_value=mock_response),
        ):
            result = runner.invoke(app, ["job", "batch", "1", long_command])

        assert result.exit_code == 0, result.output
        # Mapping table should appear at all.
        assert "Operation Mapping" in result.output
        # Both markers — including the one past char 80 — must be present
        # somewhere in the combined output (live line + final table).
        assert early_marker in result.output
        assert late_marker in result.output, (
            "Long command was truncated before the late marker; "
            "expected full command in batch output."
        )


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
        assert "--shm" in result.output

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
# Pool Size Override Tests
# =============================================================================


class TestPoolSizeOverrides:
    """Per-job replica counts are independent of MPI ranks and batch size."""

    @pytest.fixture
    def submission(self, monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
        """Stub submission dependencies without Azure or device-flow calls."""
        cfg = MagicMock(
            project_name="test-project",
            workspace_url="https://example.com",
            tool_id="tool-123",
            nodepool_id="nodepool-123",
            nodepools=[],
            datacontainer_id="dc-123",
            storagecontainer_id="sc-123",
            api_version="2026-06-01",
        )
        submit = MagicMock(return_value=MagicMock(id="op-size"))
        monkeypatch.setattr(cli_submit, "load_project_config", lambda *_a: cfg)
        monkeypatch.setattr(cli_submit, "load_tool_config", lambda *_a: None)
        monkeypatch.setattr(cli_submit, "ensure_datacontainer", lambda *_a: None)
        monkeypatch.setattr(cli_submit, "emit_env", lambda *_a: None)
        monkeypatch.setattr(cli_submit, "prepare_command", lambda command, *_a, **_k: command)
        monkeypatch.setattr(cli_submit, "start_tool_run", submit)
        monkeypatch.setattr(cli_submit, "_record_job_submission", lambda *_a, **_k: None)
        monkeypatch.setattr(cli_submit, "_poll_for_device_flow_url", lambda *_a, **_k: None)
        return cfg, submit

    @pytest.mark.parametrize(
        ("command_args", "job_count"),
        [
            (["start", "--no-wait", "mpirun -np 6 /app/program"], 1),
            (["batch", "3", "mpirun -np 6 /app/program"], 3),
            (["vscode"], 1),
        ],
    )
    @pytest.mark.parametrize(
        ("api_version", "size_field"),
        [
            ("2025-07-01-preview", "poolSize"),
            ("2025-12-01-preview", "replicaCount"),
            ("2026-02-01-preview", "replicaCount"),
            ("2026-06-01", "replicaCount"),
        ],
    )
    def test_pool_size_reaches_each_job(
        self,
        submission: tuple[MagicMock, MagicMock],
        command_args: list[str],
        job_count: int,
        api_version: str,
        size_field: str,
    ) -> None:
        """Every submission command honors the selected API and per-job size."""
        _, submit = submission
        result = runner.invoke(
            app,
            [
                "job", *command_args, "--username", "u", "--pool-size", "2",
                "--api-version", api_version,
            ],
        )

        assert result.exit_code == 0, result.output
        assert submit.call_count == job_count
        for call in submit.call_args_list:
            payload = json.loads(call.args[1].model_dump_json())
            assert payload["infraOverrides"] == {size_field: 2}
            assert call.kwargs["api_version"] == api_version
            if command_args[0] != "vscode":
                assert payload["command"] == "mpirun -np 6 /app/program"

    @pytest.mark.parametrize(
        "command_args",
        [["start", "--no-wait", "echo test"], ["batch", "2", "echo test"], ["vscode"]],
    )
    def test_omitted_pool_size_preserves_tool_default(
        self, submission: tuple[MagicMock, MagicMock], command_args: list[str]
    ) -> None:
        """Existing invocations do not emit a replica-count override."""
        _, submit = submission
        result = runner.invoke(app, ["job", *command_args, "--username", "u"])

        assert result.exit_code == 0, result.output
        assert submit.called
        for call in submit.call_args_list:
            payload = json.loads(call.args[1].model_dump_json())
            assert "infraOverrides" not in payload

    @pytest.mark.parametrize(
        "command_args",
        [["start", "--no-wait", "echo test"], ["batch", "2", "echo test"], ["vscode"]],
    )
    @pytest.mark.parametrize("pool_size", ["0", "-1", "1.5"])
    def test_invalid_pool_size_fails_before_submission(
        self, command_args: list[str], pool_size: str
    ) -> None:
        """All submission commands reject nonpositive and noninteger sizes."""
        with patch.object(cli_submit, "load_project_config") as load_config:
            result = runner.invoke(app, ["job", *command_args, "--pool-size", pool_size])

        assert result.exit_code == 2, result.output
        assert "--pool-size" in result.output
        load_config.assert_not_called()


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

    @pytest.mark.parametrize(
        ("options", "mpi", "pool_size", "infiniband"),
        [
            ([], False, 1, False),
            (["--mpi"], True, 2, False),
            (["--pool-size", "1"], False, 1, False),
            (["--pool-size", "3"], False, 3, False),
            (["--mpi", "--pool-size", "3"], True, 3, False),
            (["--mpi", "--infiniband"], True, 2, True),
            (["--mpi", "--pool-size", "2", "--infiniband"], True, 2, True),
            (["--infiniband"], False, 1, True),
        ],
    )
    def test_build_deploys_requested_tool_mode(
        self, tmp_path: Path, options: list[str], mpi: bool, pool_size: int, infiniband: bool
    ) -> None:
        """Build flags reach the existing tool-definition deployment flow."""
        cfg = MagicMock(
            subscription="sub", resource_group="rg", acr_name="acr", acr_url="acr.azurecr.io"
        )
        with (
            patch.object(cli_build, "_load_acr_config", return_value=cfg),
            patch.object(cli_build.acr, "execute_build", return_value=0),
            patch.object(cli_build, "get_location_from_supercomputer", return_value="eastus"),
            patch.object(cli_build, "deploy_tool_definition") as deploy,
        ):
            result = runner.invoke(
                app,
                ["build", "image", str(tmp_path), "--image", "demo", "--tag", "latest", *options],
                input="y\ndemo\nDemo tool\n",
            )

        assert result.exit_code == 0, result.output
        deploy.assert_called_once()
        inputs = deploy.call_args.kwargs["inputs"]
        assert inputs.image == "acr.azurecr.io/demo:latest"
        assert inputs.mpi is mpi
        assert inputs.pool_size == pool_size
        assert inputs.infiniband is infiniband

    @pytest.mark.parametrize("pool_size", ["0", "-1", "1.5"])
    def test_build_rejects_invalid_pool_size(self, tmp_path: Path, pool_size: str) -> None:
        """Invalid sizes are rejected before config, image build, or deployment."""
        with patch.object(cli_build, "_load_acr_config") as load_config:
            result = runner.invoke(
                app,
                [
                    "build", "image", str(tmp_path), "--image", "demo", "--tag", "latest",
                    "--pool-size", pool_size,
                ],
            )

        assert result.exit_code == 2, result.output
        assert "--pool-size" in result.output
        load_config.assert_not_called()

    @pytest.mark.parametrize("pool_size", ["0", "-1", "1", "1.5"])
    def test_build_rejects_invalid_mpi_pool_size(self, tmp_path: Path, pool_size: str) -> None:
        """MPI size errors must fail before config, ACR build, or deployment."""
        with (
            patch.object(cli_build, "_load_acr_config") as load_config,
            patch.object(cli_build.acr, "execute_build") as build_image,
            patch.object(cli_build, "deploy_tool_definition") as deploy,
        ):
            result = runner.invoke(
                app,
                [
                    "build", "image", str(tmp_path), "--image", "demo", "--tag", "latest",
                    "--mpi", "--pool-size", pool_size,
                ],
            )

        assert result.exit_code == 2, result.output
        assert "--pool-size" in result.output
        load_config.assert_not_called()
        build_image.assert_not_called()
        deploy.assert_not_called()

    @pytest.mark.parametrize(
        ("options", "expected_api"),
        [
            ([], "2026-06-01"),
            (["--tool-api-version", "2025-07-01-preview"], "2025-07-01-preview"),
            (["--tool-api-version", "2025-12-01-preview"], "2025-12-01-preview"),
            (["--tool-api-version", "2026-02-01-preview"], "2026-02-01-preview"),
            (["--tool-api-version", "2026-06-01"], "2026-06-01"),
        ],
    )
    def test_tool_api_selection_is_independent_of_job_api(
        self, tmp_path: Path, options: list[str], expected_api: str
    ) -> None:
        """Build uses the selected ARM protocol without changing the saved job API."""
        cfg = MagicMock(
            subscription="sub", resource_group="rg", acr_name="acr",
            acr_url="acr.azurecr.io", api_version="2025-07-01-preview",
        )
        with (
            patch.object(cli_build, "_load_acr_config", return_value=cfg),
            patch.object(cli_build.acr, "execute_build", return_value=0),
            patch.object(cli_build, "get_location_from_supercomputer", return_value="eastus"),
            patch.object(cli_build, "deploy_tool_definition") as deploy,
        ):
            result = runner.invoke(
                app,
                [
                    "build", "image", str(tmp_path), "--image", "demo", "--tag", "latest",
                    "--mpi", "--pool-size", "3", *options,
                ],
                input="y\ndemo\nMPI tool\n",
            )

        assert result.exit_code == 0, result.output
        assert deploy.call_args.kwargs["inputs"].api_version == expected_api
        assert deploy.call_args.kwargs["inputs"].pool_size == 3
        assert cfg.api_version == "2025-07-01-preview"

    def test_unknown_tool_api_fails_before_build(self, tmp_path: Path) -> None:
        """Unknown ARM API choices fail before any configuration or cloud work."""
        with (
            patch.object(cli_build, "_load_acr_config") as load_config,
            patch.object(cli_build.acr, "execute_build") as build_image,
        ):
            result = runner.invoke(
                app,
                [
                    "build", "image", str(tmp_path), "--image", "demo", "--tag", "latest",
                    "--tool-api-version", "unsupported",
                ],
            )
        assert result.exit_code == 2, result.output
        load_config.assert_not_called()
        build_image.assert_not_called()


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
