"""POL-022 — Docker compatibility for Podman-oriented build files."""

from __future__ import annotations

import pytest
from conftest import files, run_rule, write

from rules.pol_022 import RULE


@pytest.mark.parametrize(
    "rel",
    [
        "agents/demo/tools/tool/Containerfile",
        "agents/demo/tools/tool/Containerfile.cpu",
        "agents/demo/tools/tool/build.Containerfile",
        "agents/demo/tools/tool/containerfile",
        "starter-kits/demo/Containerfile",
    ],
)
def test_containerfile_names_are_blocked(repo, rel):
    write(repo, rel, "FROM ubuntu:24.04\n")

    result = run_rule(repo, RULE, [rel])

    assert files(result) == [rel]
    assert result.findings[0].line == 1
    assert "canonical Docker filename" in result.findings[0].message
    assert rel.rsplit("/", 1)[0] + "/Dockerfile" in result.findings[0].message
    assert "migrate-podman-containerfile" in result.findings[0].message


@pytest.mark.parametrize(
    "rel",
    [
        "agents/demo/tools/tool/Containerfile.in",
        "agents/demo/tools/tool/build.Containerfile.in",
        "agents/demo/tools/tool/Dockerfile.in",
        "agents/demo/tools/tool/build.Dockerfile.in",
        "agents/demo/tools/tool/build.Dockerfile.cpu.in",
    ],
)
def test_preprocessed_build_files_require_manual_migration(repo, rel):
    write(repo, rel, "FROM ubuntu:24.04\n#include \"packages.inc\"\n")

    result = run_rule(repo, RULE, [rel])

    assert files(result) == [rel]
    assert result.findings[0].line == 2
    assert ".in preprocessing" in result.findings[0].message
    assert "not safe" in result.findings[0].message


@pytest.mark.parametrize(
    "rel",
    [
        "agents/demo/tools/tool/Dockerfile",
        "agents/demo/tools/tool/Dockerfile.cpu",
        "agents/demo/tools/tool/build.Dockerfile",
        "docs/examples/Containerfile",
        "utilities/demo/Containerfile.in",
    ],
)
def test_supported_or_out_of_scope_files_pass(repo, rel):
    write(repo, rel, "FROM ubuntu:24.04\n")

    result = run_rule(repo, RULE, [rel])

    assert result.findings == []


def test_deleted_containerfile_is_ignored(repo):
    result = run_rule(repo, RULE, ["agents/demo/tools/tool/Containerfile"])

    assert result.findings == []
