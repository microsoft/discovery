#!/usr/bin/env python3
"""Validate changed Discovery catalog files and write CI-friendly JSON results."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from catalog_validation.contributor_scope import (
    check_contributor_scope,
    is_trusted_registry_refresh as _is_trusted_registry_refresh,
)
from catalog_validation.documentation import check_documentation
from catalog_validation.findings import Failure
from catalog_validation.policy_checks import (
    MODEL_WEIGHT_MAX_BYTES,
    PICKLE_ALLOWLIST,
    _is_ci,
    _is_env_artefact,
    _is_lfs_tracked,
    _is_lfs_tracked_strict as _policy_is_lfs_tracked_strict,
    _picklescan_unsafe_imports,
    check_model_weights,
    check_policy,
)
from catalog_validation.runner import run_validation
from catalog_validation.schema_checks import (
    _load_valid_regions as load_valid_regions,
    check_schema,
)
from catalog_validation.schemas import (
    build_schema_registry,
    load_json_schema,
    load_yaml,
    validate_against_schema,
)
from catalog_validation.structural import check_structural
from rules.registry import build_context


def _is_lfs_tracked_strict(repo: Path, rel_path: str, extension: str) -> bool:
    """Compatibility adapter that preserves monkeypatching of this module."""
    return _policy_is_lfs_tracked_strict(
        repo,
        rel_path,
        extension,
        tracker=_is_lfs_tracked,
    )


def is_agent_path(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    return normalized.startswith("agents/") and not normalized.startswith("agents/tmp/")


def agent_folder_of(rel: str) -> Path | None:
    parts = Path(rel.replace("\\", "/")).parts
    if len(parts) >= 2 and parts[0] == "agents" and parts[1] != "tmp":
        return Path(parts[0], parts[1])
    return None


def discover_folders(repo: Path, changed_files: list[str]) -> set[Path]:
    """Compatibility wrapper around the shared rule-context discovery."""
    return build_context(repo, changed_files).agent_folders


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a Discovery Catalog PR.")
    parser.add_argument(
        "--changed-files",
        required=True,
        help="Newline-delimited file listing changed paths (relative to repo root).",
    )
    parser.add_argument(
        "--repo-root",
        default=os.getcwd(),
        help="Absolute path to repository root.",
    )
    parser.add_argument(
        "--output",
        default="validation-results.json",
        help="Path to write JSON results.",
    )
    return parser.parse_args()


def main() -> None:
    _configure_console()
    args = _parse_args()
    repo = Path(args.repo_root).resolve()
    with open(args.changed_files, encoding="utf-8") as changed_file:
        changed_files = [line.strip() for line in changed_file if line.strip()]

    result = run_validation(
        repo,
        changed_files,
        author_permission=os.environ.get("PR_AUTHOR_PERMISSION"),
        author=os.environ.get("PR_AUTHOR", ""),
        head_ref=os.environ.get("PR_HEAD_REF", ""),
    )
    for warning in result.setup_warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    with open(args.output, "w", encoding="utf-8") as output_file:
        json.dump(result.to_dict(), output_file, indent=2)

    if result.warnings:
        print(f"\nWARNING: {len(result.warnings)} non-blocking warning(s):\n")
        for warning in result.warnings:
            print(
                f"  [{warning.rule_id}] {warning.file}:{warning.line} - {warning.message}"
            )

    if result.blocking:
        print(f"\nValidation failed - {len(result.blocking)} issue(s) found:\n")
        for failure in result.blocking:
            print(
                f"  [{failure.rule_id}] {failure.file}:{failure.line} - {failure.message}"
            )
        raise SystemExit(1)

    print("\nAll validation checks passed.")
    raise SystemExit(0)


if __name__ == "__main__":
    main()