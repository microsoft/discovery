"""Tests focused on internal CLI helper utilities."""

from __future__ import annotations

from pathlib import Path

import pytest
import json

from discovery.poll import cli_helpers
from discovery.poll.models.config import EnvConfig
from discovery.poll.vscode_layer import WRAPPER_TARGET_PATH


def _write_env(tmp_path: Path) -> EnvConfig:
    env = EnvConfig(path=tmp_path / ".env")
    env.project_id = "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Discovery/workspaces/ws/projects/proj"
    env.workspace_resource_id = (
        "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Discovery/workspaces/ws"
    )
    env.nodepool_id = "nodepool-1"
    env.tool_id = "tool-1"
    env.acr_name = "acr-1"
    env.workspace_url = "https://ws"
    env.path.write_text(env.model_dump_json(by_alias=True), encoding="utf-8")
    return env


def _clone_env(env: EnvConfig, tmp_path: Path) -> EnvConfig:
    target = EnvConfig(path=tmp_path / "clone.env")
    for field in (
        "project_id",
        "workspace_resource_id",
        "nodepool_id",
        "tool_id",
        "acr_name",
        "workspace_url",
    ):
        setattr(target, field, getattr(env, field))
    return target


def test_prepare_command_no_vscode(tmp_path) -> None:
    env = _clone_env(_write_env(tmp_path), tmp_path)
    result = cli_helpers.prepare_command("echo hi", env, vscode=False, additional_ports=[])
    assert result == "echo hi"


