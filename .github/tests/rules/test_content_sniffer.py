"""content_sniffer — magic-byte and text-heuristic classification.

These tests pin the behaviour POL-008 depends on: a binary must be detected
from its bytes, and an ASCII-looking signature must not misclassify real text.
"""

from __future__ import annotations

import pytest
from conftest import (
    ELF_BYTES,
    GZIP_BYTES,
    PDF_BYTES,
    PE_BYTES,
    PNG_BYTES,
    SQLITE_BYTES,
    WASM_BYTES,
    ZIP_BYTES,
    write,
)

from content_sniffer import (
    PRINTABLE_RATIO_THRESHOLD,
    classify,
    classify_bytes,
)


def _classify_bytes(payload: bytes, suffix: str = ""):
    return classify_bytes(payload[:512], payload, suffix)


# ── Magic signatures ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("payload,expected_format", [
    (ELF_BYTES, "elf"),
    (PE_BYTES, "pe"),
    (ZIP_BYTES, "zip"),
    (GZIP_BYTES, "gzip"),
    (PNG_BYTES, "png"),
    (PDF_BYTES, "pdf"),
    (SQLITE_BYTES, "sqlite"),
    (WASM_BYTES, "wasm"),
    (b"BZh91AY&SY" + b"\x00" * 20, "bzip2"),
    (b"\xfd7zXZ\x00" + b"\x00" * 20, "xz"),
    (b"7z\xbc\xaf\x27\x1c" + b"\x00" * 20, "7z"),
    (b"Rar!\x1a\x07\x00" + b"\x00" * 20, "rar"),
    (b"\x93NUMPY\x01\x00" + b"\x00" * 20, "npy"),
    (b"\x89HDF\r\n\x1a\n" + b"\x00" * 20, "hdf5"),
    (b"\xed\xab\xee\xdb" + b"\x00" * 20, "rpm"),
    (b"!<arch>\n" + b"\x00" * 20, "ar"),
])
def test_known_binary_formats_are_identified(payload, expected_format):
    result = _classify_bytes(payload)
    assert result.is_binary
    assert result.format == expected_format


def test_iso_signature_beyond_the_sample_window_is_detected(repo):
    rel = write(repo, "sample.txt", b"A" * 32769 + b"CD001" + b"A" * 100)
    result = classify(repo / rel)
    assert result.is_binary
    assert result.format == "iso"


# ── ASCII-ambiguous signatures must not eat legitimate text ──────────────────

@pytest.mark.parametrize("text", [
    "MZ is the two-letter prefix used by DOS executables.\n",
    "RIFF containers are described in the multimedia section.\n",
    "ID3 tags store MP3 metadata.\n",
    "BM is the BMP magic; this document merely mentions it.\n",
    "GIF87a and GIF89a are the two GIF versions.\n",
    "GGUF is the llama.cpp weight format.\n",
])
def test_text_beginning_with_an_ascii_signature_stays_text(text):
    result = _classify_bytes(text.encode("utf-8"), ".md")
    assert result.kind == "text"
    assert not result.spoofed


def test_real_pe_binary_is_still_caught_despite_ascii_magic():
    result = _classify_bytes(PE_BYTES, ".txt")
    assert result.is_binary
    assert result.spoofed


# ── Text heuristics ──────────────────────────────────────────────────────────

def test_plain_ascii_source_is_text():
    result = _classify_bytes(b"def main():\n    return 1\n", ".py")
    assert result.kind == "text"


def test_multibyte_utf8_is_text():
    payload = "# Démo — Ångström\n中文说明。\nΔG = -12.4 kJ/mol\n".encode("utf-8")
    result = _classify_bytes(payload, ".md")
    assert result.kind == "text"


def test_nul_byte_makes_content_binary():
    result = _classify_bytes(b"looks like text\x00but is not", ".txt")
    assert result.is_binary
    assert "NUL" in result.detail


def test_invalid_utf8_is_binary():
    result = _classify_bytes(b"\xc3\x28\xa0\xa1\xf0\x28\x8c\x28" * 8, ".txt")
    assert result.is_binary


def test_low_printable_ratio_is_binary():
    # Valid UTF-8 made almost entirely of control characters.
    payload = bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x0B]) * 64
    result = _classify_bytes(payload.replace(b"\x00", b"\x01"), ".txt")
    assert result.is_binary


def test_threshold_is_a_meaningful_value():
    assert 0.5 < PRINTABLE_RATIO_THRESHOLD <= 1.0


def test_empty_content_is_neither_text_nor_binary():
    result = _classify_bytes(b"")
    assert result.kind == "empty"
    assert not result.is_binary


# ── Spoofing signal ──────────────────────────────────────────────────────────

def test_binary_with_binary_extension_is_not_marked_spoofed():
    assert not _classify_bytes(PNG_BYTES, ".png").spoofed


def test_binary_with_text_extension_is_marked_spoofed():
    assert _classify_bytes(PNG_BYTES, ".md").spoofed


def test_text_with_binary_extension_is_marked_spoofed():
    assert _classify_bytes(b"just text\n", ".png").spoofed


def test_unreadable_path_is_reported_not_raised(tmp_path):
    result = classify(tmp_path / "does-not-exist.txt")
    assert result.is_binary
    assert result.format == "unreadable"
