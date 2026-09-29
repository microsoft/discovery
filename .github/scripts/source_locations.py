"""Source locations for keys in YAML and JSON mappings."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import yaml
from yaml.nodes import MappingNode, ScalarNode


def line_for_key_path(text: str, key_path: Sequence[str]) -> int:
    """Return the 1-based source line for a nested mapping key, or 1 if unknown."""
    try:
        node = yaml.compose(text)
    except yaml.YAMLError:
        return 1

    line = 1
    for expected_key in key_path:
        if not isinstance(node, MappingNode):
            return 1
        match = next(
            (
                (key_node, value_node)
                for key_node, value_node in node.value
                if isinstance(key_node, ScalarNode) and key_node.value == expected_key
            ),
            None,
        )
        if match is None:
            return 1
        key_node, node = match
        line = key_node.start_mark.line + 1
    return line


def line_for_key_path_in_file(path: Path, key_path: Sequence[str]) -> int:
    """Read *path* and return the source line for a nested mapping key."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 1
    return line_for_key_path(text, key_path)