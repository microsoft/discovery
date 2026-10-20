"""Path-aware source locations for YAML and JSON diagnostics."""

from __future__ import annotations

from pathlib import Path

import pytest

from source_locations import line_for_key_path, line_for_key_path_in_file


def test_yaml_location_follows_nested_path_with_repeated_key_names():
    text = (
        "url: https://example.com/top\n"
        "publisher:\n"
        '  "url": https://example.com/publisher\n'
        "  support_url: https://example.com/support\n"
        "author:\n"
        "  url: https://example.com/author\n"
    )

    assert line_for_key_path(text, ("url",)) == 1
    assert line_for_key_path(text, ("publisher", "url")) == 3
    assert line_for_key_path(text, ("publisher", "support_url")) == 4
    assert line_for_key_path(text, ("author", "url")) == 6


def test_json_location_follows_nested_path():
    text = (
        "{\n"
        '  "url": "https://example.com/top",\n'
        '  "author": {\n'
        '    "url": "https://example.com/author",\n'
        '    "email": "owner@example.com"\n'
        "  }\n"
        "}\n"
    )

    assert line_for_key_path(text, ("author", "url")) == 4
    assert line_for_key_path(text, ("author", "email")) == 5


@pytest.mark.parametrize(
    ("text", "key_path"),
    [
        ("{not-json", ("author", "url")),
        ("publisher: []\n", ("publisher", "support_url")),
        ("publisher: {}\n", ("publisher", "support_url")),
        ("", ("publisher",)),
    ],
)
def test_unknown_or_malformed_location_falls_back_to_first_line(
    text: str, key_path: tuple[str, ...]
):
    assert line_for_key_path(text, key_path) == 1


def test_file_location_handles_missing_and_non_utf8_files(tmp_path: Path):
    missing = tmp_path / "missing.yaml"
    binary = tmp_path / "binary.yaml"
    binary.write_bytes(b"\xff\xfe")

    assert line_for_key_path_in_file(missing, ("publisher",)) == 1
    assert line_for_key_path_in_file(binary, ("publisher",)) == 1