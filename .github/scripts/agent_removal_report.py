"""Schema-version-1 data protocol shared by the removal gate and reporter.

The workflow creates not_applicable/error records when validation is skipped;
the gate CLI emits success/blocked/error records for actual validation.
This module's CLI checks protocol validity and the expected gate exit code.
A consistent blocked record validates with exit 0 here, without clearing the
original validator failure. It never performs GitHub API requests or publishing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any


REPORT_FILE = "agent-removal-results.json"
MAX_REPORT_BYTES = 5 * 1024 * 1024
MAX_STRING = 16_000
GUIDANCE = "docs/authoring-guides/starter-kit-authoring-guide.md"


def catalog_path(value: Any, root: str) -> bool:
    if not isinstance(value, str) or not value or len(value) > MAX_STRING:
        return False
    path = PurePosixPath(value)
    return (
        len(path.parts) == 2 and path.parts[0] == root
        and path.parts[1] not in {".", ".."} and str(path) == value
        and not any(character in value for character in ("\\", "\0", "\r", "\n"))
    )


def result(
    outcome: str, *, removed_paths: list[str] | None = None,
    impacted_kits: list[dict[str, Any]] | None = None,
    issues: list[str] | None = None, approved: bool = False,
    reason: str = "Not evaluated.",
) -> dict[str, Any]:
    return {
        "schema_version": 1, "outcome": outcome,
        "exit_code": 0 if outcome in {"success", "not_applicable"} else 1,
        "removed_paths": removed_paths or [], "impacted_kits": impacted_kits or [],
        "issues": issues or [], "override": {"approved": approved, "reason": reason},
        "guidance": GUIDANCE,
    }


def validate_report(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise ValueError("Removal report must be an object.")
    outcome = report.get("outcome")
    if (
        type(report.get("schema_version")) is not int or report["schema_version"] != 1
        or not isinstance(outcome, str)
        or outcome not in {"success", "blocked", "not_applicable", "error"}
        or type(report.get("exit_code")) is not int
        or report["exit_code"] != (0 if outcome in {"success", "not_applicable"} else 1)
    ):
        raise ValueError("Invalid removal report version, outcome, or exit code.")
    removed = report.get("removed_paths")
    kits = report.get("impacted_kits")
    issues = report.get("issues")
    override = report.get("override")
    if (
        not isinstance(removed, list) or not all(catalog_path(p, "agents") for p in removed)
        or len(set(removed)) != len(removed) or not isinstance(kits, list)
        or not isinstance(issues, list)
        or not all(isinstance(s, str) and 0 < len(s) <= MAX_STRING for s in issues)
        or not isinstance(override, dict) or type(override.get("approved")) is not bool
        or not isinstance(override.get("reason"), str)
        or not 0 < len(override["reason"]) <= MAX_STRING
    ):
        raise ValueError("Invalid removal paths, issues, or override decision.")
    kit_paths = []
    for kit in kits:
        if not isinstance(kit, dict) or not catalog_path(kit.get("path"), "starter-kits"):
            raise ValueError("Invalid impacted starter-kit path.")
        refs = kit.get("required_refs")
        if (
            not isinstance(refs, list) or not refs
            or not all(catalog_path(ref, "agents") and ref in removed for ref in refs)
            or len(set(refs)) != len(refs)
        ):
            raise ValueError("Impacted required references must identify removed agents.")
        kit_paths.append(kit["path"])
    if len(set(kit_paths)) != len(kit_paths):
        raise ValueError("Duplicate impacted starter kit.")
    if (
        (outcome == "blocked" and (not kits or not issues or override["approved"]))
        or (outcome == "error" and (not issues or override["approved"]))
        or (outcome == "not_applicable" and (removed or kits or issues or override["approved"]))
        or (outcome == "success" and (issues or (kits and not override["approved"])))
    ):
        raise ValueError("Removal outcome contradicts its diagnostic details.")
    guidance = report.get("guidance")
    if guidance != GUIDANCE:
        raise ValueError("Removal guidance must identify the fixed starter-kit authoring guide.")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a local removal-gate result.")
    parser.add_argument("report", type=Path)
    parser.add_argument("--expected-exit-code", type=int, choices=(0, 1), required=True)
    args = parser.parse_args()
    try:
        data = args.report.read_bytes()
        if len(data) > MAX_REPORT_BYTES:
            raise ValueError("Removal report exceeds the size limit.")
        report = validate_report(json.loads(data))
        if report["exit_code"] != args.expected_exit_code:
            raise ValueError("Removal report contradicts the validator step outcome.")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
