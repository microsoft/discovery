"""Tests for the ``discovery update`` Typer command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from discovery.common import auto_update
from discovery.common.auto_update import maybe_notify
from discovery.poll.cli import app


runner = CliRunner()


@pytest.fixture
def fake_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(
        "discovery.common.auto_update.get_home_dir",
        lambda: tmp_path,
    )
    return tmp_path


@pytest.fixture
def installed_build(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(
        "discovery._version.get_build_commit", lambda: "deadbeef"
    )
    monkeypatch.setattr(
        "discovery.common.auto_update.get_build_commit", lambda: "deadbeef"
    )
    monkeypatch.setattr(
        "discovery.poll.cli_update.get_build_commit", lambda: "deadbeef"
    )
    return "deadbeef"


class TestUpdateCommandFlags:
    def test_disable_persists_flag(
        self, fake_home: Path, installed_build: str
    ) -> None:
        result = runner.invoke(app, ["update", "--disable"])
        assert result.exit_code == 0
        assert auto_update.load_cache().disabled is True

    def test_enable_clears_flag(
        self, fake_home: Path, installed_build: str
    ) -> None:
        auto_update.set_disabled(True)
        result = runner.invoke(app, ["update", "--enable"])
        assert result.exit_code == 0
        assert auto_update.load_cache().disabled is False

    def test_enable_and_disable_are_mutually_exclusive(
        self, fake_home: Path, installed_build: str
    ) -> None:
        result = runner.invoke(app, ["update", "--enable", "--disable"])
        assert result.exit_code == 2


class TestUpdateCommandCheck:
    def test_reports_up_to_date(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        installed_build: str,
    ) -> None:
        info = auto_update.UpdateInfo(
            current_commit=installed_build,
            latest_commit=installed_build,
            update_available=False,
        )
        monkeypatch.setattr(
            "discovery.poll.cli_update.check_for_update",
            lambda *_a, **_k: (info, None),
        )
        result = runner.invoke(app, ["update"])
        assert result.exit_code == 0
        assert "latest version" in result.stdout

    def test_reports_update_available_with_check_flag(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        installed_build: str,
    ) -> None:
        info = auto_update.UpdateInfo(
            current_commit=installed_build,
            latest_commit="cafef00d",
            latest_commit_date="2025-06-01T00:00:00Z",
            update_available=True,
        )
        monkeypatch.setattr(
            "discovery.poll.cli_update.check_for_update",
            lambda *_a, **_k: (info, None),
        )
        result = runner.invoke(app, ["update", "--check"])
        assert result.exit_code == 0
        assert "cafef00d" in result.stdout
        assert "discovery update" in result.stdout

    def test_network_failure_exits_3(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        installed_build: str,
    ) -> None:
        def raise_network(*_a: object, **_k: object) -> None:
            msg = "DNS failure"
            raise auto_update.UpdateCheckError(
                auto_update.REASON_NETWORK, msg
            )

        monkeypatch.setattr(
            "discovery.poll.cli_update.check_for_update",
            raise_network,
        )
        result = runner.invoke(app, ["update"])
        assert result.exit_code == 3
        assert "Could not check for updates" in result.stdout
        assert "network" in result.stdout

    def test_rate_limit_message_offers_token_hint(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        installed_build: str,
    ) -> None:
        def raise_rate(*_a: object, **_k: object) -> None:
            msg = "API rate limit exceeded"
            raise auto_update.UpdateCheckError(
                auto_update.REASON_RATE_LIMITED, msg
            )

        monkeypatch.setattr(
            "discovery.poll.cli_update.check_for_update",
            raise_rate,
        )
        result = runner.invoke(app, ["update"])
        assert result.exit_code == 3
        assert "GITHUB_TOKEN" in result.stdout
        assert "gh auth login" in result.stdout


class TestUpdateCommandInstall:
    def test_install_with_yes_runs_uv(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        installed_build: str,
    ) -> None:
        info = auto_update.UpdateInfo(
            current_commit=installed_build,
            latest_commit="cafef00d",
            update_available=True,
        )
        monkeypatch.setattr(
            "discovery.poll.cli_update.check_for_update",
            lambda *_a, **_k: (info, None),
        )
        install = MagicMock(return_value=0)
        monkeypatch.setattr(
            "discovery.poll.cli_update.install_update", install
        )
        result = runner.invoke(app, ["update", "--yes"])
        assert result.exit_code == 0
        install.assert_called_once()
        # The successful install should baseline the cache so the
        # at-exit notifier doesn't immediately re-trigger.
        state = auto_update.load_cache()
        assert state.notified_commit == "cafef00d"

    def test_install_failure_exits_with_subprocess_code(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        installed_build: str,
    ) -> None:
        info = auto_update.UpdateInfo(
            current_commit=installed_build,
            latest_commit="cafef00d",
            update_available=True,
        )
        monkeypatch.setattr(
            "discovery.poll.cli_update.check_for_update",
            lambda *_a, **_k: (info, None),
        )
        monkeypatch.setattr(
            "discovery.poll.cli_update.install_update",
            lambda *_a, **_k: 7,
        )
        result = runner.invoke(app, ["update", "--yes"])
        assert result.exit_code == 7

    def test_install_missing_uv_exits_1(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        installed_build: str,
    ) -> None:
        info = auto_update.UpdateInfo(
            current_commit=installed_build,
            latest_commit="cafef00d",
            update_available=True,
        )
        monkeypatch.setattr(
            "discovery.poll.cli_update.check_for_update",
            lambda *_a, **_k: (info, None),
        )

        def explode(*_a: object, **_k: object) -> int:
            msg = "uv not on PATH"
            raise auto_update.UpgradeError(msg)

        monkeypatch.setattr(
            "discovery.poll.cli_update.install_update", explode
        )
        result = runner.invoke(app, ["update", "--yes"])
        assert result.exit_code == 1
        assert "uv not on PATH" in result.stdout


class TestRootCallbackHooks:
    """The root callback should arm the auto-update machinery."""

    def test_schedule_and_atexit_register_on_invocation(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path
    ) -> None:
        schedule = MagicMock()
        register = MagicMock()
        monkeypatch.setattr("discovery.poll.cli.schedule_check", schedule)
        monkeypatch.setattr("discovery.poll.cli.atexit.register", register)

        with patch(
            "discovery.poll.cli_update.check_for_update",
            return_value=None,
        ):
            runner.invoke(app, ["update", "--check"])
        assert schedule.called
        assert register.called
        # The registered callable must be maybe_notify.
        assert any(
            call.args and call.args[0] is maybe_notify
            for call in register.call_args_list
        )

    def test_version_flag_also_arms_auto_update(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path
    ) -> None:
        """`--version` is an eager Typer callback that exits before the
        main callback body runs; the auto-update wiring must still fire
        so users running only `--version` are not stuck on a stale cache.
        """
        schedule = MagicMock()
        register = MagicMock()
        monkeypatch.setattr("discovery.poll.cli.schedule_check", schedule)
        monkeypatch.setattr("discovery.poll.cli.atexit.register", register)
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "discovery" in result.stdout
        assert schedule.called
        assert register.called
