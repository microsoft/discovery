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


def test_stage_alias_reference_is_not_external():
    text = "FROM ubuntu:24.04 AS builder\nFROM builder\n"
    images = external_images(text)
    assert [d.image.repository for d in images] == ["ubuntu"]


@pytest.mark.parametrize("line", [
    "FROM {acr}.azurecr.io/tool:1.0.0",
    "FROM {registry}.example.io/library/python:3.12",
])
def test_deployer_placeholder_is_recognized(line):
    directives = parse_from_directives(line + "\n")
    assert directives[0].image.is_deployer_placeholder


def test_docker_official_image_detection():
    assert parse_image_ref("ubuntu:24.04").is_docker_official
    assert not parse_image_ref("condaforge/mambaforge:24.3.0-0").is_docker_official
