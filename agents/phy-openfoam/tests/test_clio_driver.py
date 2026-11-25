"""Native run receipt parsing, including terminal waits without a sequence field."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import clio_driver, result_paths


class FakeClient:
    waits = []

    def __init__(self, cwd, log):
        self.p = SimpleNamespace(pid=123)

    def init(self):
        pass

    def call(self, method):
        assert method == "tools/list"
        return {"tools": [{"name": "start"}, {"name": "wait"}]}

    def tool(self, name, args, timeout):
        if name == "start":
            return (
                "RESUMED from session 00000000-0000-0000-0000-123456abcdef\n"
                "run_id: dead12345678\n"
            )
        assert name == "wait" and args["run_id"] == "dead12345678"
        self.waits.append(args["since_seq"])
        return ("run dead12345678 [running] seq=7" if len(self.waits) == 1 else
                "run dead12345678 [done]\n===== RESULT =====\ncomplete")

    def close(self):
        pass


def test_resume_id_and_terminal_missing_sequence_are_parsed(tmp_path, monkeypatch):
    FakeClient.waits = []
    monkeypatch.setattr(clio_driver, "Client", FakeClient)
    result = clio_driver.run("test objective", tmp_path / "out", cwd=tmp_path, timeout=30)
    assert result["run_id"] == "dead12345678" and result["state"] == "done"
    assert result["seq"] == 7 and FakeClient.waits == [0, 7]
    assert json.loads((tmp_path / "out" / "result.json").read_text())["state"] == "done"


def test_start_without_literal_run_id_is_rejected(tmp_path, monkeypatch):
    class BadClient(FakeClient):
        def tool(self, name, args, timeout):
            return "RESUMED from session 00000000-0000-0000-0000-123456abcdef"

    monkeypatch.setattr(clio_driver, "Client", BadClient)
    with pytest.raises(RuntimeError, match="no run_id"):
        clio_driver.run("test objective", tmp_path / "out", cwd=tmp_path)


def _executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Synthetic executable fixture; never launched.\n", encoding="utf-8")
    path.chmod(0o755)
    return path.resolve()


def test_explicit_executable_overrides_environment_and_path(tmp_path, monkeypatch):
    selected = _executable(tmp_path / "selected CLIO" / "Science.Autopilot.exe")
    other = _executable(tmp_path / "other.exe")
    monkeypatch.setenv("DISCOVERY_CLIO_EXE", str(other))
    monkeypatch.setattr(clio_driver.shutil, "which", lambda _: str(other))
    assert clio_driver.exe(selected) == str(selected)


def test_environment_executable_overrides_path(tmp_path, monkeypatch):
    selected = _executable(tmp_path / "selected.exe")
    monkeypatch.setenv("DISCOVERY_CLIO_EXE", str(selected))
    monkeypatch.setattr(clio_driver.shutil, "which", lambda _: pytest.fail("PATH must not win"))
    assert clio_driver.exe() == str(selected)


@pytest.mark.parametrize("invalid", ["missing", "directory", "not_executable", "empty"])
def test_invalid_explicit_executable_is_not_ignored(tmp_path, monkeypatch, invalid):
    other = _executable(tmp_path / "fallback.exe")
    monkeypatch.setenv("DISCOVERY_CLIO_EXE", str(other))
    selected = tmp_path / "selected.exe"
    if invalid == "directory":
        selected.mkdir()
    elif invalid == "not_executable":
        _executable(selected)
        monkeypatch.setattr(clio_driver.os, "access", lambda *_: False)
    monkeypatch.setattr(clio_driver.shutil, "which", lambda _: None)
    with pytest.raises((FileNotFoundError, PermissionError, ValueError), match="CLIO executable"):
        clio_driver.exe("" if invalid == "empty" else selected)


def test_invalid_environment_override_does_not_fall_back(tmp_path, monkeypatch):
    other = _executable(tmp_path / "fallback.exe")
    missing = tmp_path / "missing.exe"
    monkeypatch.setenv("DISCOVERY_CLIO_EXE", str(missing))
    monkeypatch.setattr(
        clio_driver.shutil, "which",
        lambda command: str(other) if "Science.Autopilot" in command else None,
    )
    with pytest.raises(FileNotFoundError, match="CLIO executable not found"):
        clio_driver.exe()


def test_path_fallback_needs_no_localappdata(tmp_path, monkeypatch):
    selected = _executable(tmp_path / "Science.Autopilot.exe")
    monkeypatch.delenv("DISCOVERY_CLIO_EXE", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(clio_driver.shutil, "which", lambda _: str(selected))
    assert clio_driver.exe() == str(selected)


@pytest.mark.parametrize("versions", [
    [("0.9.9-preview", "0.9.9"), ("0.15.9-preview", "0.15.9"),
     ("0.15.21-preview", "0.15.21")],
    [("0.15.21-preview", "0.15.9"), ("0.15.21-preview", "0.15.21")],
    [("0.15.21-preview.9", "0.15.21"), ("0.15.21-preview.10", "0.15.21")],
])
def test_preview_discovery_sorts_versions_numerically(tmp_path_factory, monkeypatch, versions):
    # The vendor layout is already deep; do not prepend pytest's long test name
    # or require an operator to change Windows long-path policy to run tests.
    tmp_path = tmp_path_factory.mktemp("v")
    monkeypatch.delenv("DISCOVERY_CLIO_EXE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(clio_driver.shutil, "which", lambda _: None)
    root = tmp_path / "Programs" / "Discovery App - Preview"
    for app_version, extension_version in versions:
        selected = _executable(
            root / app_version / "extensions" / f"discovery-app.discovery-app-{extension_version}"
            / "dist" / "clio-plugin" / "plugins" / "clio" / "bin" / "windows-x64"
            / "Science.Autopilot.exe",
        )
    assert clio_driver.exe() == str(selected)


def test_missing_clio_has_actionable_error(monkeypatch):
    monkeypatch.delenv("DISCOVERY_CLIO_EXE", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(clio_driver.shutil, "which", lambda _: None)
    with pytest.raises(FileNotFoundError, match="--clio-executable / DISCOVERY_CLIO_EXE"):
        clio_driver.exe()


def test_run_passes_optional_executable_without_changing_default_fake_interface(
    tmp_path, monkeypatch,
):
    selected = tmp_path / "operator-selected.exe"
    observed = []

    class SelectedClient(FakeClient):
        def __init__(self, cwd, log, *, clio_executable):
            super().__init__(cwd, log)
            observed.append(clio_executable)

    FakeClient.waits = []
    monkeypatch.setattr(clio_driver, "Client", SelectedClient)
    result = clio_driver.run("test", tmp_path / "out", cwd=tmp_path, clio_executable=selected)
    assert result["state"] == "done" and observed == [selected]


def test_cli_executable_option_is_forwarded_without_starting_clio(tmp_path, monkeypatch):
    manifest = result_paths.load_guard(tmp_path).initialize(tmp_path, "clio", exact=True)
    results = Path(manifest["results_root"])
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("synthetic objective", encoding="utf-8")
    observed = {}

    def fake_run(text, out, **kwargs):
        observed.update(text=text, out=out, **kwargs)
        return {"state": "done"}

    monkeypatch.setattr(clio_driver, "run", fake_run)
    monkeypatch.setenv("DISCOVERY_PHYSICS_RUNS", "original-store")
    assert clio_driver.main([
        "run", str(prompt), "--out", str(results / "analysis" / "clio"),
        "--project-root", str(tmp_path.resolve()), "--results-dir", str(results),
        "--cwd", str(tmp_path.resolve()),
        "--clio-executable", "selected-clio",
    ]) == 0
    assert observed["clio_executable"] == "selected-clio"
    assert observed["cwd"] == tmp_path.resolve()
    assert observed["env"]["DISCOVERY_PHYSICS_RUNS"] == str(results / "runs")
    assert clio_driver.os.environ["DISCOVERY_PHYSICS_RUNS"] == "original-store"