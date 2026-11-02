"""POL-016 — documentation images must be safe, small, and referenced.

The rule checks format integrity, approved web formats, size, Markdown
reachability, and active SVG content.
"""

from __future__ import annotations

import pytest
from conftest import ELF_BYTES, PNG_BYTES, ZIP_BYTES, files, run_rule, write

from rules.pol_016 import RULE
from image_inspector import MAX_MARKDOWN_IMAGE_BYTES

# Byte-exact minimal images, each with the end-of-file marker its format requires.
VALID_PNG = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\rIHDR" + b"\x00" * 20
    + b"IEND\xaeB`\x82"
)
VALID_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 20 + b"\xff\xd9"
VALID_GIF = b"GIF89a" + b"\x00" * 20 + b"\x3b"
VALID_WEBP = b"RIFF\x1c\x00\x00\x00WEBPVP8 " + b"\x00" * 20
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


def reference_image(repo, rel):
    parts = rel.split("/")
    owner = "/".join(parts[:2])
    target = "/".join(parts[2:])
    write(repo, f"{owner}/README.md", f"# Documentation\n\n![Diagram]({target})\n")


# ── Valid images pass ────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel,payload", [
    ("agents/demo/img.png", VALID_PNG),
    ("agents/demo/img.jpg", VALID_JPEG),
    ("agents/demo/img.jpeg", VALID_JPEG),
    ("agents/demo/img.gif", VALID_GIF),
    ("agents/demo/img.webp", VALID_WEBP),
])
def test_matching_raster_content_passes(repo, rel, payload):
    write(repo, rel, payload)
    reference_image(repo, rel)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_clean_svg_passes(repo):
    rel = write(repo, "agents/demo/diagram.svg", CLEAN_SVG)
    reference_image(repo, rel)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_orphaned_image_is_blocked(repo):
    rel = write(repo, "agents/demo/img.png", VALID_PNG)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "not embedded by Markdown" in result.findings[0].message


def test_removing_last_markdown_reference_revalidates_existing_image(repo):
    image = write(repo, "agents/demo/media/diagram.png", VALID_PNG)
    markdown = write(
        repo,
        "agents/demo/README.md",
        "# Updated documentation without the image\n",
    )

    result = run_rule(repo, RULE, [markdown])

    assert files(result) == [image]
    assert "not embedded by Markdown" in result.findings[0].message


def test_oversized_image_is_blocked(repo):
    rel = write(
        repo,
        "agents/demo/img.png",
        VALID_PNG[:-8] + b"x" * MAX_MARKDOWN_IMAGE_BYTES + b"IEND\xaeB`\x82",
    )
    reference_image(repo, rel)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "1 MiB" in result.findings[0].message


def test_non_markdown_image_format_is_blocked(repo):
    rel = write(repo, "agents/demo/img.bmp", VALID_BMP)
    reference_image(repo, rel)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "not an approved Markdown image format" in result.findings[0].message


def test_nested_image_can_be_referenced_from_nested_markdown(repo):
    rel = write(repo, "agents/demo/media/diagram.png", VALID_PNG)
    write(repo, "agents/demo/docs/usage.md", "![Diagram](../media/diagram.png)\n")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_uppercase_markdown_extension_can_reference_image(repo):
    rel = write(repo, "agents/demo/media/diagram.png", VALID_PNG)
    write(repo, "agents/demo/ARCHITECTURE.MD", "![Diagram](media/diagram.png)\n")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_reference_style_markdown_image_passes(repo):
    rel = write(repo, "agents/demo/media/diagram.png", VALID_PNG)
    write(repo, "agents/demo/README.md", "![Diagram][architecture]\n\n[architecture]: media/diagram.png\n")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_html_image_reference_passes(repo):
    rel = write(repo, "agents/demo/media/diagram.webp", VALID_WEBP)
    write(repo, "agents/demo/README.md", '<img src="media/diagram.webp" alt="Diagram">\n')
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_reference_from_another_catalog_item_does_not_pass(repo):
    rel = write(repo, "agents/demo/diagram.png", VALID_PNG)
    write(repo, "agents/other/README.md", "![Wrong owner](../demo/diagram.png)\n")
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]


def test_starter_kit_long_description_can_reference_image(repo):
    rel = write(repo, "starter-kits/demo/media/diagram.png", VALID_PNG)
    write(
        repo,
        "starter-kits/demo/kit.json",
        '{"longDescription": "# Demo\\n\\n![Diagram](media/diagram.png)"}\n',
    )
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


