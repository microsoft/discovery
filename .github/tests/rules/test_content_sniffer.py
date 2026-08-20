"""content_sniffer - file/libmagic classification and policy adaptation."""

from __future__ import annotations

import shutil
import subprocess

import content_sniffer
import pytest
from conftest import write

from content_sniffer import FILE_MAX_BYTES, Classification, classify


def _mock_file(monkeypatch, output: str, *, returncode: int = 0):
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout=output,
            stderr="libmagic failed" if returncode else "",
        )

    monkeypatch.setattr(content_sniffer.subprocess, "run", run)
    return calls


def test_file_invocation_is_bounded_and_does_not_decompress(repo, monkeypatch):
    rel = write(repo, "sample.py", "print('hello')\n")
    calls = _mock_file(monkeypatch, "text/x-script.python; charset=us-ascii\n")

    result = classify(repo / rel)

    assert result.kind == "text"
    assert calls == [[
        "file",
        "--brief",
        "--mime",
        "--parameter",
        f"bytes={FILE_MAX_BYTES}",
        "--",
        str(repo / rel),
    ]]


@pytest.mark.parametrize("mime_type", [
    "application/x-executable",
    "application/x-java-serialized-object",
    "image/avif",
    "image/tiff",
])
def test_libmagic_binary_formats_are_blockable(repo, monkeypatch, mime_type):
    rel = write(repo, "payload.txt", b"binary payload")
    _mock_file(monkeypatch, f"{mime_type}; charset=binary\n")

    result = classify(repo / rel)

    assert result == Classification(
        kind="binary",
        format=mime_type,
        detail=f"Content identified by libmagic as {mime_type}.",
        spoofed=True,
    )


def test_binary_extension_is_not_reported_as_disguised(repo, monkeypatch):
    rel = write(repo, "image.tiff", b"binary payload")
    _mock_file(monkeypatch, "image/tiff; charset=binary\n")

    assert not classify(repo / rel).spoofed


def test_text_with_binary_extension_is_reported_as_disguised(repo, monkeypatch):
    rel = write(repo, "image.png", b"plain text\n")
    _mock_file(monkeypatch, "text/plain; charset=us-ascii\n")

    result = classify(repo / rel)

    assert result.kind == "text"
    assert result.spoofed


@pytest.mark.parametrize("mime_type", [
    "application/javascript",
    "application/x-wine-extension-ini",
])
def test_libmagic_text_application_types_are_accepted(
    repo, monkeypatch, mime_type
):
    rel = write(repo, "source.txt", b"plain text\n")
    _mock_file(monkeypatch, f"{mime_type}; charset=us-ascii\n")

    assert classify(repo / rel).kind == "text"


def test_non_utf8_charset_is_deferred_to_pol_020(repo, monkeypatch):
    rel = write(repo, "legacy.txt", b"legacy content")
    _mock_file(monkeypatch, "text/plain; charset=iso-8859-1\n")

    result = classify(repo / rel)

    assert result.is_binary
    assert result.format == "unknown-binary"


def test_binary_mime_wins_over_textual_charset(repo, monkeypatch):
    rel = write(repo, "document.txt", b"PDF content")
    _mock_file(monkeypatch, "application/pdf; charset=iso-8859-1\n")

    result = classify(repo / rel)

    assert result.is_binary
    assert result.format == "application/pdf"


def test_generic_binary_data_is_deferred_to_pol_020(repo, monkeypatch):
    rel = write(repo, "source.md", b"text with an unsafe byte")
    _mock_file(monkeypatch, "application/octet-stream; charset=binary\n")

    result = classify(repo / rel)

    assert result.is_binary
    assert result.format == "unknown-binary"


def test_empty_file_does_not_invoke_libmagic(repo, monkeypatch):
    rel = write(repo, "empty.txt", b"")
    monkeypatch.setattr(
        content_sniffer.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("file should not be invoked"),
    )

    result = classify(repo / rel)

    assert result.kind == "empty"


def test_missing_file_command_fails_closed(repo, monkeypatch):
    rel = write(repo, "sample.txt", b"content")

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("file command was not found")

    monkeypatch.setattr(content_sniffer.subprocess, "run", missing)

    result = classify(repo / rel)

    assert result.is_binary
    assert result.format == "classifier-error"
    assert "file command was not found" in result.detail


def test_libmagic_failure_fails_closed(repo, monkeypatch):
    rel = write(repo, "sample.txt", b"content")
    _mock_file(monkeypatch, "", returncode=1)

    result = classify(repo / rel)

    assert result.is_binary
    assert result.format == "classifier-error"
    assert "libmagic failed" in result.detail


def test_unexpected_libmagic_output_fails_closed(repo, monkeypatch):
    rel = write(repo, "sample.txt", b"content")
    _mock_file(monkeypatch, "text/plain\n")

    result = classify(repo / rel)

    assert result.is_binary
    assert result.format == "classifier-error"


@pytest.mark.skipif(shutil.which("file") is None, reason="requires file/libmagic")
def test_real_libmagic_identifies_tiff_beyond_old_signature_table(repo):
    rel = write(repo, "payload.txt", b"II*\x00\x08\x00\x00\x00\x00\x00")

    result = classify(repo / rel)

    assert result.is_binary
    assert result.format == "image/tiff"
    assert result.spoofed


def test_unreadable_path_is_reported_not_raised(tmp_path):
    result = classify(tmp_path / "does-not-exist.txt")

    assert result.is_binary
    assert result.format == "classifier-error"