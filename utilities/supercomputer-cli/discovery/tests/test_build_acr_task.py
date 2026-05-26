"""Tests for build_acr_task helper functions."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from discovery.poll import build_acr_task


def test_ensure_az_cli_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_acr_task.shutil, "which", lambda name: None)
    with pytest.raises(build_acr_task.typer.Exit) as exc:
        build_acr_task.ensure_az_cli()
    assert exc.value.exit_code == 4


def test_ensure_az_cli_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_acr_task.shutil, "which", lambda name: "/usr/bin/az")
    build_acr_task.ensure_az_cli()


def test_list_acr_names(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "alpha\n beta \n"
            self.stderr = ""

    monkeypatch.setattr(build_acr_task, "run_az", lambda args: Proc())
    names = build_acr_task.list_acr_names()
    assert names == ["alpha", "beta"]


def test_get_acr_login_server(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        def __init__(self) -> None:
            self.returncode = 0
            self.stdout = "myacr.azurecr.cn\n"
            self.stderr = ""

    monkeypatch.setattr(build_acr_task, "run_az", lambda args: Proc())
    assert build_acr_task.get_acr_login_server("myacr") == "myacr.azurecr.cn"


def test_get_acr_login_server_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        def __init__(self) -> None:
            self.returncode = 1
            self.stdout = ""
            self.stderr = ""

    monkeypatch.setattr(build_acr_task, "run_az", lambda args: Proc())
    assert build_acr_task.get_acr_login_server("myacr") == "myacr.azurecr.io"


def test_write_env_value_updates(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ACR_NAME=old\nOTHER=value\n", encoding="utf-8")
    build_acr_task.write_env_value(env_file, "ACR_NAME", "new", force=False)
    text = env_file.read_text(encoding="utf-8")
    assert "ACR_NAME=old" in text
    build_acr_task.write_env_value(env_file, "ACR_NAME", "new", force=True)
    assert "ACR_NAME=new" in env_file.read_text(encoding="utf-8")
    build_acr_task.write_env_value(env_file, "ADDED", "1", force=False)
    assert "ADDED=1" in env_file.read_text(encoding="utf-8")


def test_select_registry_interactive(monkeypatch: pytest.MonkeyPatch) -> None:
    sequence = iter(["2"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(sequence))
    monkeypatch.setattr(build_acr_task.typer, "echo", lambda *args, **kwargs: None)
    choice = build_acr_task.select_registry_interactive(["one", "two", "three"])
    assert choice == "two"


def test_acr_registry_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        def __init__(self, code: int) -> None:
            self.returncode = code

    monkeypatch.setattr(build_acr_task, "run_az", lambda args: Proc(0))
    assert build_acr_task.acr_registry_exists("acr") is True
    monkeypatch.setattr(build_acr_task, "run_az", lambda args: Proc(1))
    assert build_acr_task.acr_registry_exists("acr") is False


def test_build_image_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class Proc:
        def __init__(self, code: int) -> None:
            self.returncode = code

    commands: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(cmd, **kwargs):
        commands.append((cmd, kwargs))
        return Proc(0)

    class FakeUUID:
        hex = "deadbeef"

    monkeypatch.setattr(build_acr_task.uuid, "uuid4", lambda: FakeUUID())
    monkeypatch.setattr(build_acr_task.subprocess, "run", fake_run)
    rc = build_acr_task.build_image("acr", "img", "tag", tmp_path)
    assert rc == 0
    cmd, kwargs = commands[0]
    assert cmd[:5] == ["az", "acr", "run", "--registry", "acr"]
    assert cmd[5] == "--file"
    assert cmd[6] == ".acr-task-deadbeef.yaml"
    assert kwargs["cwd"] == str(tmp_path.resolve())
    assert not (tmp_path / ".acr-task-deadbeef.yaml").exists()


def test_build_image_with_login_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Build image uses login_server when provided instead of hardcoded .azurecr.io."""

    class Proc:
        def __init__(self, code: int) -> None:
            self.returncode = code

    output: list[str] = []
    monkeypatch.setattr(build_acr_task.typer, "secho", lambda msg, **kw: output.append(msg))
    class FakeUUID:
        hex = "ab"

    monkeypatch.setattr(build_acr_task.uuid, "uuid4", lambda: FakeUUID())
    monkeypatch.setattr(build_acr_task.subprocess, "run", lambda cmd, **kw: Proc(0))

    rc = build_acr_task.build_image(
        "acr", "img", "tag", tmp_path, login_server="acr.azurecr.cn"
    )
    assert rc == 0
    assert any("acr.azurecr.cn/img:tag" in s for s in output)


