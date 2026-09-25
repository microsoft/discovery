"""POL-017 — floating base image tags (warning severity)."""

from __future__ import annotations

import pytest
from conftest import files, run_rule, write

from rules.base import Severity
from rules.pol_017 import RULE


@pytest.mark.parametrize("image", [
    "condaforge/mambaforge:latest",
    "continuumio/miniconda3:latest",
    "ubuntu:edge",
    "python:nightly",
    "debian:stable",
])
def test_floating_tags_are_reported(repo, image):
    rel = write(repo, "agents/demo/tools/t/Dockerfile", f"FROM {image}\n")
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]


def test_findings_are_warnings_not_blocking(repo):
    rel = write(repo, "agents/demo/tools/t/Dockerfile", "FROM ubuntu:latest\n")
    result = run_rule(repo, RULE, [rel])
    assert result.blocking == []
    assert len(result.warnings) == 1
    assert result.warnings[0].severity is Severity.WARNING


def test_missing_tag_is_reported(repo):
    rel = write(repo, "agents/demo/tools/t/Dockerfile", "FROM ubuntu\n")
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "no tag" in result.findings[0].message


@pytest.mark.parametrize("image", [
    "ubuntu:24.04",
    "python:3.12-slim",
    "condaforge/mambaforge:24.3.0-0",
    "nvidia/cuda:12.6.3-devel-ubuntu22.04",
    "mcr.microsoft.com/azurelinux/base/python:3.12",
])
def test_pinned_tags_pass(repo, image):
    rel = write(repo, "agents/demo/tools/t/Dockerfile", f"FROM {image}\n")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_digest_pin_passes_even_with_a_floating_tag(repo):
    rel = write(
        repo, "agents/demo/tools/t/Dockerfile",
        "FROM ubuntu:latest@sha256:" + "0" * 64 + "\n",
    )
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


@pytest.mark.parametrize("digest", [
    "${DIGEST}",
    "sha256:not-hex",
    "sha256:1234",
])
def test_invalid_or_unresolved_digest_is_reported(repo, digest):
    rel = write(
        repo,
        "agents/demo/tools/t/Dockerfile",
        f"FROM ubuntu:24.04@{digest}\n",
    )

    result = run_rule(repo, RULE, [rel])

    assert files(result) == [rel]
    assert "invalid or unresolved digest" in result.findings[0].message


def test_arg_default_resolves_the_tag(repo):
    body = "ARG UBUNTU_TAG=24.04\nFROM ubuntu:${UBUNTU_TAG}\n"
    rel = write(repo, "agents/demo/tools/t/Dockerfile", body)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_unresolved_arg_tag_is_flagged(repo):
    # No pinned ARG default: the version can be changed at build time, so the
    # build is not reproducible. POL-017 warns rather than exempting it.
    body = "ARG UBUNTU_TAG\nFROM ubuntu:${UBUNTU_TAG}\n"
    rel = write(repo, "agents/demo/tools/t/Dockerfile", body)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]
    assert "unresolved build argument" in result.findings[0].message
    assert result.findings[0].severity is Severity.WARNING


def test_arg_default_pointing_at_latest_is_flagged(repo):
    body = "ARG UBUNTU_TAG=latest\nFROM ubuntu:${UBUNTU_TAG}\n"
    rel = write(repo, "agents/demo/tools/t/Dockerfile", body)
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]


def test_multistage_internal_reference_is_ignored(repo):
    body = "FROM ubuntu:24.04 AS builder\nFROM builder\n"
    rel = write(repo, "agents/demo/tools/t/Dockerfile", body)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []
