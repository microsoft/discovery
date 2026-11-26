"""Tests for build_acr_task helper functions."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

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


@pytest.mark.parametrize("local", [False, True])
def test_execute_build_dry_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, local: bool
) -> None:
    """Test execute_build cancellation via typer.confirm."""
    monkeypatch.setattr(build_acr_task, "ensure_az_cli", lambda: None)
    monkeypatch.setattr(build_acr_task, "acr_registry_exists", lambda name: True)
    build = MagicMock()
    docker = MagicMock()
    monkeypatch.setattr(build_acr_task, "build_image", build)
    monkeypatch.setattr(build_acr_task, "ensure_docker_cli", docker)
    # Simulate user declining the confirmation prompt
    monkeypatch.setattr(build_acr_task.typer, "confirm", lambda *args, **kwargs: False)

    with pytest.raises(build_acr_task.typer.Exit) as exc:
        build_acr_task.execute_build(
            context=tmp_path,
            image="img",
            tag="tag",
            acr_name="acr",
            local=local,
        )
    assert exc.value.exit_code == 0
    build.assert_not_called()
    docker.assert_not_called()


def test_execute_build_success(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(build_acr_task, "ensure_az_cli", lambda: None)
    monkeypatch.setattr(build_acr_task, "acr_registry_exists", lambda name: True)
    monkeypatch.setattr(build_acr_task.typer, "confirm", lambda *args, **kwargs: True)
    docker = MagicMock()
    monkeypatch.setattr(build_acr_task, "ensure_docker_cli", docker)
    calls: list[tuple] = []
    monkeypatch.setattr(
        build_acr_task, "build_image", lambda *args, **kwargs: (calls.append(args), 0)[1]
    )
    rc = build_acr_task.execute_build(
        context=tmp_path,
        image="img",
        tag="tag",
        acr_name="acr",
    )
    assert rc == 0
    assert calls[0][0] == "acr"
    docker.assert_not_called()


def test_execute_build_with_vscode(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(build_acr_task, "ensure_az_cli", lambda: None)
    monkeypatch.setattr(build_acr_task, "acr_registry_exists", lambda name: True)
    monkeypatch.setattr(build_acr_task.typer, "confirm", lambda *args, **kwargs: True)
    build_calls: list[tuple] = []

    def fake_build(*args, **kwargs):
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


@pytest.mark.parametrize("vscode", [False, True])
def test_execute_build_local_uses_context_and_publishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, vscode: bool
) -> None:
    """Local mode preserves context, tags and layering without scheduling an ACR task."""
    context = tmp_path / "context with spaces & shell"
    context.mkdir()
    dockerfile = context / "Dockerfile"
    dockerfile.write_text("FROM scratch\nCOPY input /input\n", encoding="utf-8")
    dockerignore = context / ".dockerignore"
    dockerignore.write_text("ignored\n", encoding="utf-8")
    monkeypatch.setattr(build_acr_task, "ensure_az_cli", lambda: None)
    monkeypatch.setattr(build_acr_task, "acr_registry_exists", lambda name: True)
    monkeypatch.setattr(build_acr_task.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(build_acr_task.typer, "confirm", lambda *args, **kwargs: True)
    monkeypatch.setenv("LOCAL_BUILD_TEST", "preserved")
    run = MagicMock(return_value=subprocess.CompletedProcess([], 0))
    prepare = MagicMock(return_value="/usr/local/bin/start-vscode-tunnel.sh")
    monkeypatch.setattr(build_acr_task.subprocess, "run", run)
    monkeypatch.setattr(build_acr_task, "prepare_vscode_layer", prepare)

    rc = build_acr_task.execute_build(
        context=context,
        image="team/img:v2",
        acr_name="acr",
        vscode=vscode,
        timeout=123,
        login_server="acr.azurecr.cn",
        local=True,
    )

    assert rc == 0
    full_image = "acr.azurecr.cn/team/img:v2"
    base_image = f"{full_image}-temp" if vscode else full_image
    build_args = ["docker", "build", "--load", "--platform", "linux/amd64", "--tag"]
    expected = [
        ["docker", "info", "--format", "Docker daemon: {{.OSType}}"],
        [*build_args, base_image, "."],
        ["docker", "push", base_image],
    ]
    if vscode:
        expected.extend(
            [
                [*build_args, full_image, "."],
                ["docker", "push", full_image],
            ]
        )
        layer_context = run.call_args_list[3].kwargs["cwd"]
        prepare.assert_called_once()
        assert prepare.call_args.args[0] == base_image
        assert prepare.call_args.args[1].resolve() == layer_context
        assert not layer_context.exists()
    else:
        prepare.assert_not_called()
    assert [call.args[0] for call in run.call_args_list] == expected
    assert run.call_args_list[1].kwargs["cwd"] == context.resolve()
    for call in run.call_args_list[1:]:
        assert call.kwargs["timeout"] == 123
        assert call.kwargs["check"] is False
        assert call.kwargs["env"]["DOCKER_BUILDKIT"] == "1"
        assert call.kwargs["env"]["LOCAL_BUILD_TEST"] == "preserved"
        assert not call.kwargs.get("shell")
        assert "capture_output" not in call.kwargs
    assert dockerfile.read_text(encoding="utf-8") == "FROM scratch\nCOPY input /input\n"
    assert dockerignore.read_text(encoding="utf-8") == "ignored\n"
    assert sorted(path.name for path in context.iterdir()) == [".dockerignore", "Dockerfile"]


@pytest.mark.parametrize("local", [False, True])
@pytest.mark.parametrize("retarget", [False, True])
def test_execute_rebuild_uses_selected_backend(
    monkeypatch: pytest.MonkeyPatch, local: bool, retarget: bool
) -> None:
    """Rebuild shares the same layer context, target reference and publishing backend."""
    monkeypatch.setattr(build_acr_task, "ensure_az_cli", lambda: None)
    monkeypatch.setattr(build_acr_task, "acr_registry_exists", lambda name: True)
    monkeypatch.setattr(build_acr_task.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(build_acr_task.typer, "confirm", lambda *args, **kwargs: True)
    run = MagicMock(return_value=subprocess.CompletedProcess([], 0))
    prepare = MagicMock(return_value="/usr/local/bin/start-vscode-tunnel.sh")
    monkeypatch.setattr(build_acr_task.subprocess, "run", run)
    monkeypatch.setattr(build_acr_task, "prepare_vscode_layer", prepare)

    rc = build_acr_task.execute_rebuild(
        image="img:v2",
        tag="latest",
        acr_name="acr",
        target_image="other" if retarget else None,
        target_tag="code" if retarget else None,
        login_server="acr.azurecr.cn",
        local=local,
    )

    assert rc == 0
    prepare.assert_called_once()
    base, context = prepare.call_args.args
    assert base == "acr.azurecr.cn/img:v2"
    assert not context.exists()
    commands = [call.args[0] for call in run.call_args_list]
    if local:
        full_image = "acr.azurecr.cn/other:code" if retarget else base
        assert commands[1] == [
            "docker",
            "build",
            "--load",
            "--platform",
            "linux/amd64",
            "--tag",
            full_image,
            ".",
        ]
        assert commands[2] == ["docker", "push", full_image]
        assert run.call_args_list[1].kwargs["cwd"] == context.resolve()
    else:
        assert len(commands) == 1
        assert commands[0][:5] == ["az", "acr", "run", "--registry", "acr"]
