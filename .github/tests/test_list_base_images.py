"""Enumeration of catalog base images for the weekly deep scan."""

from __future__ import annotations

from pathlib import Path

import list_base_images


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_both_dockerfile_naming_conventions_are_scanned(tmp_path: Path):
    _write(tmp_path, "agents/a/tools/t/Dockerfile", "FROM ubuntu:24.04\n")
    _write(tmp_path, "agents/b/tools/t/Dockerfile.prod", "FROM debian:12\n")
    _write(tmp_path, "agents/c/tools/t/build.Dockerfile", "FROM alpine:3.20\n")

    usage = list_base_images.collect(tmp_path)

    assert set(usage) == {"ubuntu:24.04", "debian:12", "alpine:3.20"}


def test_iter_dockerfiles_deduplicates_ambiguous_names(tmp_path: Path):
    # A name matching both globs (``Dockerfile`` prefix and ``.Dockerfile``
    # suffix) must be visited exactly once.
    _write(tmp_path, "agents/a/tools/t/Dockerfile.Dockerfile", "FROM ubuntu:24.04\n")

    found = list_base_images.iter_dockerfiles(tmp_path / "agents")

    assert len(found) == 1
