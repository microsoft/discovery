"""Shared fixtures for per-rule tests.

Each rule gets its own ``test_<rule_id>.py`` next to this file. Tests build a
scratch repository on tmp_path, seeded with the *real* ``.github/policy/``
configuration so a mistake in the shipped allowlist shows up as a test failure
rather than passing against a hand-written stub.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rules.base import Rule
from rules.registry import RunResult, build_context, run_rules

REPO_ROOT = Path(__file__).resolve().parents[3]

# Minimal well-formed samples, byte-exact where the magic matters.
ELF_BYTES = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 56 + b"payload"
PE_BYTES = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00" + b"\x00" * 48
ZIP_BYTES = b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + b"\x00" * 40
GZIP_BYTES = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03" + b"\xed\xbd\x07"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 20
PDF_BYTES = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< >>\nendobj\n"
SQLITE_BYTES = b"SQLite format 3\x00" + b"\x00" * 80
WASM_BYTES = b"\x00asm\x01\x00\x00\x00" + b"\x00" * 16


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A scratch repo containing the real .github/policy/ configuration."""
    policy_src = REPO_ROOT / ".github" / "policy"
    policy_dst = tmp_path / ".github" / "policy"
    policy_dst.mkdir(parents=True, exist_ok=True)
    if policy_src.is_dir():
        for f in policy_src.iterdir():
            if f.is_file():
                shutil.copy2(f, policy_dst / f.name)
    return tmp_path


def write(repo: Path, rel: str, content: bytes | str) -> str:
    """Write a file into the scratch repo and return its relative path."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return rel


def write_policy(repo: Path, filename: str, content: str) -> None:
    """Overwrite one file in the scratch repo's .github/policy/ directory."""
    path = repo / ".github" / "policy" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_rule(repo: Path, rule: Rule, changed: list[str], **kwargs) -> RunResult:
    """Execute exactly one rule against the scratch repo."""
    ctx = build_context(repo, changed)
    return run_rules(ctx, [rule], **kwargs)


def ids(result: RunResult) -> list[str]:
    return [f.rule_id for f in result.findings]


def files(result: RunResult) -> list[str]:
    return [f.file for f in result.findings]
