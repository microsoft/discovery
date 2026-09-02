#!/usr/bin/env python3
"""Dispatch the reusable branch or PR-shadow validation workflow with GitHub CLI."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys


WORKFLOW = "validate-everything.yml"
DEFAULT_REPOSITORY = "microsoft/discovery"


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def current_branch() -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        check=False,
        capture_output=True,
        text=True,
    )
    branch = result.stdout.strip()
    if result.returncode != 0 or not branch:
        raise RuntimeError("Could not determine the current branch; pass --ref explicitly.")
    return branch


def build_dispatch_command(
    repository: str,
    ref: str,
    reason: str,
    pr_number: int | None,
) -> list[str]:
    command = [
        "gh",
        "workflow",
        "run",
        WORKFLOW,
        "--repo",
        repository,
        "--ref",
        ref,
        "-f",
        f"reason={reason}",
    ]
    if pr_number is not None:
        command.extend(["-f", f"pr_number={pr_number}"])
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pr-number",
        type=positive_int,
        help="Open internal or fork PR to inspect; omit for a branch smoke test.",
    )
    parser.add_argument(
        "--ref",
        help="Trusted workflow branch or SHA (default: current Git branch).",
    )
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY)
    parser.add_argument("--reason", help="Label shown in the Actions run title.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if shutil.which("gh") is None:
        print("GitHub CLI is required: https://cli.github.com/", file=sys.stderr)
        return 2

    auth = subprocess.run(
        ["gh", "auth", "status", "--hostname", "github.com"],
        check=False,
    )
    if auth.returncode != 0:
        print("Authenticate first with: gh auth login -h github.com", file=sys.stderr)
        return 2

    try:
        ref = args.ref or current_branch()
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    reason = args.reason or (
        "Queued PR shadow test" if args.pr_number else "Candidate branch smoke test"
    )
    command = build_dispatch_command(args.repo, ref, reason, args.pr_number)
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        return result.returncode

    print("Validation test dispatched. Inspect recent runs with:")
    print(
        f"  gh run list --repo {args.repo} --workflow {WORKFLOW} "
        f"--branch {ref} --event workflow_dispatch --limit 10"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())