def test_webp_with_appended_payload_is_blocked(repo):
    rel = write(
        repo,
        "agents/demo/img.webp",
        VALID_WEBP + b"PK\x03\x04appended archive",
    )
    reference_image(repo, rel)

    result = run_rule(repo, RULE, [rel])

    assert files(result) == [rel]
    assert "data appended" in result.findings[0].message


def test_data_appended_after_image_end_is_blocked(repo):
    rel = write(repo, "agents/demo/img.png", VALID_PNG + b"A" * 64)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]


def test_small_payload_appended_after_image_end_is_blocked(repo):
    # A short append keeps IEND inside the tail window; the marker must be the
    # actual final bytes, not merely present near the end.
    rel = write(repo, "agents/demo/img.png", VALID_PNG + b"A" * 4)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "end-of-file" in result.findings[0].message


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


@pytest.mark.parametrize(
    "doctype",
    [
        '<!DOCTYPE svg SYSTEM "https://attacker.example/entity.dtd">',
        '<!DOCTYPE svg PUBLIC "-//EXAMPLE//DTD SVG 1.0//EN" "https://attacker.example/svg.dtd">',
    ],
)
def test_svg_with_external_doctype_is_blocked(repo, doctype):
    body = (
        f"{doctype}\n"
        '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>\n'
    )
    rel = write(repo, "agents/demo/external-dtd.svg", body)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "external DTD" in result.findings[0].message


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


def test_svg_root_only_inside_a_comment_is_blocked(repo):
    """A ``<svg`` that appears only inside a comment or text node is not a root
    element; the file must be rejected rather than accepted as an SVG."""
    rel = write(repo, "agents/demo/fake.svg", "<!-- <svg> not really -->\nplain text\n")
    reference_image(repo, rel)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "root element" in result.findings[0].message


def test_svg_with_leading_comment_and_doctype_still_passes(repo):
    """Legitimate leading noise — an XML declaration, a comment, a DOCTYPE —
    before the real ``<svg>`` root must not cause a false rejection."""
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!-- a copyright banner -->\n"
        "<!DOCTYPE svg>\n"
        '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">'
        '<rect width="1" height="1"/></svg>\n'
    )
    rel = write(repo, "agents/demo/ok.svg", svg)
    reference_image(repo, rel)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == []


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
    reference_image(repo, rel)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


@pytest.mark.parametrize("snippet,label", [
    ('<style>@import url("https://evil.example/x.css");</style>', "CSS @import"),
    ('<rect style="fill:url(https://evil.example/p.png)"/>', "CSS url()"),
    ('<use xlink:href="https://evil.example/x.svg#a"/>', "remote xlink"),
    ('<use xlink:href="//evil.example/x.svg#a"/>', "protocol-relative xlink"),
    ('<a href="java&#115;cript:alert(1)"><rect/></a>', "encoded javascript:"),
    ('<rect o&#110;load="steal()" width="1" height="1"/>', "encoded handler"),
])
def test_svg_with_obfuscated_or_css_active_content_is_blocked(repo, snippet, label):
    body = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">\n'
        f"  {snippet}\n"
        "</svg>\n"
    )
    rel = write(repo, "agents/demo/bad.svg", body)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel], f"expected {label} to be rejected"


@pytest.mark.parametrize("snippet", [
    '<rect fill="url(#grad1)" width="1" height="1"/>',   # internal paint ref
    '<use xlink:href="#icon"/>',                          # internal symbol ref
    '<use href="#icon"/>',                                # internal symbol ref
])
def test_svg_internal_references_are_not_flagged(repo, snippet):
    body = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink">\n'
        f"  {snippet}\n"
        "</svg>\n"
    )
    rel = write(repo, "agents/demo/ok.svg", body)
    reference_image(repo, rel)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_svg_with_escaped_script_text_is_not_flagged(repo):
    # Named entities stay literal text in a browser; they must not be decoded
    # into an executable-looking match.
    body = (
        '<svg xmlns="http://www.w3.org/2000/svg">\n'
        "  <text>&lt;script&gt;alert(1)&lt;/script&gt;</text>\n"
        "</svg>\n"
    )
    rel = write(repo, "agents/demo/ok.svg", body)
    reference_image(repo, rel)
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
