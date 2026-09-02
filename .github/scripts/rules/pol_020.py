#!/usr/bin/env python3
"""POL-020 — contributed text must be safe, well-formed UTF-8."""

from __future__ import annotations

import codecs
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from content_sniffer import classify
from rules.base import Finding, Rule, RuleContext, Scope, Severity


GUARDED_PREFIXES = ("agents/", "starter-kits/")
READ_CHUNK_BYTES = 64 * 1024
ALLOWED_CONTROLS = frozenset({"\t", "\n", "\r"})


@dataclass(frozen=True)
class TextIssue:
    line: int
    description: str


def _is_noncharacter(codepoint: int) -> bool:
    return 0xFDD0 <= codepoint <= 0xFDEF or codepoint & 0xFFFF in {0xFFFE, 0xFFFF}


def _unsafe_reason(character: str) -> str | None:
    if character in ALLOWED_CONTROLS:
        return None

    codepoint = ord(character)
    if _is_noncharacter(codepoint):
        return "Unicode noncharacter"
    if codepoint == 0xFFFD:
        return "Unicode replacement character, which indicates lost or malformed text"

    category = unicodedata.category(character)
    reasons = {
        "Cc": "control character",
        "Cf": "invisible formatting or bidirectional control",
        "Cs": "surrogate code point",
        "Co": "private-use code point",
        "Cn": "unassigned code point",
        "Zl": "Unicode line separator",
        "Zp": "Unicode paragraph separator",
    }
    if category in reasons:
        return reasons[category]
    if category == "Zs" and character != " ":
        return "non-ASCII space separator"
    return None


def _describe_character(character: str, reason: str) -> str:
    codepoint = ord(character)
    name = unicodedata.name(character, "UNNAMED")
    return f"U+{codepoint:04X} {name} ({reason})"


def scan_text(path: Path) -> TextIssue | None:
    """Return the first malformed or unsafe character without loading the file."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    line = 1

    try:
        with path.open("rb") as stream:
            while chunk := stream.read(READ_CHUNK_BYTES):
                try:
                    text = decoder.decode(chunk, final=False)
                except UnicodeDecodeError as error:
                    prefix = error.object[:error.start].decode("utf-8", errors="ignore")
                    return TextIssue(
                        line=line + prefix.count("\n"),
                        description="invalid UTF-8 byte sequence",
                    )

                for character in text:
                    reason = _unsafe_reason(character)
                    if reason is not None:
                        return TextIssue(line, _describe_character(character, reason))
                    if character == "\n":
                        line += 1

            try:
                tail = decoder.decode(b"", final=True)
            except UnicodeDecodeError:
                return TextIssue(line, "incomplete UTF-8 byte sequence at end of file")

            for character in tail:
                reason = _unsafe_reason(character)
                if reason is not None:
                    return TextIssue(line, _describe_character(character, reason))
                if character == "\n":
                    line += 1
    except OSError:
        return None

    return None


def _is_guarded(rel: str) -> bool:
    return rel.startswith(GUARDED_PREFIXES)


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []

    for rel in ctx.existing_changed_files():
        if not _is_guarded(rel):
            continue
        if Path(rel).suffix.lower() in ctx.policy.model_weight_extensions:
            continue

        classification = classify(ctx.abs(rel))
        if classification.is_binary and classification.format != "unknown-binary":
            continue

        issue = scan_text(ctx.abs(rel))
        if issue is None:
            continue

        findings.append(Finding(
            rule_id="POL-020",
            file=rel,
            line=issue.line,
            message=(
                f"Unsafe text at line {issue.line}: {issue.description}. "
                "Catalog source must be valid UTF-8 and must not contain "
                "invisible controls, bidirectional overrides, private-use or "
                "unassigned code points, Unicode noncharacters, replacement "
                "characters, or non-standard space/line separators. Tabs and "
                "CR/LF line endings are allowed."
            ),
        ))

    return findings


RULE = Rule(
    id="POL-020",
    summary="UTF-8 source text must not contain unsafe or invisible Unicode characters.",
    scope=Scope.CHANGED_FILES,
    severity=Severity.ERROR,
    remediation=(
        "Save the file as valid UTF-8 and remove the reported control, "
        "bidirectional, zero-width, private-use, unassigned, noncharacter, "
        "replacement, or non-standard separator code point. Normal visible "
        "international and scientific text is allowed."
    ),
    tags=("security", "integrity", "unicode"),
    check=check,
)