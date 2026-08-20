"""Tests for the reusable manual validation dispatcher."""

import argparse

import pytest

from run_validation_workflow import build_dispatch_command, positive_int


def test_branch_dispatch_omits_pr_input():
    command = build_dispatch_command(
        "microsoft/discovery",
        "users/example/pipeline",
        "Branch smoke test",
        None,
    )

    assert command == [
        "gh",
        "workflow",
        "run",
        "validate-everything.yml",
        "--repo",
        "microsoft/discovery",
        "--ref",
        "users/example/pipeline",
        "-f",
        "reason=Branch smoke test",
    ]


def test_pr_dispatch_includes_pr_input():
    command = build_dispatch_command(
        "microsoft/discovery",
        "users/example/pipeline",
        "Fork canary",
        110,
    )

    assert command[-2:] == ["-f", "pr_number=110"]


@pytest.mark.parametrize("value", ["0", "-1"])
def test_pr_number_must_be_positive(value: str):
    with pytest.raises(argparse.ArgumentTypeError):
        positive_int(value)