"""POL-020 — UTF-8 and Unicode text hygiene."""

from __future__ import annotations

import pytest
from conftest import ELF_BYTES, files, run_rule, write

from rules.pol_020 import RULE


@pytest.mark.parametrize(("character", "codepoint"), [
    ("\x00", "U+0000"),
    ("\x1b", "U+001B"),
    ("\x7f", "U+007F"),
    ("\u0085", "U+0085"),
    ("\u00a0", "U+00A0"),
    ("\u200b", "U+200B"),
    ("\u202e", "U+202E"),
    ("\u2066", "U+2066"),
    ("\u2028", "U+2028"),
    ("\ue000", "U+E000"),
    ("\ufdd0", "U+FDD0"),
    ("\ufffd", "U+FFFD"),
    ("\U0010ffff", "U+10FFFF"),
    ("\u0378", "U+0378"),
])
def test_unsafe_unicode_character_is_blocked(repo, character, codepoint):
    rel = write(repo, "agents/demo/README.md", f"# Safe heading\ntext{character}hidden\n")
    result = run_rule(repo, RULE, [rel])

    assert files(result) == [rel]
    assert codepoint in result.findings[0].message
    assert result.findings[0].line == 2


def test_utf8_bom_is_blocked(repo):
    rel = write(repo, "agents/demo/README.md", "\ufeff# Hidden BOM\n")
    result = run_rule(repo, RULE, [rel])

    assert files(result) == [rel]
    assert "U+FEFF" in result.findings[0].message


def test_invalid_utf8_is_blocked(repo):
    rel = write(repo, "agents/demo/README.md", b"valid first line\ninvalid: \xff\n")
    result = run_rule(repo, RULE, [rel])

    assert files(result) == [rel]
    assert "invalid UTF-8" in result.findings[0].message
    assert result.findings[0].line == 2


def test_visible_international_and_scientific_text_passes(repo):
    rel = write(
        repo,
        "agents/demo/README.md",
        "# Démo — Ångström\r\n\tSchrödinger β-sheet at 25 °C ± 0.5 Å.\n中文说明。\n",
    )
    result = run_rule(repo, RULE, [rel])

    assert result.findings == []


def test_combining_marks_pass(repo):
    rel = write(repo, "agents/demo/README.md", "Cafe\u0301 and A\u030angstro\u0308m\n")
    result = run_rule(repo, RULE, [rel])

    assert result.findings == []


def test_recognized_binary_is_left_to_pol_008(repo):
    rel = write(repo, "agents/demo/payload.txt", ELF_BYTES)
    result = run_rule(repo, RULE, [rel])

    assert result.findings == []


def test_model_weight_is_left_to_pol_009(repo):
    rel = write(repo, "agents/demo/model.safetensors", b"not text\x00")
    result = run_rule(repo, RULE, [rel])

    assert result.findings == []


def test_file_outside_catalog_trees_is_ignored(repo):
    rel = write(repo, "utilities/demo/readme.txt", "unsafe\u202etext\n")
    result = run_rule(repo, RULE, [rel])

    assert result.findings == []


def test_deleted_file_is_ignored(repo):
    result = run_rule(repo, RULE, ["agents/demo/deleted.txt"])

    assert result.findings == []