"""Tests for discovery.common.paths — config path resolution and WSL support."""

from __future__ import annotations

from pathlib import Path

import pytest

from discovery.common import paths


class TestGetConfigFilePathEnvOverride:
    """DISCOVERY_CONFIG_PATH env var takes priority over all other logic."""

    def test_env_override_returns_exact_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        override = tmp_path / "custom-config"
        monkeypatch.setenv("DISCOVERY_CONFIG_PATH", str(override))
        assert paths.get_config_file_path() == override

    def test_env_override_does_not_require_file_to_exist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DISCOVERY_CONFIG_PATH", "/nonexistent/path/config")
        assert paths.get_config_file_path() == Path("/nonexistent/path/config")

    def test_env_override_beats_primary(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Even when the primary exists, the env override wins."""
        primary = tmp_path / "home" / paths.CONFIG_FILE_NAME
        primary.parent.mkdir(parents=True)
        primary.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))

        override = tmp_path / "override-config"
        monkeypatch.setenv("DISCOVERY_CONFIG_PATH", str(override))
        assert paths.get_config_file_path() == override


class TestGetConfigFilePathPrimary:
    """Default behaviour: Path.home() / CONFIG_FILE_NAME."""

    def test_returns_primary_when_file_exists(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        cfg = home / paths.CONFIG_FILE_NAME
        cfg.write_text("{}", encoding="utf-8")

        monkeypatch.delenv("DISCOVERY_CONFIG_PATH", raising=False)
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        assert paths.get_config_file_path() == cfg

    def test_returns_primary_when_file_absent_and_not_wsl(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()

        monkeypatch.delenv("DISCOVERY_CONFIG_PATH", raising=False)
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        assert paths.get_config_file_path() == home / paths.CONFIG_FILE_NAME


class TestGetConfigFilePathWSLFallback:
    """On WSL, search alternative home dirs when primary doesn't have the config."""

    def test_falls_back_to_pwd_home_on_wsl(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Simulates WSL where Path.home() = /mnt/c/Users/user but config is in /home/user."""
        windows_home = tmp_path / "mnt" / "c" / "Users" / "user"
        windows_home.mkdir(parents=True)
        linux_home = tmp_path / "home" / "user"
        linux_home.mkdir(parents=True)

        # Config exists only at the Linux home
        (linux_home / paths.CONFIG_FILE_NAME).write_text("{}", encoding="utf-8")

        monkeypatch.delenv("DISCOVERY_CONFIG_PATH", raising=False)
        monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
        monkeypatch.setattr(Path, "home", staticmethod(lambda: windows_home))

        # Mock pwd.getpwuid to return the Linux home
        import types

        fake_pwd = types.ModuleType("pwd")
        pw_entry = types.SimpleNamespace(pw_dir=str(linux_home))
        fake_pwd.getpwuid = lambda uid: pw_entry  # type: ignore[attr-defined]
        monkeypatch.setattr(paths, "pwd", fake_pwd, raising=False)

        # We need to make _wsl_home_candidates use our mocked pwd
        # by patching the import inside the function

        def patched_candidates() -> list[Path]:
            primary = Path.home()
            seen = {primary}
            candidates: list[Path] = []
            pw_home = Path(linux_home)
            if pw_home not in seen:
                candidates.append(pw_home)
                seen.add(pw_home)
            return candidates

        monkeypatch.setattr(paths, "_wsl_home_candidates", patched_candidates)

        result = paths.get_config_file_path()
        assert result == linux_home / paths.CONFIG_FILE_NAME

    def test_no_fallback_when_primary_exists_on_wsl(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Even on WSL, primary wins when it exists."""
        home = tmp_path / "home"
        home.mkdir()
        cfg = home / paths.CONFIG_FILE_NAME
        cfg.write_text("{}", encoding="utf-8")

        monkeypatch.delenv("DISCOVERY_CONFIG_PATH", raising=False)
        monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

        assert paths.get_config_file_path() == cfg

    def test_returns_primary_when_no_candidate_has_config(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """WSL fallback returns primary when no candidates have config either."""
        home = tmp_path / "home"
        home.mkdir()

        monkeypatch.delenv("DISCOVERY_CONFIG_PATH", raising=False)
        monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        monkeypatch.setattr(paths, "_wsl_home_candidates", list)

        assert paths.get_config_file_path() == home / paths.CONFIG_FILE_NAME


class TestIsWSL:
    def test_true_when_wsl_distro_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
        assert paths.is_wsl() is True

    def test_false_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        assert paths.is_wsl() is False

    def test_false_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WSL_DISTRO_NAME", "")
        assert paths.is_wsl() is False


class TestGetHomeDir:
    def test_returns_path_home_when_not_wsl(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        assert paths.get_home_dir() == tmp_path

    def test_prefers_candidate_with_discovery_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        windows_home = tmp_path / "win_home"
        windows_home.mkdir()
        linux_home = tmp_path / "linux_home"
        linux_home.mkdir()
        (linux_home / ".discovery").mkdir()

        monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
        monkeypatch.setattr(Path, "home", staticmethod(lambda: windows_home))
        monkeypatch.setattr(paths, "_wsl_home_candidates", lambda: [linux_home])

        assert paths.get_home_dir() == linux_home

    def test_prefers_candidate_with_config_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        windows_home = tmp_path / "win_home"
        windows_home.mkdir()
        linux_home = tmp_path / "linux_home"
        linux_home.mkdir()
        (linux_home / paths.CONFIG_FILE_NAME).write_text("{}", encoding="utf-8")

        monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
        monkeypatch.setattr(Path, "home", staticmethod(lambda: windows_home))
        monkeypatch.setattr(paths, "_wsl_home_candidates", lambda: [linux_home])

        assert paths.get_home_dir() == linux_home

    def test_falls_back_to_primary_when_no_discovery_artefacts(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        windows_home = tmp_path / "win_home"
        windows_home.mkdir()
        linux_home = tmp_path / "linux_home"
        linux_home.mkdir()

        monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
        monkeypatch.setattr(Path, "home", staticmethod(lambda: windows_home))
        monkeypatch.setattr(paths, "_wsl_home_candidates", lambda: [linux_home])

        assert paths.get_home_dir() == windows_home


class TestBackwardCompatibility:
    """Ensure get_config_file_path is still importable from cli_helpers."""

    def test_import_from_cli_helpers(self) -> None:
        from discovery.poll.cli_helpers import get_config_file_path

        assert callable(get_config_file_path)
        # Should be the same function
        assert get_config_file_path is paths.get_config_file_path


class TestIsWSLProcVersionFallback:
    """is_wsl() falls back to /proc/version when WSL_DISTRO_NAME is unset."""

    def test_true_via_proc_version_microsoft(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        fake = tmp_path / "proc_version"
        fake.write_text("Linux version 5.15.153.1-microsoft-standard-WSL2\n", encoding="utf-8")

        import builtins

        real_open = builtins.open

        def fake_open(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if path == "/proc/version":
                return real_open(fake, *args, **kwargs)
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", fake_open)
        assert paths.is_wsl() is True

    def test_false_when_proc_version_not_microsoft(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
        fake = tmp_path / "proc_version"
        fake.write_text("Linux version 6.1.0 (Debian 6.1.0)\n", encoding="utf-8")

        import builtins

        real_open = builtins.open

        def fake_open(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if path == "/proc/version":
                return real_open(fake, *args, **kwargs)
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", fake_open)
        assert paths.is_wsl() is False

    def test_false_when_proc_version_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)

        import builtins

        def raising_open(path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if path == "/proc/version":
                raise OSError("no such file")
            return builtins.__dict__["open"](path, *args, **kwargs)

        # Only replace open for the /proc/version path; delegate otherwise.
        real_open = builtins.open
        monkeypatch.setattr(
            builtins,
            "open",
            lambda p, *a, **kw: (_ for _ in ()).throw(OSError("no such file"))
            if p == "/proc/version"
            else real_open(p, *a, **kw),
        )
        assert paths.is_wsl() is False


class TestWindowsHomeOnWSL:
    """_windows_home_on_wsl() uses cmd.exe + wslpath to resolve %USERPROFILE%."""

    def test_returns_none_when_cmd_exe_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess as sp

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise OSError("cmd.exe not found")

        monkeypatch.setattr(sp, "run", fake_run)
        assert paths._windows_home_on_wsl() is None

    def test_returns_none_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess as sp

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise sp.TimeoutExpired(cmd=args[0] if args else "", timeout=2)

        monkeypatch.setattr(sp, "run", fake_run)
        assert paths._windows_home_on_wsl() is None

    def test_returns_none_on_nonzero_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess as sp
        import types

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            return types.SimpleNamespace(returncode=1, stdout="", stderr="boom")

        monkeypatch.setattr(sp, "run", fake_run)
        assert paths._windows_home_on_wsl() is None

    def test_returns_none_when_var_unexpanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """cmd.exe prints '%USERPROFILE%' literally when the var is not set."""
        import subprocess as sp
        import types

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            return types.SimpleNamespace(returncode=0, stdout="%USERPROFILE%\r\n", stderr="")

        monkeypatch.setattr(sp, "run", fake_run)
        assert paths._windows_home_on_wsl() is None

    def test_returns_wsl_path_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess as sp
        import types

        calls: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(cmd)
            if cmd[0] == "cmd.exe":
                return types.SimpleNamespace(returncode=0, stdout="C:\\Users\\Bob\r\n", stderr="")
            if cmd[0] == "wslpath":
                assert cmd == ["wslpath", "-u", "C:\\Users\\Bob"]
                return types.SimpleNamespace(returncode=0, stdout="/mnt/c/Users/Bob\n", stderr="")
            raise AssertionError(f"unexpected cmd: {cmd}")

        monkeypatch.setattr(sp, "run", fake_run)
        assert paths._windows_home_on_wsl() == Path("/mnt/c/Users/Bob")

    def test_wsl_fallback_finds_config_in_windows_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Linux→Windows case: Path.home()=/home/user but config is /mnt/c/Users/USER/."""
        linux_home = tmp_path / "home" / "user"
        linux_home.mkdir(parents=True)
        windows_home = tmp_path / "mnt" / "c" / "Users" / "Bob"
        windows_home.mkdir(parents=True)
        (windows_home / paths.CONFIG_FILE_NAME).write_text("{}", encoding="utf-8")

        monkeypatch.delenv("DISCOVERY_CONFIG_PATH", raising=False)
        monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
        monkeypatch.setenv("HOME", str(linux_home))
        monkeypatch.setattr(Path, "home", staticmethod(lambda: linux_home))

        # Only the Windows-home hook returns something; pwd fallback matches
        # Path.home so contributes nothing.
        import types

        fake_pwd = types.ModuleType("pwd")
        fake_pwd.getpwuid = lambda uid: types.SimpleNamespace(pw_dir=str(linux_home))  # type: ignore[attr-defined]
        monkeypatch.setitem(__import__("sys").modules, "pwd", fake_pwd)
        monkeypatch.setattr(paths, "_windows_home_on_wsl", lambda: windows_home)

        assert paths.get_config_file_path() == windows_home / paths.CONFIG_FILE_NAME