def test_build_image_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class Proc:
        def __init__(self, code: int) -> None:
            self.returncode = code

    class FakeUUID:
        hex = "feedface"

    monkeypatch.setattr(build_acr_task.uuid, "uuid4", lambda: FakeUUID())
    monkeypatch.setattr(build_acr_task.subprocess, "run", lambda cmd, **kwargs: Proc(1))
    rc = build_acr_task.build_image("acr", "img", "tag", tmp_path)
    assert rc == 4
    assert not (tmp_path / ".acr-task-feedface.yaml").exists()


def test_execute_build_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Test execute_build cancellation via typer.confirm."""
    monkeypatch.setattr(build_acr_task, "ensure_az_cli", lambda: None)
    monkeypatch.setattr(build_acr_task, "acr_registry_exists", lambda name: True)
    monkeypatch.setattr(build_acr_task, "build_image", lambda *args, **kwargs: 0)
    # Simulate user declining the confirmation prompt
    monkeypatch.setattr(build_acr_task.typer, "confirm", lambda *args, **kwargs: False)

    with pytest.raises(build_acr_task.typer.Exit) as exc:
        build_acr_task.execute_build(
            context=tmp_path,
            image="img",
            tag="tag",
            acr_name="acr",
        )
    assert exc.value.exit_code == 0


def test_execute_build_success(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(build_acr_task, "ensure_az_cli", lambda: None)
    monkeypatch.setattr(build_acr_task, "acr_registry_exists", lambda name: True)
    monkeypatch.setattr(build_acr_task.typer, "confirm", lambda *args, **kwargs: True)
    calls: list[tuple] = []
    monkeypatch.setattr(build_acr_task, "build_image", lambda *args: (calls.append(args), 0)[1])
    rc = build_acr_task.execute_build(
        context=tmp_path,
        image="img",
        tag="tag",
        acr_name="acr",
    )
    assert rc == 0
    assert calls[0][0] == "acr"


def test_execute_build_with_vscode(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(build_acr_task, "ensure_az_cli", lambda: None)
    monkeypatch.setattr(build_acr_task, "acr_registry_exists", lambda name: True)
    monkeypatch.setattr(build_acr_task.typer, "confirm", lambda *args, **kwargs: True)
    build_calls: list[tuple] = []

    def fake_build(*args):
        build_calls.append(args)
        return 0

    monkeypatch.setattr(build_acr_task, "build_image", fake_build)

    prepared = {"called": False}
    monkeypatch.setattr(build_acr_task, "prepare_vscode_layer", lambda *args: prepared.update({"called": True}))

    class FakeTempDir:
        def __init__(self, path: Path) -> None:
            self._path = path

        def __enter__(self) -> str:
            self._path.mkdir(parents=True, exist_ok=True)
            return str(self._path)

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    temp_dir = tmp_path / "vscode"
    monkeypatch.setattr(build_acr_task.tempfile, "TemporaryDirectory", lambda prefix: FakeTempDir(temp_dir))

    rc = build_acr_task.execute_build(
        context=tmp_path,
        image="img",
        tag="tag",
        acr_name="acr",
        vscode=True,
    )
    assert rc == 0
    assert prepared["called"] is True
    assert len(build_calls) == 2
