"""Unit tests for the minimal Dockerfile parser.

The parser is intentionally partial, but it is used as a policy boundary
(POL-014/POL-017 and compute_tags), so the edge cases it *does* claim to handle
must stay correct: line continuations, ARG scope, registry ports, digest-only
references, and comments.
"""

from __future__ import annotations

import pytest

from dockerfile_parser import (
    external_images,
    parse_from_directives,
    parse_image_ref,
)

DIGEST = "sha256:" + "0" * 64


def _only(text: str):
    directives = external_images(text)
    assert len(directives) == 1, directives
    return directives[0].image


def test_comment_lines_are_ignored():
    text = "# FROM evil/image:latest\nFROM ubuntu:24.04\n"
    images = external_images(text)
    assert [img.raw for img in (d.image for d in images)] == ["ubuntu:24.04"]


def test_multiline_from_is_joined():
    text = "FROM \\\n  ubuntu:24.04\n"
    directives = parse_from_directives(text)
    assert len(directives) == 1
    assert directives[0].line == 1
    assert directives[0].image is not None
    assert directives[0].image.repository == "ubuntu"
    assert directives[0].image.tag == "24.04"


def test_multiline_from_with_platform_flag_is_joined():
    text = "FROM --platform=$BUILDPLATFORM \\\n  python:3.12-slim AS build\n"
    directives = parse_from_directives(text)
    assert len(directives) == 1
    assert directives[0].alias == "build"
    assert directives[0].image.repository == "python"
    assert directives[0].image.tag == "3.12-slim"


def test_global_arg_default_resolves_a_later_from():
    text = "ARG TAG=24.04\nFROM ubuntu:${TAG}\n"
    image = _only(text)
    assert image.tag == "24.04"
    assert not image.tag_is_variable


def test_arg_declared_after_from_does_not_resolve_that_stage():
    # A stage-local ARG declared *after* the FROM cannot pin it: the value is
    # unknown at the point the base image is selected.
    text = "FROM ubuntu:${TAG}\nARG TAG=24.04\n"
    image = _only(text)
    assert image.tag == "${TAG}"
    assert image.tag_is_variable


def test_registry_port_is_part_of_the_registry_not_the_tag():
    image = parse_image_ref("localhost:5000/team/img:1.0")
    assert image.registry == "localhost:5000"
    assert image.namespace == "team"
    assert image.repository == "img"
    assert image.tag == "1.0"


def test_registry_port_with_variable_tag():
    image = _only("FROM registry.example.com:8443/ns/app:${V}\n")
    assert image.registry == "registry.example.com:8443"
    assert image.repository == "app"
    assert image.tag_is_variable


def test_digest_only_reference_has_no_tag():
    image = _only(f"FROM ubuntu@{DIGEST}\n")
    assert image.tag is None
    assert image.digest == DIGEST


def test_tag_and_digest_reference_keeps_both():
    image = _only(f"FROM ubuntu:24.04@{DIGEST}\n")
    assert image.tag == "24.04"
    assert image.digest == DIGEST


def test_digest_validation_rejects_variables_and_malformed_values():
    valid = parse_image_ref(f"ubuntu:latest@{DIGEST}")
    variable = parse_image_ref("ubuntu:latest@${DIGEST}")
    malformed = parse_image_ref("ubuntu:latest@sha256:not-hex")

    assert valid.has_valid_digest
    assert not valid.has_unresolved_variable
    assert variable.has_unresolved_variable
    assert not variable.has_valid_digest
    assert not malformed.has_valid_digest


def test_stage_alias_reference_is_not_external():
    text = "FROM ubuntu:24.04 AS builder\nFROM builder\n"
    images = external_images(text)
    assert [d.image.repository for d in images] == ["ubuntu"]


@pytest.mark.parametrize("line", [
    "FROM {acr}.azurecr.io/tool:1.0.0",
    "FROM {registry}.azurecr.io/library/python:3.12",
])
def test_deployer_placeholder_is_recognized(line):
    directives = parse_from_directives(line + "\n")
    assert directives[0].image.is_deployer_placeholder


@pytest.mark.parametrize("line", [
    "FROM {attacker}.evil.example/payload:latest",
    "FROM {registry}.example.io/library/python:3.12",
    "FROM {acr}.azurecr.io.evil.example/payload:latest",
])
def test_non_acr_brace_registry_is_not_a_placeholder(line):
    # Only a genuine ``{name}.azurecr.io`` placeholder is rewritten by the
    # deployer; any other braced host must not be waved through.
    directives = parse_from_directives(line + "\n")
    assert not directives[0].image.is_deployer_placeholder


def test_arg_inside_earlier_stage_does_not_leak_to_a_later_stage():
    # ARG declared *after* the first FROM is stage-local; it must not resolve a
    # ``${VAR}`` in a subsequent stage's base image.
    text = (
        "FROM ubuntu:24.04 AS build\n"
        "ARG TAG=24.04\n"
        "FROM debian:${TAG}\n"
    )
    images = external_images(text)
    assert images[-1].image.tag == "${TAG}"
    assert images[-1].image.tag_is_variable


def test_unresolved_variable_image_is_not_docker_official():
    # ``FROM ${IMAGE}`` parses as ``docker.io/library/${IMAGE}`` but its identity
    # is unknown, so it must never qualify for the official-image exemption.
    image = _only("FROM ${IMAGE}\n")
    assert image.has_unresolved_variable
    assert not image.is_docker_official


def test_unresolved_variable_in_registry_is_detected():
    image = _only("FROM ${REGISTRY}/library/ubuntu:24.04\n")
    assert image.has_unresolved_variable
    assert not image.is_docker_official


def test_docker_official_image_detection():
    assert parse_image_ref("ubuntu:24.04").is_docker_official
    assert not parse_image_ref("condaforge/mambaforge:24.3.0-0").is_docker_official


def test_nested_library_path_is_not_docker_official():
    """``library`` as the first of several path components does not make an
    image official — only a single-component repo under it does."""
    ref = parse_image_ref("docker.io/library/untrusted/payload:tag")
    assert ref.namespace == "library"
    assert ref.repository == "untrusted/payload"
    assert not ref.is_docker_official
    # The genuine official form still resolves.
    assert parse_image_ref("docker.io/library/ubuntu:24.04").is_docker_official
