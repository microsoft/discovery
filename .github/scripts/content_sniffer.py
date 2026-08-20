#!/usr/bin/env python3
"""Content classification for POL-008 using the file/libmagic utility."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


FILE_COMMAND = "file"
FILE_MAX_BYTES = 64 * 1024
FILE_TIMEOUT_SECONDS = 10

# Extensions whose content is expected to be binary. This only determines
# whether the content is disguised; libmagic decides the content type.
_EXPECTED_BINARY_EXTENSIONS = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".lib", ".class",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".zst",
    ".iso", ".img", ".dmg", ".pkg", ".deb", ".rpm", ".msi", ".whl", ".jar",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".pdf",
    ".mp3", ".mp4", ".avi", ".mov", ".webm", ".ogg", ".wav", ".flac",
    ".tif", ".tiff", ".avif", ".heic",
    ".xlsx", ".docx", ".pptx", ".db", ".sqlite", ".pyc", ".pyo", ".wasm",
    ".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".pb", ".h5", ".hdf5",
    ".pkl", ".joblib", ".npy", ".npz", ".gguf", ".tflite", ".engine", ".weights",
})

_UTF8_ENCODINGS = frozenset({"us-ascii", "utf-8"})
_TEXT_MIME_TYPES = frozenset({
    "application/javascript",
    "application/json",
    "application/xml",
    "application/x-ndjson",
    "application/x-wine-extension-ini",
    "application/x-yaml",
    "application/yaml",
    "image/svg+xml",
})


@dataclass(frozen=True)
class Classification:
    """Outcome of classifying one file."""

    kind: str
    format: str
    detail: str
    spoofed: bool = False

    @property
    def is_binary(self) -> bool:
        return self.kind == "binary"


def _classifier_error(detail: str) -> Classification:
    return Classification(
        kind="binary",
        format="classifier-error",
        detail=f"Could not classify content with file/libmagic: {detail}",
    )


def _is_text_mime(mime_type: str) -> bool:
    return (
        mime_type.startswith("text/")
        or mime_type in _TEXT_MIME_TYPES
        or mime_type.endswith(("+json", "+xml", "+yaml"))
    )


def _from_mime_output(output: str, suffix: str) -> Classification:
    mime_type, separator, charset_value = output.partition(";")
    mime_type = mime_type.strip().lower()
    charset_key, charset_separator, charset = charset_value.strip().partition("=")
    charset = charset.strip().lower()

    if (
        not separator
        or not mime_type
        or not charset_separator
        or charset_key.strip().lower() != "charset"
        or not charset
    ):
        return _classifier_error(f"unexpected output {output!r}")

    expected_binary = suffix in _EXPECTED_BINARY_EXTENSIONS
    if mime_type == "application/octet-stream":
        return Classification(
            kind="binary",
            format="unknown-binary",
            detail=(
                "libmagic reported generic binary data; POL-020 will verify "
                "whether the content is malformed or unsafe text."
            ),
            spoofed=not expected_binary,
        )

    if not _is_text_mime(mime_type):
        return Classification(
            kind="binary",
            format=mime_type,
            detail=f"Content identified by libmagic as {mime_type}.",
            spoofed=not expected_binary,
        )

    if charset not in _UTF8_ENCODINGS:
        return Classification(
            kind="binary",
            format="unknown-binary",
            detail=(
                f"libmagic reported {mime_type} with charset {charset}; "
                "POL-020 will verify that the content is valid UTF-8."
            ),
            spoofed=not expected_binary,
        )

    return Classification(
        kind="text",
        format="utf-8-text",
        detail=f"Content identified by libmagic as {mime_type}; charset={charset}.",
        spoofed=expected_binary,
    )


def classify(path: Path) -> Classification:
    """Classify a path with a bounded, non-decompressing libmagic scan."""
    try:
        if path.stat().st_size == 0:
            return Classification("empty", "empty", "File is empty.")
    except OSError as error:
        return _classifier_error(str(error))

    command = [
        FILE_COMMAND,
        "--brief",
        "--mime",
        "--parameter",
        f"bytes={FILE_MAX_BYTES}",
        "--",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=FILE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _classifier_error(f"timed out after {FILE_TIMEOUT_SECONDS} seconds")
    except OSError as error:
        return _classifier_error(str(error))

    if result.returncode != 0:
        detail = result.stderr.strip() or f"exited with status {result.returncode}"
        return _classifier_error(detail)

    return _from_mime_output(result.stdout.strip(), path.suffix.lower())