"""Tests for :mod:`discovery.common.auto_update`."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from discovery.common import auto_update


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the cache directory at a tmp path for the duration of a test."""
    monkeypatch.setattr(
        "discovery.common.auto_update.get_home_dir",
        lambda: tmp_path,
    )
    return tmp_path


@pytest.fixture
def installed_build(monkeypatch: pytest.MonkeyPatch) -> str:
    """Pretend we are running a real ``uv tool``-installed build (commit != dev)."""
    sha = "deadbeef"
    monkeypatch.setattr(
        "discovery.common.auto_update.get_build_commit",
        lambda: sha,
    )
    return sha


@pytest.fixture
def enable_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the conftest autouse opt-out for tests that need to verify the path."""
    monkeypatch.delenv(auto_update.ENV_OPT_OUT, raising=False)


def _compare_response(
    *,
    ahead_by: int = 1,
    cli_filename: str = "utilities/supercomputer-cli/discovery/foo.py",
    extra_filename: str | None = None,
    commit_sha: str = "1234567890abcdef1234567890abcdef12345678",
    commit_date: str = "2025-05-30T12:00:00Z",
) -> dict:
    """Build a minimal compare-API payload for use in tests."""
    files = [{"filename": cli_filename, "status": "modified"}]
    if extra_filename is not None:
        files.append({"filename": extra_filename, "status": "modified"})
    return {
        "ahead_by": ahead_by,
        "behind_by": 0,
        "status": "behind" if ahead_by else "identical",
        "files": files,
        "commits": [
            {
                "sha": commit_sha,
                "commit": {"committer": {"date": commit_date}},
                "files": files,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Cache load / save round-trip
# ---------------------------------------------------------------------------


class TestCacheIO:
    def test_load_returns_empty_when_missing(self, fake_home: Path) -> None:
        state = auto_update.load_cache()
        assert state == auto_update.UpdateCacheState()

    def test_round_trip_preserves_all_fields(self, fake_home: Path) -> None:
        original = auto_update.UpdateCacheState(
            last_checked="2025-05-31T00:00:00+00:00",
            latest_commit="abcd1234",
            latest_commit_date="2025-05-30T12:00:00Z",
            current_at_check="11112222",
            notified_commit="abcd1234",
            disabled=True,
        )
        auto_update.save_cache(original)
        loaded = auto_update.load_cache()
        assert loaded == original

    def test_load_ignores_unknown_keys(self, fake_home: Path) -> None:
        path = auto_update._cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"latest_commit": "feedface", "unknown_future_key": 42}),
            encoding="utf-8",
        )
        loaded = auto_update.load_cache()
        assert loaded.latest_commit == "feedface"

    def test_load_returns_empty_on_corrupt_json(self, fake_home: Path) -> None:
        path = auto_update._cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json}", encoding="utf-8")
        assert auto_update.load_cache() == auto_update.UpdateCacheState()

    def test_load_returns_empty_when_top_level_not_dict(
        self, fake_home: Path
    ) -> None:
        path = auto_update._cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[1, 2, 3]", encoding="utf-8")
        assert auto_update.load_cache() == auto_update.UpdateCacheState()

    def test_save_creates_parent_directory(self, fake_home: Path) -> None:
        nested = fake_home / "deeply" / "nested"
        with patch(
            "discovery.common.auto_update.get_home_dir",
            return_value=nested,
        ):
            auto_update.save_cache(
                auto_update.UpdateCacheState(latest_commit="x")
            )
            assert (nested / auto_update.CACHE_DIR_NAME / auto_update.CACHE_FILE_NAME).exists()


# ---------------------------------------------------------------------------
# Opt-out + staleness
# ---------------------------------------------------------------------------


class TestOptOut:
    def test_env_var_opts_out(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path
    ) -> None:
        monkeypatch.setenv(auto_update.ENV_OPT_OUT, "1")
        assert auto_update.is_opted_out() is True

    def test_env_var_falsy_does_not_opt_out(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        enable_checks: None,
    ) -> None:
        monkeypatch.setenv(auto_update.ENV_OPT_OUT, "")
        assert auto_update.is_opted_out() is False

    def test_disabled_flag_opts_out(
        self, fake_home: Path, enable_checks: None
    ) -> None:
        auto_update.set_disabled(True)
        assert auto_update.is_opted_out() is True

    def test_set_disabled_round_trip(
        self, fake_home: Path, enable_checks: None
    ) -> None:
        auto_update.set_disabled(True)
        assert auto_update.load_cache().disabled is True
        auto_update.set_disabled(False)
        assert auto_update.load_cache().disabled is False


class TestCacheIsStale:
    def test_empty_cache_is_stale(self) -> None:
        assert auto_update.cache_is_stale(auto_update.UpdateCacheState())

    def test_fresh_cache_not_stale(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = datetime(2025, 5, 31, 12, 0, tzinfo=timezone.utc)
        monkeypatch.setattr("discovery.common.auto_update._now", lambda: now)
        state = auto_update.UpdateCacheState(
            last_checked=(now - timedelta(hours=1)).isoformat()
        )
        assert auto_update.cache_is_stale(state) is False

    def test_old_cache_is_stale(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now = datetime(2025, 5, 31, 12, 0, tzinfo=timezone.utc)
        monkeypatch.setattr("discovery.common.auto_update._now", lambda: now)
        state = auto_update.UpdateCacheState(
            last_checked=(now - timedelta(hours=48)).isoformat()
        )
        assert auto_update.cache_is_stale(state) is True

    def test_unparseable_timestamp_is_stale(self) -> None:
        state = auto_update.UpdateCacheState(last_checked="not a date")
        assert auto_update.cache_is_stale(state) is True


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


class TestShouldCheck:
    def test_dev_install_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "discovery.common.auto_update.get_build_commit",
            lambda: auto_update.DEV_COMMIT_SENTINEL,
        )
        assert auto_update._should_check() is False

    def test_real_install_eligible(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "discovery.common.auto_update.get_build_commit",
            lambda: "abc12345",
        )
        assert auto_update._should_check() is True


# ---------------------------------------------------------------------------
# fetch_update_info
# ---------------------------------------------------------------------------


def _patch_httpx_get(payload: dict | None, *, status: int = 200) -> MagicMock:
    """Return a context-manager mock that yields a client whose .get(...) returns ``payload``."""
    response = MagicMock()
    response.status_code = status
    if payload is None:
        response.json.side_effect = ValueError("no body")
    else:
        response.json.return_value = payload
    if status >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=MagicMock(), response=response
        )
    else:
        response.raise_for_status.return_value = None

    client = MagicMock()
    client.get.return_value = response
    cm = MagicMock()
    cm.__enter__.return_value = client
    cm.__exit__.return_value = False
    return MagicMock(return_value=cm)


class TestFetchUpdateInfo:
    def test_returns_none_for_dev_commit(self) -> None:
        assert (
            auto_update.fetch_update_info(auto_update.DEV_COMMIT_SENTINEL)
            is None
        )

    def test_returns_none_for_empty_commit(self) -> None:
        assert auto_update.fetch_update_info("") is None

    def test_reports_update_when_cli_dir_changed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _compare_response(
            commit_sha="abcdef1234567890abcdef1234567890abcdef12",
            commit_date="2025-06-01T08:00:00Z",
        )
        monkeypatch.setattr(httpx, "Client", _patch_httpx_get(payload))
        info = auto_update.fetch_update_info("deadbeef")
        assert info is not None
        assert info.update_available is True
        assert info.latest_commit == "abcdef12"
        assert info.latest_commit_date == "2025-06-01T08:00:00Z"
        assert info.current_commit == "deadbeef"

    def test_sends_authorization_header_when_token_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _compare_response()
        client_mock = MagicMock()
        response = MagicMock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        client_mock.get.return_value = response
        cm = MagicMock()
        cm.__enter__.return_value = client_mock
        cm.__exit__.return_value = False
        monkeypatch.setattr(httpx, "Client", MagicMock(return_value=cm))
        monkeypatch.setenv("DISCOVERY_GITHUB_TOKEN", "secret-token")

        auto_update.fetch_update_info("deadbeef")

        sent_headers = client_mock.get.call_args.kwargs["headers"]
        assert sent_headers["Authorization"] == "Bearer secret-token"

    def test_no_authorization_header_when_no_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in auto_update.TOKEN_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        # Stub out gh CLI lookup so the test doesn't depend on the
        # developer's local `gh auth` state.
        monkeypatch.setattr(
            "discovery.common.auto_update.shutil.which", lambda _: None
        )
        payload = _compare_response()
        client_mock = MagicMock()
        response = MagicMock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        client_mock.get.return_value = response
        cm = MagicMock()
        cm.__enter__.return_value = client_mock
        cm.__exit__.return_value = False
        monkeypatch.setattr(httpx, "Client", MagicMock(return_value=cm))

        auto_update.fetch_update_info("deadbeef")
        sent_headers = client_mock.get.call_args.kwargs["headers"]
        assert "Authorization" not in sent_headers

    def test_reports_no_update_when_no_cli_changes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _compare_response(
            cli_filename="agents/some-agent/metadata.yaml",
        )
        monkeypatch.setattr(httpx, "Client", _patch_httpx_get(payload))
        info = auto_update.fetch_update_info("deadbeef")
        assert info is not None
        assert info.update_available is False
        assert info.latest_commit == "deadbeef"

    def test_reports_no_update_when_ahead_by_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = _compare_response(ahead_by=0)
        monkeypatch.setattr(httpx, "Client", _patch_httpx_get(payload))
        info = auto_update.fetch_update_info("deadbeef")
        assert info is not None
        assert info.update_available is False

    def test_returns_none_on_network_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = MagicMock()
        client.get.side_effect = httpx.ConnectError("no network")
        cm = MagicMock()
        cm.__enter__.return_value = client
        cm.__exit__.return_value = False
        monkeypatch.setattr(httpx, "Client", MagicMock(return_value=cm))
        assert auto_update.fetch_update_info("deadbeef") is None

    def test_returns_none_on_http_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            httpx, "Client", _patch_httpx_get({}, status=500)
        )
        assert auto_update.fetch_update_info("deadbeef") is None

    def test_returns_none_on_invalid_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(httpx, "Client", _patch_httpx_get(None))
        assert auto_update.fetch_update_info("deadbeef") is None

    def test_picks_newest_cli_commit_among_mixed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 3 commits: oldest CLI, middle unrelated, newest unrelated.
        # Newest CLI-touching should win even though it's not the tip.
        payload = {
            "ahead_by": 3,
            "files": [
                {"filename": "utilities/supercomputer-cli/discovery/x.py"},
                {"filename": "agents/other/README.md"},
            ],
            "commits": [
                {
                    "sha": "111111111111111111",
                    "commit": {"committer": {"date": "2025-01-01T00:00:00Z"}},
                    "files": [
                        {"filename": "utilities/supercomputer-cli/discovery/x.py"}
                    ],
                },
                {
                    "sha": "222222222222222222",
                    "commit": {"committer": {"date": "2025-02-01T00:00:00Z"}},
                    "files": [
                        {"filename": "utilities/supercomputer-cli/discovery/y.py"}
                    ],
                },
                {
                    "sha": "333333333333333333",
                    "commit": {"committer": {"date": "2025-03-01T00:00:00Z"}},
                    "files": [{"filename": "agents/other/README.md"}],
                },
            ],
        }
        monkeypatch.setattr(httpx, "Client", _patch_httpx_get(payload))
        info = auto_update.fetch_update_info("deadbeef")
        assert info is not None
        assert info.latest_commit == "22222222"

    def test_falls_back_to_tip_when_per_commit_files_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = {
            "ahead_by": 1,
            "files": [
                {"filename": "utilities/supercomputer-cli/discovery/x.py"}
            ],
            "commits": [
                {
                    "sha": "abcdef1234567890",
                    "commit": {"committer": {"date": "2025-06-01T00:00:00Z"}},
                }
            ],
        }
        monkeypatch.setattr(httpx, "Client", _patch_httpx_get(payload))
        info = auto_update.fetch_update_info("deadbeef")
        assert info is not None
        assert info.latest_commit == "abcdef12"
        assert info.update_available is True


class TestTokenResolution:
    def test_env_var_priority(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DISCOVERY_GITHUB_TOKEN", "from-discovery")
        monkeypatch.setenv("GITHUB_TOKEN", "from-github")
        assert auto_update._resolve_github_token() == "from-discovery"

    def test_falls_back_to_github_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DISCOVERY_GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "from-github")
        monkeypatch.delenv("GH_TOKEN", raising=False)
        assert auto_update._resolve_github_token() == "from-github"

    def test_falls_back_to_gh_cli_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in auto_update.TOKEN_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(
            "discovery.common.auto_update.shutil.which",
            lambda _: "/usr/local/bin/gh",
        )
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "ghp_fakefakefakefake\n"
        monkeypatch.setattr(
            "discovery.common.auto_update.subprocess.run",
            MagicMock(return_value=proc),
        )
        assert auto_update._resolve_github_token() == "ghp_fakefakefakefake"

    def test_returns_none_when_no_token_anywhere(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in auto_update.TOKEN_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(
            "discovery.common.auto_update.shutil.which", lambda _: None
        )
        assert auto_update._resolve_github_token() is None

    def test_gh_cli_failure_falls_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in auto_update.TOKEN_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(
            "discovery.common.auto_update.shutil.which",
            lambda _: "/usr/local/bin/gh",
        )
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = ""
        monkeypatch.setattr(
            "discovery.common.auto_update.subprocess.run",
            MagicMock(return_value=proc),
        )
        assert auto_update._resolve_github_token() is None


# ---------------------------------------------------------------------------
# schedule_check
# ---------------------------------------------------------------------------


class TestScheduleCheck:
    def test_skipped_for_dev_install(
        self, monkeypatch: pytest.MonkeyPatch, fake_home: Path
    ) -> None:
        monkeypatch.setattr(
            "discovery.common.auto_update.get_build_commit",
            lambda: "dev",
        )
        assert auto_update.schedule_check() is None

    def test_skipped_when_opted_out_via_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        installed_build: str,
    ) -> None:
        monkeypatch.setenv(auto_update.ENV_OPT_OUT, "1")
        assert auto_update.schedule_check() is None

    def test_skipped_when_cache_fresh(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        installed_build: str,
        enable_checks: None,
    ) -> None:
        now = datetime(2025, 5, 31, 12, 0, tzinfo=timezone.utc)
        monkeypatch.setattr("discovery.common.auto_update._now", lambda: now)
        auto_update.save_cache(
            auto_update.UpdateCacheState(
                last_checked=(now - timedelta(minutes=10)).isoformat()
            )
        )
        assert auto_update.schedule_check() is None

    def test_spawns_thread_when_stale(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        installed_build: str,
        enable_checks: None,
    ) -> None:
        # Stub out the worker so the thread terminates immediately without
        # hitting the network.
        called = {"count": 0}

        def stub_worker() -> None:
            called["count"] += 1

        monkeypatch.setattr(
            "discovery.common.auto_update._refresh_cache_worker", stub_worker
        )
        thread = auto_update.schedule_check()
        assert thread is not None
        thread.join(timeout=2)
        assert called["count"] == 1


# ---------------------------------------------------------------------------
# Worker behavior
# ---------------------------------------------------------------------------


class TestRefreshCacheWorker:
    def test_writes_cache_on_success(
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
        now = datetime(2025, 6, 1, 9, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(
            "discovery.common.auto_update.fetch_update_info",
            lambda *_args, **_kw: info,
        )
        monkeypatch.setattr("discovery.common.auto_update._now", lambda: now)
        auto_update._refresh_cache_worker()

        state = auto_update.load_cache()
        assert state.latest_commit == "cafef00d"
        assert state.latest_commit_date == "2025-06-01T00:00:00Z"
        assert state.current_at_check == installed_build
        assert state.last_checked == now.isoformat()

    def test_resets_notified_on_upgrade(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        installed_build: str,
    ) -> None:
        """When the installed commit changes between checks, the
        ``notified_commit`` memo must be cleared so the next pending
        update is announced even if it happens to match an old SHA."""
        auto_update.save_cache(
            auto_update.UpdateCacheState(
                current_at_check="oldoldol",
                notified_commit="cafef00d",
                latest_commit="cafef00d",
            )
        )
        info = auto_update.UpdateInfo(
            current_commit=installed_build,
            latest_commit="cafef00d",
            update_available=True,
        )
        monkeypatch.setattr(
            "discovery.common.auto_update.fetch_update_info",
            lambda *_a, **_k: info,
        )
        auto_update._refresh_cache_worker()
        state = auto_update.load_cache()
        assert state.notified_commit is None
        assert state.current_at_check == installed_build

    def test_no_cache_write_on_network_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        installed_build: str,
    ) -> None:
        monkeypatch.setattr(
            "discovery.common.auto_update.fetch_update_info",
            lambda *_a, **_k: None,
        )
        auto_update._refresh_cache_worker()
        assert not auto_update._cache_path().exists()


# ---------------------------------------------------------------------------
# maybe_notify
# ---------------------------------------------------------------------------


class TestMaybeNotify:
    def test_silent_when_no_cache(
        self,
        fake_home: Path,
        installed_build: str,
        capsys: pytest.CaptureFixture,
        enable_checks: None,
    ) -> None:
        auto_update.maybe_notify()
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_silent_when_already_notified(
        self,
        fake_home: Path,
        installed_build: str,
        capsys: pytest.CaptureFixture,
        enable_checks: None,
    ) -> None:
        auto_update.save_cache(
            auto_update.UpdateCacheState(
                latest_commit="newshasx",
                notified_commit="newshasx",
            )
        )
        auto_update.maybe_notify()
        assert capsys.readouterr().err == ""

    def test_silent_when_disabled(
        self,
        fake_home: Path,
        installed_build: str,
        capsys: pytest.CaptureFixture,
        enable_checks: None,
    ) -> None:
        auto_update.save_cache(
            auto_update.UpdateCacheState(
                latest_commit="newshasx",
                disabled=True,
            )
        )
        auto_update.maybe_notify()
        assert capsys.readouterr().err == ""

    def test_prints_and_marks_notified(
        self,
        fake_home: Path,
        installed_build: str,
        capsys: pytest.CaptureFixture,
        enable_checks: None,
    ) -> None:
        auto_update.save_cache(
            auto_update.UpdateCacheState(
                latest_commit="newshasx",
                latest_commit_date="2025-06-01T00:00:00Z",
            )
        )
        auto_update.maybe_notify()
        out = capsys.readouterr().err
        assert "Discovery CLI" in out
        assert "newshasx" in out
        state = auto_update.load_cache()
        assert state.notified_commit == "newshasx"

    def test_silent_for_dev_build(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        capsys: pytest.CaptureFixture,
        enable_checks: None,
    ) -> None:
        monkeypatch.setattr(
            "discovery.common.auto_update.get_build_commit",
            lambda: "dev",
        )
        auto_update.save_cache(
            auto_update.UpdateCacheState(latest_commit="newshasx")
        )
        auto_update.maybe_notify()
        assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# format_notification
# ---------------------------------------------------------------------------


class TestFormatNotification:
    def test_includes_all_fields(self) -> None:
        msg = auto_update.format_notification(
            "deadbeef", "cafef00d", "2025-06-01T08:00:00Z"
        )
        assert "deadbeef" in msg
        assert "cafef00d" in msg
        assert "2025-06-01" in msg
        assert auto_update.UPGRADE_COMMAND in msg

    def test_omits_empty_date(self) -> None:
        msg = auto_update.format_notification("deadbeef", "cafef00d", "")
        assert "()" not in msg


# ---------------------------------------------------------------------------
# install_update
# ---------------------------------------------------------------------------


class TestInstallUpdate:
    def test_raises_when_uv_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "discovery.common.auto_update.shutil.which", lambda _: None
        )
        with pytest.raises(auto_update.UpgradeError):
            auto_update.install_update()

    def test_dry_run_does_not_invoke_subprocess(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "discovery.common.auto_update.shutil.which", lambda _: "/usr/bin/uv"
        )
        called = MagicMock()
        monkeypatch.setattr(
            "discovery.common.auto_update.subprocess.run", called
        )
        rc = auto_update.install_update(dry_run=True)
        assert rc == 0
        called.assert_not_called()

    def test_runs_uv_tool_upgrade(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "discovery.common.auto_update.shutil.which", lambda _: "/usr/bin/uv"
        )
        proc = MagicMock()
        proc.returncode = 0
        run = MagicMock(return_value=proc)
        monkeypatch.setattr(
            "discovery.common.auto_update.subprocess.run", run
        )
        rc = auto_update.install_update()
        assert rc == 0
        run.assert_called_once_with(
            ["uv", "tool", "upgrade", "discovery"], check=False
        )

    def test_returns_nonzero_on_subprocess_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "discovery.common.auto_update.shutil.which", lambda _: "/usr/bin/uv"
        )
        proc = MagicMock()
        proc.returncode = 7
        monkeypatch.setattr(
            "discovery.common.auto_update.subprocess.run",
            MagicMock(return_value=proc),
        )
        assert auto_update.install_update() == 7
