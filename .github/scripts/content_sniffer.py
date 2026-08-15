#!/usr/bin/env python3
"""
content_sniffer.py — content-based file classification for POL-008.

Extension-based binary blocking is trivially bypassed: renaming ``payload.so``
to ``notes.txt`` defeats a suffix allow/deny list entirely. This module
classifies a file by what it *contains* — magic-byte signatures first, then a
text-decodability heuristic — so the classification cannot be spoofed by
renaming.

The module deliberately never parses, decompresses, or deserializes candidate
content. It reads a bounded prefix and, for the text heuristic, a bounded
sample. That keeps a hostile file from turning the validator into the exploit.

Public API:
    classify(path)      -> Classification
    classify_bytes(...) -> Classification
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# ── Tunables ─────────────────────────────────────────────────────────────────

# Bytes read for magic-signature matching. The longest signature we check sits
# at offset 257 (tar's "ustar"), so this must comfortably exceed that.
MAGIC_PREFIX_BYTES = 512

# Bytes sampled for the text heuristic. Large enough to be representative,
# small enough that a multi-GB file costs one read.
TEXT_SAMPLE_BYTES = 64 * 1024

# Minimum fraction of sampled bytes that must be printable/whitespace for a
# file to count as text. Source and data files sit far above this; compiled
# artifacts and compressed payloads sit far below.
PRINTABLE_RATIO_THRESHOLD = 0.90


# ── Classification result ────────────────────────────────────────────────────

@dataclass(frozen=True)
class Classification:
    """Outcome of sniffing one file.

    Attributes:
        kind:      One of "text", "binary", "empty".
        format:    Short identifier of the detected format, e.g. "elf",
                   "zip", "png", "utf-8-text". Never None.
        detail:    Human-readable explanation suitable for a PR comment.
        spoofed:   True when the on-disk extension implies a different
                   category than the content does. This is the signal that
                   someone renamed a binary to sneak it past a suffix check.
    """

    kind: str
    format: str
    detail: str
    spoofed: bool = False

    @property
    def is_binary(self) -> bool:
        return self.kind == "binary"


# ── Magic signatures ─────────────────────────────────────────────────────────

# (offset, signature bytes, format id, human label). Ordered most-specific
# first; the first match wins.
_MAGIC_SIGNATURES: tuple[tuple[int, bytes, str, str], ...] = (
    # Executables and objects
    (0, b"\x7fELF", "elf", "ELF executable/shared object"),
    (0, b"MZ", "pe", "Windows PE executable (EXE/DLL)"),
    (0, b"\xfe\xed\xfa\xce", "macho", "Mach-O executable (32-bit)"),
    (0, b"\xfe\xed\xfa\xcf", "macho", "Mach-O executable (64-bit)"),
    (0, b"\xce\xfa\xed\xfe", "macho", "Mach-O executable (32-bit, LE)"),
    (0, b"\xcf\xfa\xed\xfe", "macho", "Mach-O executable (64-bit, LE)"),
    (0, b"\xca\xfe\xba\xbe", "macho-fat", "Mach-O universal binary or Java class"),
    (0, b"\x00\x61\x73\x6d", "wasm", "WebAssembly module"),
    (0, b"!<arch>", "ar", "ar archive (.deb / static library)"),
    (0, b"\xed\xab\xee\xdb", "rpm", "RPM package"),

    # Archives and compression
    (0, b"PK\x03\x04", "zip", "ZIP archive (also .jar/.whl/.xlsx/.docx)"),
    (0, b"PK\x05\x06", "zip", "empty ZIP archive"),
    (0, b"PK\x07\x08", "zip", "spanned ZIP archive"),
    (0, b"\x1f\x8b", "gzip", "gzip archive"),
    (0, b"BZh", "bzip2", "bzip2 archive"),
    (0, b"\xfd7zXZ\x00", "xz", "xz archive"),
    (0, b"7z\xbc\xaf\x27\x1c", "7z", "7-Zip archive"),
    (0, b"Rar!\x1a\x07", "rar", "RAR archive"),
    (0, b"\x28\xb5\x2f\xfd", "zstd", "Zstandard archive"),
    (0, b"\x04\x22\x4d\x18", "lz4", "LZ4 archive"),
    (257, b"ustar", "tar", "tar archive"),

    # Disk and installer images
    (0, b"\x00\x01\x00\x00", "misc-bin", "binary resource (TrueType/ICO-like)"),
    (0, b"\xd0\xcf\x11\xe0", "ole", "OLE compound file (legacy Office/MSI)"),

    # Media and documents
    (0, b"%PDF-", "pdf", "PDF document"),
    (0, b"\x89PNG\r\n\x1a\n", "png", "PNG image"),
    (0, b"\xff\xd8\xff", "jpeg", "JPEG image"),
    (0, b"GIF87a", "gif", "GIF image"),
    (0, b"GIF89a", "gif", "GIF image"),
    (0, b"BM", "bmp", "BMP image"),
    (0, b"RIFF", "riff", "RIFF container (WebP/WAV/AVI)"),
    (0, b"\x1aE\xdf\xa3", "matroska", "Matroska/WebM container"),
    (0, b"OggS", "ogg", "Ogg container"),
    (0, b"ID3", "mp3", "MP3 audio"),

    # Databases, caches, model formats
    (0, b"SQLite format 3\x00", "sqlite", "SQLite database"),
    (0, b"\x93NUMPY", "npy", "NumPy .npy array"),
    (0, b"\x89HDF\r\n\x1a\n", "hdf5", "HDF5 archive"),
    (0, b"GGUF", "gguf", "GGUF model weights"),
    (0, b"\x08", "protobuf-maybe", "possible protobuf stream"),
)

# ISO 9660 stores its signature past the magic prefix but inside the text
# sample, so it is matched separately in classify().
_ISO_OFFSET = 32769
_ISO_MAGIC = b"CD001"

# Signatures too weak to act on at all — they collide with ordinary text and
# carry no corroborating structure.
_WEAK_FORMATS = frozenset({"protobuf-maybe", "misc-bin"})

# Signatures made entirely of printable ASCII. A legitimate text file could
# begin with these bytes by coincidence, so they only count as evidence of a
# binary when the content also fails the text test.
_ASCII_AMBIGUOUS_FORMATS = frozenset({
    "pe", "ar", "tar", "riff", "mp3", "bmp", "gif", "ogg", "gguf",
})

# Python bytecode has a version-dependent 2-byte magic followed by \r\n.
_PYC_SUFFIX = b"\r\n"

# Extensions whose content is expected to be binary. Used only to report
# spoofing, never to decide the classification.
_EXPECTED_BINARY_EXTENSIONS = frozenset({
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".lib", ".class",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".zst",
    ".iso", ".img", ".dmg", ".pkg", ".deb", ".rpm", ".msi", ".whl", ".jar",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".pdf",
    ".mp3", ".mp4", ".avi", ".mov", ".webm", ".ogg", ".wav",
    ".xlsx", ".docx", ".pptx", ".db", ".sqlite", ".pyc", ".pyo", ".wasm",
    ".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".pb", ".h5", ".hdf5",
    ".pkl", ".joblib", ".npy", ".npz", ".gguf", ".tflite", ".engine", ".weights",
})


def _match_magic(prefix: bytes) -> tuple[str, str, bool] | None:
    """Return (format_id, label, is_ambiguous) for the first signature match.

    ``is_ambiguous`` marks all-printable-ASCII signatures that need the text
    test to corroborate them before they can be treated as binary.
    """
    for offset, sig, fmt, label in _MAGIC_SIGNATURES:
        if fmt in _WEAK_FORMATS:
            continue
        end = offset + len(sig)
        if len(prefix) >= end and prefix[offset:end] == sig:
            return fmt, label, fmt in _ASCII_AMBIGUOUS_FORMATS

    # Python bytecode: 2-byte version magic, then \r\n at offset 2. The NUL
    # check below catches these anyway; this only improves the message.
    if len(prefix) >= 16 and prefix[2:4] == _PYC_SUFFIX and b"\x00" in prefix[:16]:
        return "pyc", "Python compiled bytecode", False

    return None


def _printable_ratio(sample: bytes) -> float:
    """Fraction of bytes that are printable ASCII, common whitespace, or
    part of a valid multi-byte UTF-8 sequence."""
    if not sample:
        return 1.0
    printable = 0
    for b in sample:
        # Tab, LF, CR, FF, and the printable ASCII range.
        if b in (0x09, 0x0A, 0x0C, 0x0D) or 0x20 <= b <= 0x7E:
            printable += 1
        elif b >= 0x80:
            # Assume UTF-8 continuation/lead bytes are legitimate text; the
            # decode check below is the authority on whether that holds.
            printable += 1
    return printable / len(sample)


def classify_bytes(prefix: bytes, sample: bytes, suffix: str = "") -> Classification:
    """Classify content from an already-read prefix and sample.

    Args:
        prefix: First ``MAGIC_PREFIX_BYTES`` (or fewer) of the file.
        sample: Up to ``TEXT_SAMPLE_BYTES`` used for the text heuristic.
        suffix: Lowercased file extension, used only for spoofing detection.
    """
    if not prefix and not sample:
        return Classification("empty", "empty", "File is empty.")

    expected_binary = suffix in _EXPECTED_BINARY_EXTENSIONS

    # Decide text-ness first so ASCII-ambiguous signatures can be corroborated.
    has_nul = b"\x00" in sample
    try:
        sample.decode("utf-8")
        decodes = True
    except UnicodeDecodeError:
        decodes = False
    ratio = _printable_ratio(sample)
    looks_like_text = (
        not has_nul and decodes and ratio >= PRINTABLE_RATIO_THRESHOLD
    )

    magic = _match_magic(prefix)
    if magic:
        fmt, label, ambiguous = magic
        if not (ambiguous and looks_like_text):
            return Classification(
                kind="binary",
                format=fmt,
                detail=f"Content identified as {label} by magic-byte signature.",
                spoofed=not expected_binary,
            )

    if has_nul:
        return Classification(
            kind="binary",
            format="unknown-binary",
            detail="Content contains NUL bytes and is not decodable text.",
            spoofed=not expected_binary,
        )

    if not decodes:
        return Classification(
            kind="binary",
            format="unknown-binary",
            detail=(
                "Content is not valid UTF-8 "
                f"(printable-byte ratio {ratio:.2f}). Only UTF-8 text source "
                "files are accepted."
            ),
            spoofed=not expected_binary,
        )

    if ratio < PRINTABLE_RATIO_THRESHOLD:
        return Classification(
            kind="binary",
            format="unknown-binary",
            detail=(
                f"Content has a printable-byte ratio of {ratio:.2f}, below the "
                f"{PRINTABLE_RATIO_THRESHOLD:.2f} threshold for text files."
            ),
            spoofed=not expected_binary,
        )

    return Classification(
        kind="text",
        format="utf-8-text",
        detail="Content is valid UTF-8 text.",
        # A .png that contains text is still wrong, just in the other direction.
        spoofed=expected_binary,
    )


def classify(path: Path) -> Classification:
    """Classify a file on disk. Never parses or executes the content."""
    try:
        with open(path, "rb") as fh:
            sample = fh.read(TEXT_SAMPLE_BYTES)
    except OSError as e:
        return Classification("binary", "unreadable", f"Could not read file: {e}")

    # ISO 9660 puts its signature at offset 32769, well past the magic prefix
    # but still inside the text sample.
    if len(sample) >= _ISO_OFFSET + len(_ISO_MAGIC):
        if sample[_ISO_OFFSET:_ISO_OFFSET + len(_ISO_MAGIC)] == _ISO_MAGIC:
            return Classification(
                "binary", "iso", "Content identified as an ISO 9660 disk image.",
                spoofed=path.suffix.lower() not in _EXPECTED_BINARY_EXTENSIONS,
            )

    return classify_bytes(sample[:MAGIC_PREFIX_BYTES], sample, path.suffix.lower())
