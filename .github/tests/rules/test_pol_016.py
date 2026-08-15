"""POL-016 — image files must genuinely be the image they claim to be.

Two failure families matter: a raster whose content contradicts its extension,
and an SVG carrying active content. SVG gets the heavier coverage because it is
the only image format accepted as source and the only one that can execute.
"""

from __future__ import annotations

import pytest
from conftest import ELF_BYTES, PNG_BYTES, ZIP_BYTES, files, run_rule, write

from rules.pol_016 import RULE

# Byte-exact minimal images, each with the end-of-file marker its format requires.
VALID_PNG = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\rIHDR" + b"\x00" * 20
    + b"IEND\xaeB`\x82"
)
VALID_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 20 + b"\xff\xd9"
VALID_GIF = b"GIF89a" + b"\x00" * 20 + b"\x3b"
VALID_WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 20
VALID_BMP = b"BM" + b"\x00" * 12 + (40).to_bytes(4, "little") + b"\x00" * 20
VALID_ICO = b"\x00\x00\x01\x00\x01\x00" + b"\x00" * 20
VALID_TIFF = b"II\x2a\x00" + b"\x00" * 30

CLEAN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="88" height="88" '
    'viewBox="0 0 88 88" role="img" aria-label="Logo">\n'
    '  <rect x="6" y="6" width="36" height="36" fill="#0078D4"/>\n'
    '  <title>A title</title>\n'
    '</svg>\n'
)


# ── Valid images pass ────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel,payload", [
    ("agents/demo/img.png", VALID_PNG),
    ("agents/demo/img.jpg", VALID_JPEG),
    ("agents/demo/img.jpeg", VALID_JPEG),
    ("agents/demo/img.gif", VALID_GIF),
    ("agents/demo/img.webp", VALID_WEBP),
    ("agents/demo/img.bmp", VALID_BMP),
    ("agents/demo/img.ico", VALID_ICO),
    ("agents/demo/img.tiff", VALID_TIFF),
])
def test_matching_raster_content_passes(repo, rel, payload):
    write(repo, rel, payload)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_clean_svg_passes(repo):
    rel = write(repo, "agents/demo/diagram.svg", CLEAN_SVG)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_repository_svgs_are_inert(repo):
    """The SVGs shipped in includes/media/ sit outside the rule's scope, but the
    inspector must still find them clean — they are the reference samples."""
    from pathlib import Path

    from image_inspector import inspect

    repo_root = Path(__file__).resolve().parents[3]
    svgs = list((repo_root / "includes" / "media").glob("*.svg"))
    assert svgs, "expected shipped SVGs to exist"
    for svg in svgs:
        verdict = inspect(svg)
        assert verdict is not None and verdict.ok, f"{svg.name}: {verdict.reason}"


# ── Wrong format behind an image extension ───────────────────────────────────

@pytest.mark.parametrize("rel,payload,expected", [
    ("agents/demo/img.png", VALID_JPEG, "JPEG"),
    ("agents/demo/img.jpg", VALID_PNG, "PNG"),
    ("agents/demo/img.gif", VALID_PNG, "PNG"),
    ("agents/demo/img.webp", VALID_GIF, "GIF"),
])
def test_mismatched_image_format_is_blocked(repo, rel, payload, expected):
    write(repo, rel, payload)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert expected in result.findings[0].message


@pytest.mark.parametrize("payload", [ELF_BYTES, ZIP_BYTES, b"just plain text\n"])
def test_non_image_behind_an_image_extension_is_blocked(repo, payload):
    rel = write(repo, "agents/demo/img.png", payload)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "no known image format" in result.findings[0].message


def test_truncated_png_is_blocked(repo):
    # Correct header, missing the IEND chunk.
    rel = write(repo, "agents/demo/img.png", PNG_BYTES)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "end-of-file marker" in result.findings[0].message


def test_data_appended_after_image_end_is_blocked(repo):
    rel = write(repo, "agents/demo/img.png", VALID_PNG + b"A" * 64)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]


# ── SVG active content ───────────────────────────────────────────────────────

