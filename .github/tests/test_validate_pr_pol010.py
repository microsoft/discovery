"""Tests for POL-010 inside validate_pr.py.

POL-010 blocks committed OS / editor / env artefacts. It must NOT fire on
*deletions* of those files — a PR that removes a forbidden file is exactly
the cleanup we want to allow.
"""

from __future__ import annotations

from pathlib import Path

from validate_pr import check_policy


def _has_pol010(failures, file_path: str) -> bool:
    return any(f.rule_id == "POL-010" and f.file == file_path for f in failures)


def test_pol010_fires_when_env_file_is_added(tmp_path: Path) -> None:
    env = tmp_path / "archive" / "foo" / ".env.example"
    env.parent.mkdir(parents=True)
    env.write_text("KEY=value\n", encoding="utf-8")

    changed = ["archive/foo/.env.example"]
    failures = check_policy(tmp_path, set(), changed)

    assert _has_pol010(failures, "archive/foo/.env.example")


def test_pol010_skips_deleted_env_file(tmp_path: Path) -> None:
    # File appears in the changed list but does NOT exist in the PR checkout
    # — i.e. the PR deletes it. POL-010 should not fire.
    changed = ["archive/foo/.env.example"]
    failures = check_policy(tmp_path, set(), changed)

    assert not _has_pol010(failures, "archive/foo/.env.example")


def test_pol010_skips_deleted_ds_store(tmp_path: Path) -> None:
    changed = ["some/path/.DS_Store"]
    failures = check_policy(tmp_path, set(), changed)

    assert not _has_pol010(failures, "some/path/.DS_Store")
