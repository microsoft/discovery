#!/usr/bin/env python3
"""Report spelling warnings in changed catalog prose without executing PR code."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

MAX_FILE_BYTES = 1_000_000
IGNORE_WORDS_PATH = Path(__file__).resolve().parent.parent / "policy" / "codespell-ignore.txt"
PROSE_FIELDS = frozenset({
    "additionalInstructions",
    "description",
    "displayName",
    "expectedOutput",
    "instructions",
    "longDescription",
    "prompt",
    "title",
})
STRUCTURED_SUFFIXES = frozenset({".json", ".yaml", ".yml"})
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_INLINE_CODE_RE = re.compile(r"`+[^`]*`+")
_MARKDOWN_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_AUTOLINK_RE = re.compile(r"<https?://[^>]+>", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_CODESPELL_LINE_RE = re.compile(r"^.*:(\d+):\s*(.+)$")


@dataclass(frozen=True)
class ProseFragment:
    file: str
    line: int
    text: str


@dataclass(frozen=True)
class SpellingWarning:
    file: str
    line: int
    message: str


def _clean_markdown_line(line: str) -> str:
    line = _INLINE_CODE_RE.sub(" ", line)
    line = _MARKDOWN_LINK_RE.sub(r"\1", line)
    line = _AUTOLINK_RE.sub(" ", line)
    line = _URL_RE.sub(" ", line)
    line = _HTML_TAG_RE.sub(" ", line)
    return line.strip(" \t#>*_~-|")


def _markdown_fragments(text: str, rel_path: str) -> list[ProseFragment]:
    fragments: list[ProseFragment] = []
    in_fence = False
    fence_character = ""
    in_frontmatter = text.startswith("---\n") or text.startswith("---\r\n")

    for line_number, line in enumerate(text.splitlines(), start=1):
        if in_frontmatter:
            if line_number > 1 and line.strip() == "---":
                in_frontmatter = False
            continue

        fence = _FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not in_fence:
                in_fence = True
                fence_character = marker[0]
            elif marker[0] == fence_character:
                in_fence = False
            continue
        if in_fence or line.startswith(("    ", "\t")):
            continue

        cleaned = _clean_markdown_line(line)
        if cleaned:
            fragments.append(ProseFragment(rel_path, line_number, cleaned))
    return fragments


def _structured_fragments(text: str, rel_path: str) -> list[ProseFragment]:
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return []
    if root is None:
        return []

    fragments: list[ProseFragment] = []

    def walk(node: Node) -> None:
        if isinstance(node, MappingNode):
            for key_node, value_node in node.value:
                if (
                    isinstance(key_node, ScalarNode)
                    and key_node.value in PROSE_FIELDS
                    and isinstance(value_node, ScalarNode)
                    and value_node.tag == "tag:yaml.org,2002:str"
                ):
                    prose = " ".join(
                        fragment.text
                        for fragment in _markdown_fragments(value_node.value, rel_path)
                    )
                    if prose:
                        fragments.append(ProseFragment(
                            rel_path,
                            value_node.start_mark.line + 1,
                            prose,
                        ))
                walk(value_node)
        elif isinstance(node, SequenceNode):
            for child in node.value:
                walk(child)

    walk(root)
    return fragments


def _catalog_file(repo_root: Path, changed_path: str) -> tuple[Path, str] | None:
    normalized = changed_path.strip().replace("\\", "/")
    relative = PurePosixPath(normalized)
    if (
        not normalized
        or relative.is_absolute()
        or ".." in relative.parts
        or not relative.parts
        or relative.parts[0] not in {"agents", "starter-kits"}
    ):
        return None

    candidate = repo_root.joinpath(*relative.parts)
    try:
        candidate.resolve().relative_to(repo_root.resolve())
    except (OSError, ValueError):
        return None
    if not candidate.is_file() or candidate.stat().st_size > MAX_FILE_BYTES:
        return None
    return candidate, normalized


def collect_fragments(repo_root: Path, changed_files: Iterable[str]) -> list[ProseFragment]:
    fragments: list[ProseFragment] = []
    for changed_path in changed_files:
        catalog_file = _catalog_file(repo_root, changed_path)
        if catalog_file is None:
            continue
        path, rel_path = catalog_file
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue

        suffix = path.suffix.lower()
        if suffix in MARKDOWN_SUFFIXES:
            fragments.extend(_markdown_fragments(text, rel_path))
        elif suffix in STRUCTURED_SUFFIXES:
            fragments.extend(_structured_fragments(text, rel_path))
    return fragments


def run_codespell(
    fragments: list[ProseFragment],
    codespell_command: list[str] | None = None,
) -> list[SpellingWarning]:
    if not fragments:
        return []

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".txt", delete=False
        ) as temp_file:
            temp_path = Path(temp_file.name)
            for fragment in fragments:
                temp_file.write(fragment.text.replace("\n", " ") + "\n")

        command = codespell_command or [sys.executable, "-m", "codespell_lib"]
        result = subprocess.run(
            [
                *command,
                "--quiet-level=2",
                "--ignore-words",
                str(IGNORE_WORDS_PATH),
                "--",
                str(temp_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        warnings: list[SpellingWarning] = []
        for output_line in (result.stdout + "\n" + result.stderr).splitlines():
            match = _CODESPELL_LINE_RE.match(output_line)
            if not match:
                continue
            fragment_index = int(match.group(1)) - 1
            if 0 <= fragment_index < len(fragments):
                fragment = fragments[fragment_index]
                warnings.append(SpellingWarning(
                    fragment.file,
                    fragment.line,
                    f"Possible spelling issue: {match.group(2)}",
                ))

        if result.returncode and not warnings:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"codespell failed with exit code {result.returncode}: {detail}")
        return warnings
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _workflow_escape(value: str, *, property_value: bool = False) -> str:
    escaped = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if property_value:
        escaped = escaped.replace(":", "%3A").replace(",", "%2C")
    return escaped


def write_report(path: Path, warnings: list[SpellingWarning]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "warning_count": len(warnings),
        "warnings": [asdict(warning) for warning in warnings],
    }, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    changed_files = Path(args.changed_files).read_text(encoding="utf-8").splitlines()
    fragments = collect_fragments(Path(args.repo_root).resolve(), changed_files)
    warnings = run_codespell(fragments)
    write_report(Path(args.output), warnings)

    for warning in warnings:
        print(
            "::warning "
            f"file={_workflow_escape(warning.file, property_value=True)},"
            f"line={warning.line},title=SPELL-001::"
            f"{_workflow_escape(warning.message)}"
        )
    print(f"Spellcheck completed with {len(warnings)} non-blocking warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())