@pytest.mark.parametrize("snippet,label", [
    ('<script>alert(1)</script>', "script"),
    ('<script type="text/javascript">fetch("//evil")</script>', "script"),
    ('<rect onload="fetch(\'//evil\')" width="1" height="1"/>', "event handler"),
    ('<rect onmouseover="steal()" width="1" height="1"/>', "event handler"),
    ('<a href="javascript:alert(1)"><rect width="1" height="1"/></a>', "javascript:"),
    ('<foreignObject><body xmlns="http://www.w3.org/1999/xhtml"/></foreignObject>', "foreignObject"),
    ('<iframe src="//evil"/>', "iframe"),
    ('<image href="https://evil.example/pixel.png"/>', "remote resource"),
    ('<use href="https://evil.example/x.svg#a"/>', "remote resource"),
    ('<animate attributeName="x" to="1"/>', "animate"),
])
def test_svg_with_active_content_is_blocked(repo, snippet, label):
    body = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">\n'
        f"  {snippet}\n"
        "</svg>\n"
    )
    rel = write(repo, "agents/demo/bad.svg", body)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel], f"expected {label} to be rejected"


def test_svg_with_xxe_entity_declaration_is_blocked(repo):
    body = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>\n'
        '<svg xmlns="http://www.w3.org/2000/svg"><text>&xxe;</text></svg>\n'
    )
    rel = write(repo, "agents/demo/xxe.svg", body)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "entity" in result.findings[0].message.lower() or "DTD" in result.findings[0].message


def test_svg_failure_message_reports_a_line_number(repo):
    body = (
        '<svg xmlns="http://www.w3.org/2000/svg">\n'
        "  <rect width='1' height='1'/>\n"
        "  <script>alert(1)</script>\n"
        "</svg>\n"
    )
    rel = write(repo, "agents/demo/bad.svg", body)
    result = run_rule(repo, RULE, [rel])
    assert "line 3" in result.findings[0].message


def test_svg_holding_binary_content_is_blocked(repo):
    rel = write(repo, "agents/demo/fake.svg", ELF_BYTES)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "not UTF-8 text" in result.findings[0].message


def test_svg_without_a_root_element_is_blocked(repo):
    rel = write(repo, "agents/demo/nope.svg", "# Just a markdown file\n")
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "root element" in result.findings[0].message


@pytest.mark.parametrize("attr", [
    'origin="left"',      # starts with "o" but is not an on* handler
    'opacity="0.5"',
    'font-family="Segoe"',
    'stroke-linejoin="round"',
])
def test_svg_attributes_resembling_handlers_are_not_flagged(repo, attr):
    body = (
        '<svg xmlns="http://www.w3.org/2000/svg">\n'
        f"  <rect {attr} width='1' height='1'/>\n"
        "</svg>\n"
    )
    rel = write(repo, "agents/demo/ok.svg", body)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


# ── Scope ────────────────────────────────────────────────────────────────────

def test_non_image_extensions_are_ignored(repo):
    rel = write(repo, "agents/demo/tools/t/utils.py", "print('hi')\n")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


@pytest.mark.parametrize("rel", [
    "docs/media/bad.svg",
    "includes/media/bad.svg",
    "utilities/toolbox/icon.png",
    "README-diagram.svg",
])
def test_images_outside_the_guarded_trees_are_ignored(repo, rel):
    # This policy governs public contributions to agents/ and starter-kits/ only.
    write(repo, rel,
          '<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>')
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_deleted_image_is_not_flagged(repo):
    result = run_rule(repo, RULE, ["agents/demo/gone.png"])
    assert result.findings == []


# ── Image detection used by the PR review gate ───────────────────────────────

@pytest.mark.parametrize("rel,expected", [
    ("agents/demo/logo.png", True),
    ("agents/demo/logo.SVG", True),
    ("starter-kits/demo/shot.jpeg", True),
    ("agents/demo/img.webp", True),
    ("agents/demo/README.md", False),
    ("agents/demo/tools/t/utils.py", False),
    ("agents/demo/metadata.yaml", False),
])
def test_is_image_path_drives_the_review_gate(rel, expected):
    from image_inspector import is_image_path

    assert is_image_path(rel) is expected