def test_prepare_command_vscode(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _clone_env(_write_env(tmp_path), tmp_path)

    result = cli_helpers.prepare_command(
        "echo hi", env, vscode=True, additional_ports=[], tunnel_name="my-tunnel"
    )
    assert WRAPPER_TARGET_PATH in result
    assert "echo hi" in result
    assert "--name" in result
    assert "my-tunnel" in result


def test_prepare_command_vscode_requires_tunnel_name(tmp_path) -> None:
    """Test that vscode=True without tunnel_name raises ValueError."""
    env = _clone_env(_write_env(tmp_path), tmp_path)

    with pytest.raises(ValueError, match="--tunnel-name is required"):
        cli_helpers.prepare_command("echo hi", env, vscode=True, additional_ports=[])


def test_prepare_command_named_tunnel(tmp_path) -> None:
    """Test that --tunnel-name uses named mode."""
    env = _clone_env(_write_env(tmp_path), tmp_path)

    result = cli_helpers.prepare_command(
        "echo hi", env, vscode=True, additional_ports=[], tunnel_name="my-gpu-box"
    )
    assert WRAPPER_TARGET_PATH in result
    assert "--name" in result
    assert "my-gpu-box" in result
    assert "echo hi" in result


def test_get_azure_username_cli_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Azure username retrieval when CLI fails."""

    def mock_run(*args, **kwargs):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "ERROR: Please run 'az login'"

        return Result()

    # Patch at the module level to avoid test pollution
    import discovery.poll.cli_helpers as helpers_module
    monkeypatch.setattr(helpers_module.subprocess, "run", mock_run)
    # Suppress logging which may fail with closed file handles after CliRunner tests
    monkeypatch.setattr(helpers_module, "error", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="Could not determine Azure username"):
        cli_helpers.get_azure_username()


def test_get_azure_username_empty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Azure username retrieval when output is empty."""

    def mock_run(*args, **kwargs):
        class Result:
            returncode = 0
            stdout = "  \n"
            stderr = ""

        return Result()

    import discovery.poll.cli_helpers as helpers_module
    monkeypatch.setattr(helpers_module.subprocess, "run", mock_run)
    with pytest.raises(RuntimeError, match="Azure username is empty"):
        cli_helpers.get_azure_username()


def test_get_azure_username_cli_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Azure username retrieval when Azure CLI is not installed."""

    def mock_run(*args, **kwargs):
        msg = "az command not found"
        raise OSError(msg)

    import discovery.poll.cli_helpers as helpers_module
    monkeypatch.setattr(helpers_module.subprocess, "run", mock_run)
    # Suppress logging which may fail with closed file handles after CliRunner tests
    monkeypatch.setattr(helpers_module, "error", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="Azure CLI not found"):
        cli_helpers.get_azure_username()


class TestSanitizeUsername:
    """Tests for sanitize_username 24-char cap."""

    def test_short_plain_username_unchanged(self) -> None:
        assert cli_helpers.sanitize_username("alice") == "alice"

    def test_plain_username_at_limit_unchanged(self) -> None:
        name = "a" * 24
        result = cli_helpers.sanitize_username(name)
        assert result == name
        assert len(result) == 24

    def test_plain_username_over_limit_truncated_with_hash(self) -> None:
        name = "a" * 25
        result = cli_helpers.sanitize_username(name)
        assert len(result) == 24
        assert "-" in result

    def test_plain_username_preserves_uniqueness(self) -> None:
        """Different long usernames produce different hashes."""
        r1 = cli_helpers.sanitize_username("a" * 30)
        r2 = cli_helpers.sanitize_username("a" * 29 + "b")
        assert r1 != r2
        assert len(r1) <= 24
        assert len(r2) <= 24

    def test_email_username_short_local(self) -> None:
        result = cli_helpers.sanitize_username("ab@example.com")
        assert result.startswith("ab-")
        assert len(result) <= 24

    def test_email_short_local_uses_domain_hash(self) -> None:
        """Short emails use domain-only hash for backward compatibility."""
        import hashlib

        domain = "example.com"
        expected_hash = hashlib.sha256(domain.encode()).hexdigest()[:8]
        result = cli_helpers.sanitize_username(f"user@{domain}")
        assert result == f"user-{expected_hash}"

    def test_email_long_local_uses_full_username_hash(self) -> None:
        """Long emails use full-username hash so truncated chars stay unique."""
        import hashlib

        email = "abcdefghijklmnopqrstuvwxyz@example.com"
        expected_hash = hashlib.sha256(email.encode()).hexdigest()[:8]
        result = cli_helpers.sanitize_username(email)
        assert result.endswith(expected_hash)
        assert len(result) == 24

    def test_email_different_domains_different_hashes(self) -> None:
        r1 = cli_helpers.sanitize_username("user@domainA.com")
        r2 = cli_helpers.sanitize_username("user@domainB.com")
        assert r1 != r2

    def test_email_no_alphanumeric_local_raises(self) -> None:
        with pytest.raises(ValueError, match="no alphanumeric"):
            cli_helpers.sanitize_username("@@@..@domain.com")

    def test_plain_no_valid_chars_raises(self) -> None:
        with pytest.raises(ValueError, match="no valid characters"):
            cli_helpers.sanitize_username("!!!")

    def test_plain_hyphens_preserved(self) -> None:
        assert cli_helpers.sanitize_username("my-user") == "my-user"

    def test_result_always_lowercase(self) -> None:
        assert cli_helpers.sanitize_username("Alice") == "alice"
        result = cli_helpers.sanitize_username("ALICE@EXAMPLE.COM")
        assert result == result.lower()


def test_get_azure_username_no_alphanumeric(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Azure username retrieval when username has no alphanumeric characters."""

    def mock_run(*args, **kwargs):
        class Result:
            returncode = 0
            stdout = "@@@...___\n"
            stderr = ""

        return Result()

    import discovery.poll.cli_helpers as helpers_module
    monkeypatch.setattr(helpers_module.subprocess, "run", mock_run)
    with pytest.raises(RuntimeError, match="contains no alphanumeric characters"):
        cli_helpers.get_azure_username()


class TestLoadProjectConfigReanchorsAndSaves:
    def test_reanchors_stale_path_from_json(self, tmp_path: Path) -> None:
        """run_configure_if_needed should re-anchor env_cfg.path to env_file."""
        # Write a config whose embedded `path` points somewhere stale.
        stale_path = tmp_path / "stale" / ".discovery-sc-config"
        stale_path.parent.mkdir(parents=True)
        real_path = tmp_path / "real.config"

        # Use a ready config so load_project_config does not prompt
        env = EnvConfig(path=stale_path)
        env.project_id = (
            "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Discovery/workspaces/ws/projects/p"
        )
        env.workspace_resource_id = (
            "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Discovery/workspaces/ws"
        )
        env.nodepool_id = "nodepool-1"
        real_path.write_text(env.model_dump_json(by_alias=True), encoding="utf-8")

        loaded = cli_helpers.run_configure_if_needed(real_path)
        assert loaded.path == real_path

    def test_load_project_config_saves_after_selection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When project is not ready, select runs and the result is persisted."""
        env_file = tmp_path / ".discovery-sc-config"
        # Non-ready config: no nodepool yet
        env = EnvConfig(path=env_file)
        env.project_id = (
            "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Discovery/workspaces/ws/projects/p"
        )
        env_file.write_text(env.model_dump_json(by_alias=True), encoding="utf-8")

        def fake_select(env_cfg):  # type: ignore[no-untyped-def]
            env_cfg.workspace_resource_id = (
                "/subscriptions/1/resourceGroups/rg/providers/Microsoft.Discovery/workspaces/ws"
            )
            env_cfg.nodepool_id = "nodepool-X"

        monkeypatch.setattr(cli_helpers, "select_project_and_related", fake_select)

        result = cli_helpers.load_project_config(env_file)
        assert result.nodepool_id == "nodepool-X"
        # Verify persistence — reloading must show the new nodepool_id
        reloaded = EnvConfig.model_validate_json(env_file.read_text(encoding="utf-8"))
        assert reloaded.nodepool_id == "nodepool-X"


# --- _load_with_migration -------------------------------------------------

class TestLoadWithMigration:
    def test_strips_unknown_root_field_and_rewrites(self, tmp_path: Path) -> None:
        """A config with a field that's no longer in the schema should load
        cleanly after one migration pass and be rewritten without that field."""
        env_file = tmp_path / ".discovery-sc-config"
        env_file.write_text(
            json.dumps(
                {
                    "path": str(env_file),
                    "DISCOVERY_API_VERSION": "2025-12-01-preview",
                    # Removed-in-current-schema field that should be silently scrubbed:
                    "DISCOVERY_SUPERCOMPUTER_ID": "/sc/should-not-trip-validation",
                }
            ),
            encoding="utf-8",
        )

        env_cfg = cli_helpers._load_with_migration(env_file)
        assert env_cfg.api_version == "2025-12-01-preview"

        # Persisted form must not contain the dropped key any more.
        rewritten = json.loads(env_file.read_text(encoding="utf-8"))
        assert "DISCOVERY_SUPERCOMPUTER_ID" not in rewritten

    def test_strips_unknown_nodepool_field(self, tmp_path: Path) -> None:
        """Removed fields nested in cached nodepools also get scrubbed."""
        env_file = tmp_path / ".discovery-sc-config"
        env_file.write_text(
            json.dumps(
                {
                    "path": str(env_file),
                    "nodepools": [
                        {
                            "id": "/x/np1",
                            "name": "np1",
                            # Field removed in the current schema:
                            "scratch_dc_region": "uksouth",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        env_cfg = cli_helpers._load_with_migration(env_file)
        assert env_cfg.nodepools[0].name == "np1"
        rewritten = json.loads(env_file.read_text(encoding="utf-8"))
        assert "scratch_dc_region" not in rewritten["nodepools"][0]

    def test_re_raises_on_real_validation_error(self, tmp_path: Path) -> None:
        """Validation errors that aren't caused by extra fields must still raise."""
        import pydantic

        env_file = tmp_path / ".discovery-sc-config"
        env_file.write_text(
            json.dumps(
                {
                    "path": str(env_file),
                    "nodepools": [{"name": "missing-id-is-required"}],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(pydantic.ValidationError):
            cli_helpers._load_with_migration(env_file)
