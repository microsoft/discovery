"""POL-014 — approved container base image sources."""

from __future__ import annotations

import pytest
from conftest import files, run_rule, write

from rules.pol_014 import RULE

APPROVED = [
    "python:3.12-slim",                              # Docker Official Image
    "ubuntu:24.04",
    "debian:12-slim",
    "docker.io/library/python:3.11-slim",            # explicit official form
    "mcr.microsoft.com/azurelinux/base/python:3.12",  # trusted registry
    "mcr.microsoft.com/azurelinux/base/core:3.0",
    "nvidia/cuda:12.6.3-devel-ubuntu22.04",          # approved namespaces
    "pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime",
    "condaforge/mambaforge:24.3.0-0",
    "continuumio/miniconda3:latest",
    "mambaorg/micromamba:1.5-jammy",
    "opencfd/openfoam-run:2512",
    "hdlc/xyce:latest",
]

REJECTED = [
    "randomuser/sketchy-image:1.0",
    "quay.io/someorg/tool:2.0",
    "ghcr.io/attacker/payload:latest",
    "registry.example.com/internal/thing:1.0",
    "evilnamespace/cuda:12.0",
]


@pytest.mark.parametrize("image", APPROVED)
def test_approved_base_images_pass(repo, image):
    rel = write(repo, "agents/demo/tools/t/Dockerfile", f"FROM {image}\nRUN echo hi\n")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == [], f"{image} should be approved"


@pytest.mark.parametrize("image", REJECTED)
def test_unapproved_base_images_are_blocked(repo, image):
    rel = write(repo, "agents/demo/tools/t/Dockerfile", f"FROM {image}\n")
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel], f"{image} should be rejected"
    assert "base-images.yaml" in result.findings[0].message


def test_multistage_internal_references_are_not_treated_as_images(repo):
    body = (
        "FROM ubuntu:24.04 AS builder\n"
        "RUN make\n"
        "FROM ubuntu:24.04 AS runtime\n"
        "COPY --from=builder /out /out\n"
        "FROM builder\n"
    )
    rel = write(repo, "agents/demo/tools/t/Dockerfile", body)
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_every_unapproved_stage_is_reported(repo):
    body = (
        "FROM badns/one:1.0 AS a\n"
        "FROM ubuntu:24.04 AS b\n"
        "FROM otherns/two:2.0 AS c\n"
    )
    rel = write(repo, "agents/demo/tools/t/Dockerfile", body)
    result = run_rule(repo, RULE, [rel])
    assert len(result.findings) == 2
    assert [f.line for f in result.findings] == [1, 3]


def test_platform_flag_is_ignored(repo):
    rel = write(repo, "agents/demo/tools/t/Dockerfile",
                "FROM --platform=linux/amd64 randomuser/img:1.0\n")
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]


@pytest.mark.parametrize("name", ["Dockerfile", "Dockerfile.gpu", "gpu.Dockerfile"])
def test_dockerfile_naming_variants_are_checked(repo, name):
    rel = write(repo, f"agents/demo/tools/t/{name}", "FROM randomuser/img:1.0\n")
    result = run_rule(repo, RULE, [rel])
    assert files(result) == [rel]


def test_non_dockerfiles_are_ignored(repo):
    rel = write(repo, "agents/demo/tools/t/notes.md", "FROM randomuser/img:1.0\n")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_dockerfiles_outside_guarded_trees_are_ignored(repo):
    rel = write(repo, "utilities/toolbox/Dockerfile", "FROM randomuser/img:1.0\n")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


@pytest.mark.parametrize("image", [
    "{acr}.azurecr.io/retrochimera-deps:1.1.0",
    "{name}.azurecr.io/alphafold:latest",
])
def test_deployer_registry_placeholders_are_not_third_party(repo, image):
    # The deployer rewrites these to the target subscription's own ACR.
    rel = write(repo, "agents/demo/tools/t/Dockerfile.acr", f"FROM {image}\n")
    result = run_rule(repo, RULE, [rel])
    assert result.findings == []


def test_every_shipped_dockerfile_uses_an_approved_base(repo):
    """The 51 Dockerfiles already in the catalog must satisfy this policy."""
    from pathlib import Path

    from dockerfile_parser import external_images
    from rules.base import PolicyConfig

    repo_root = Path(__file__).resolve().parents[3]
    policy = PolicyConfig.load(repo_root)

    offenders = []
    for df in sorted((repo_root / "agents").rglob("Dockerfile*")):
        for directive in external_images(df.read_text(encoding="utf-8", errors="replace")):
            img = directive.image
            if img.is_deployer_placeholder:
                continue
            if not policy.is_approved_base_image(
                img.registry, img.namespace_ref, img.is_docker_official
            ):
                offenders.append(f"{df.relative_to(repo_root)}:{directive.line} {img.raw}")

    assert not offenders, "Unapproved base images in the catalog:\n" + "\n".join(offenders)
