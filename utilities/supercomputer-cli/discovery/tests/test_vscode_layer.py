"""Tests for vscode_layer helpers."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from discovery.poll import vscode_layer


def test_prepare_vscode_layer_creates_dockerfile(tmp_path, monkeypatch) -> None:
    def fake_download(dest: Path) -> Path:
        code = dest / "code"
        dest.mkdir(parents=True, exist_ok=True)
        code.write_text("#!/bin/sh\n", encoding="utf-8")
        return code

    monkeypatch.setattr(vscode_layer, "download_vscode_cli", fake_download)
    wrapper_dest = vscode_layer.prepare_vscode_layer("registry.azurecr.io/image:tag", tmp_path)
    dockerfile = tmp_path / "Dockerfile"
    contents = dockerfile.read_text(encoding="utf-8")
    assert "FROM registry.azurecr.io/image:tag" in contents
    assert "start-vscode-tunnel.sh" in contents
    assert (tmp_path / "bin" / "code").exists()
    assert (tmp_path / "bin" / "start-vscode-tunnel.sh").exists()
    assert wrapper_dest == vscode_layer.WRAPPER_TARGET_PATH
    # Verify wrapper script supports named mode and optional --provider
    wrapper_content = (tmp_path / "bin" / "start-vscode-tunnel.sh").read_text(encoding="utf-8")
    assert "--name" in wrapper_content
    assert "--provider" in wrapper_content


def test_build_named_tunnel_command() -> None:
    cmd = vscode_layer.build_named_tunnel_command("echo hi", "my-gpu-box")
    assert vscode_layer.WRAPPER_TARGET_PATH in cmd
    assert "--name" in cmd
    assert "my-gpu-box" in cmd
    assert "echo hi" in cmd
    # Should NOT contain --tunnel-id or --host-token
    assert "--tunnel-id" not in cmd
    assert "--host-token" not in cmd
    # Default (no provider) must not forward --provider, preserving
    # backward compatibility with wrappers built before the flag existed.
    assert "--provider" not in cmd


def test_build_named_tunnel_command_with_github_provider() -> None:
    cmd = vscode_layer.build_named_tunnel_command(
        "echo hi", "my-gpu-box", provider="github"
    )
    assert "--provider github" in cmd


def test_build_named_tunnel_command_with_microsoft_provider() -> None:
    cmd = vscode_layer.build_named_tunnel_command(
        "echo hi", "my-gpu-box", provider="microsoft"
    )
    assert "--provider microsoft" in cmd
    # tunnel name still present and properly quoted
    assert "--name" in cmd
    assert "my-gpu-box" in cmd


def test_download_vscode_cli(tmp_path, monkeypatch) -> None:
    archive = tmp_path / "archive.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        data = b"#!/bin/sh\n"
        info = tarfile.TarInfo("code-server-linux-x64/bin/code")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))

    def fake_urlretrieve(url, filename):
        Path(filename).write_bytes(archive.read_bytes())
        return filename, {
            "url": url,
        }

    monkeypatch.setattr(vscode_layer.urllib.request, "urlretrieve", fake_urlretrieve)
    path = vscode_layer.download_vscode_cli(tmp_path)
    assert path.exists()
    assert path.name == "code"
