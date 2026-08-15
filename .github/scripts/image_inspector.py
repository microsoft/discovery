#!/usr/bin/env python3
"""
image_inspector.py — verify that a file claiming to be an image really is one.

Two distinct problems are covered here.

**Mislabelling.** A file named ``diagram.png`` that actually holds a ZIP, an
ELF, or a different image format is either a mistake or an attempt to smuggle
content past a reviewer who trusts the extension.

**Active content in SVG.** SVG is the only image format the catalog accepts as
source, because it is text. That same property makes it executable: an SVG can
carry ``<script>``, inline event handlers, ``javascript:`` URIs, external
entity declarations, and remote references. Rendered in a browser — a docs
site, a catalog UI, a Markdown preview — those run. So an SVG is checked for
structure *and* for active content.

Nothing here parses untrusted XML with a real parser; the checks are bounded
regex and byte comparisons, so a hostile file cannot turn the validator into
the exploit (billion laughs, XXE, and friends).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Bytes read from the head of a file for signature matching.
HEADER_BYTES = 64

#: Bytes read from the tail for end-of-file marker checks.
TRAILER_BYTES = 32

#: Cap on how much SVG text is scanned for active content.
SVG_SCAN_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class ImageVerdict:
    """Outcome of inspecting one image file."""

    ok: bool
    #: Format actually detected, or None when nothing recognizable was found.
    detected: str | None
    #: Human-readable explanation suitable for a PR comment.
    reason: str


# ── Raster signatures ────────────────────────────────────────────────────────

def _is_webp(head: bytes) -> bool:
    return len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP"


def _is_bmp(head: bytes) -> bool:
    # "BM" alone is two printable characters; require the DIB header size that
    # follows the 14-byte file header to be one of the documented values.
    if len(head) < 18 or head[:2] != b"BM":
        return False
    dib_size = int.from_bytes(head[14:18], "little")
    return dib_size in {12, 40, 52, 56, 64, 108, 124}


def _is_ico(head: bytes) -> bool:
    # Reserved=0, type=1 (icon) or 2 (cursor), and at least one image entry.
    if len(head) < 6 or head[:2] != b"\x00\x00":
        return False
    return head[2:4] in (b"\x01\x00", b"\x02\x00") and head[4:6] != b"\x00\x00"


#: Detector order matters only in that each predicate is mutually exclusive.
_RASTER_DETECTORS: tuple[tuple[str, object], ...] = (
    ("png", lambda h: h[:8] == b"\x89PNG\r\n\x1a\n"),
    ("jpeg", lambda h: h[:3] == b"\xff\xd8\xff"),
    ("gif", lambda h: h[:6] in (b"GIF87a", b"GIF89a")),
    ("webp", _is_webp),
    ("tiff", lambda h: h[:4] in (b"II\x2a\x00", b"MM\x00\x2a")),
    ("ico", _is_ico),
    ("bmp", _is_bmp),
)

#: Expected end-of-file markers, where the format defines one.
_TRAILERS: dict[str, bytes] = {
    "png": b"IEND\xaeB`\x82",
    "jpeg": b"\xff\xd9",
    "gif": b"\x3b",
}

#: Extension → the format ids that are acceptable for it.
IMAGE_EXTENSIONS: dict[str, tuple[str, ...]] = {
    ".png": ("png",),
    ".jpg": ("jpeg",),
    ".jpeg": ("jpeg",),
    ".jpe": ("jpeg",),
    ".gif": ("gif",),
    ".webp": ("webp",),
    ".tif": ("tiff",),
    ".tiff": ("tiff",),
    ".ico": ("ico",),
    ".bmp": ("bmp",),
    ".svg": ("svg",),
}


def detect_raster_format(head: bytes) -> str | None:
    """Return the raster format id matching this header, if any."""
    for name, predicate in _RASTER_DETECTORS:
        if predicate(head):  # type: ignore[operator]
            return name
    return None


def is_image_path(rel_path: str | Path) -> bool:
    """True when the path claims an image format by extension."""
    return Path(rel_path).suffix.lower() in IMAGE_EXTENSIONS


# ── SVG structure and active content ─────────────────────────────────────────

_SVG_ROOT_RE = re.compile(r"<svg[\s>]", re.IGNORECASE)

#: Patterns that make an SVG executable or able to reach off-host. Each entry
#: is (regex, short label used in the failure message).
_SVG_ACTIVE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"<\s*script", re.IGNORECASE), "a <script> element"),
    (re.compile(r"<\s*foreignObject", re.IGNORECASE), "a <foreignObject> element"),
    (re.compile(r"<\s*iframe", re.IGNORECASE), "an <iframe> element"),
    (re.compile(r"<\s*embed", re.IGNORECASE), "an <embed> element"),
    (re.compile(r"<\s*object", re.IGNORECASE), "an <object> element"),
    (re.compile(r"<!ENTITY", re.IGNORECASE), "an XML entity declaration (XXE vector)"),
    (re.compile(r"<\s*!\s*DOCTYPE[^>]*\[", re.IGNORECASE), "an internal DTD subset"),
    (re.compile(r"\son[a-z]+\s*=", re.IGNORECASE), "an inline event handler attribute"),
    (re.compile(r"javascript\s*:", re.IGNORECASE), "a javascript: URI"),
    (re.compile(r"data\s*:\s*text/html", re.IGNORECASE), "a data: URI containing HTML"),
    (re.compile(r"<\s*(image|use)[^>]*\bhref\s*=\s*[\"']?https?://", re.IGNORECASE),
     "a remote resource reference"),
    (re.compile(r"<\s*set\b", re.IGNORECASE), "an animation <set> element"),
    (re.compile(r"<\s*animate", re.IGNORECASE), "an <animate> element"),
)


def inspect_svg(text: str) -> ImageVerdict:
    """Validate SVG structure and reject active content."""
    scanned = text[:SVG_SCAN_BYTES]

    if not _SVG_ROOT_RE.search(scanned):
        return ImageVerdict(
            ok=False,
            detected=None,
            reason="No <svg> root element was found; the file is not an SVG document.",
        )

    for pattern, label in _SVG_ACTIVE_PATTERNS:
        match = pattern.search(scanned)
        if match:
            line = scanned[:match.start()].count("\n") + 1
            return ImageVerdict(
                ok=False,
                detected="svg",
                reason=(
                    f"SVG contains {label} at line {line} "
                    f"({match.group(0).strip()!r}). SVG is accepted as source "
                    f"only when it is purely declarative artwork; scripting, "
                    f"embedded documents, entity declarations, and remote "
                    f"references execute or leak when the image is rendered."
                ),
            )

    return ImageVerdict(ok=True, detected="svg", reason="Valid, inert SVG document.")


# ── Entry point ──────────────────────────────────────────────────────────────

def inspect(path: Path, suffix: str | None = None) -> ImageVerdict | None:
    """Inspect a file whose extension claims an image format.

    Returns ``None`` when the extension is not an image extension, so callers
    can skip non-images without a second lookup.
    """
    ext = (suffix if suffix is not None else path.suffix).lower()
    expected = IMAGE_EXTENSIONS.get(ext)
    if expected is None:
        return None

    try:
        raw = path.read_bytes() if ext == ".svg" else _read_ends(path)
    except OSError as e:
        return ImageVerdict(False, None, f"Could not read file: {e}")

    if ext == ".svg":
        # A NUL byte or a raster signature settles it before any decode: an SVG
        # is an XML text document, and ELF-style payloads are pure ASCII, so
        # decodability alone would misreport them as malformed markup.
        raster = detect_raster_format(raw[:HEADER_BYTES])
        if raster or b"\x00" in raw[:SVG_SCAN_BYTES]:
            return ImageVerdict(
                ok=False,
                detected=raster,
                reason=(
                    f"File is named .svg but its content is "
                    f"{raster.upper() if raster else 'binary'}, not UTF-8 text. "
                    f"SVG is an XML document; binary content here means the "
                    f"file is mislabelled."
                ),
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return ImageVerdict(
                ok=False,
                detected=None,
                reason=(
                    "File is named .svg but is not UTF-8 text. SVG is an XML "
                    "document; binary content here means the file is mislabelled."
                ),
            )
        return inspect_svg(text)

    head, tail = raw[:HEADER_BYTES], raw[-TRAILER_BYTES:]
    detected = detect_raster_format(head)

    if detected is None:
        return ImageVerdict(
            ok=False,
            detected=None,
            reason=(
                f"File is named '{ext}' but its content matches no known image "
                f"format. The extension misrepresents what the file contains."
            ),
        )

    if detected not in expected:
        return ImageVerdict(
            ok=False,
            detected=detected,
            reason=(
                f"File is named '{ext}' but its content is {detected.upper()}. "
                f"Rename it to the correct extension or re-export it in the "
                f"declared format."
            ),
        )

    trailer = _TRAILERS.get(detected)
    if trailer and trailer not in tail:
        return ImageVerdict(
            ok=False,
            detected=detected,
            reason=(
                f"{detected.upper()} file is missing its end-of-file marker, so "
                f"it is truncated or has data appended after the image. Both "
                f"indicate corruption or a polyglot file."
            ),
        )

    return ImageVerdict(ok=True, detected=detected, reason=f"Valid {detected.upper()} image.")


def _read_ends(path: Path) -> bytes:
    """Read the head and tail of a file without loading the whole thing."""
    with open(path, "rb") as fh:
        head = fh.read(HEADER_BYTES)
        try:
            fh.seek(max(0, path.stat().st_size - TRAILER_BYTES))
            tail = fh.read(TRAILER_BYTES)
        except OSError:
            tail = b""
    # Keep the contract of `raw[:HEADER]` / `raw[-TRAILER:]` for short files.
    return head + tail if len(head) == HEADER_BYTES else head
