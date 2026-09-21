#!/usr/bin/env python3
"""
generate_baseline.py — record pre-existing rule violations for the ratchet.

A stricter ruleset cannot ship as a hard failure against content that predates
it. This script runs the modular rules over the whole catalog and writes the
violations it finds to `.github/policy/baseline.json`. The engine downgrades
anything in that file to a non-blocking warning, so legacy agents keep
building while any *new* violation of the same rule blocks the PR.

The baseline is a debt register, not an amnesty: entries are expected to
shrink, and `--check` fails when the baseline has grown.

Usage:
    python .github/scripts/generate_baseline.py            # write baseline
    python .github/scripts/generate_baseline.py --check    # CI drift gate
    python .github/scripts/generate_baseline.py --report   # human summary
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from rules.registry import (
    build_context,
    discover_rules,
    parse_baseline_document,
    run_rules,
)

GUARDED_DIRS = ("agents", "starter-kits")
BASELINE_PATH = Path(".github") / "policy" / "baseline.json"


def tracked_files(repo: Path) -> list[str]:
    """All git-tracked files under the guarded trees.

    Falls back to a filesystem walk when git is unavailable, so the script
    still works in a source archive.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "--", *GUARDED_DIRS],
            cwd=str(repo), capture_output=True, text=True, check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return [line.strip() for line in out.stdout.splitlines() if line.strip()]
    except (FileNotFoundError, OSError):
        pass

    found: list[str] = []
    for d in GUARDED_DIRS:
        root = repo / d
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                found.append(str(path.relative_to(repo)).replace("\\", "/"))
    return sorted(found)


def audit(repo: Path) -> tuple[list[dict], list[dict], list[str]]:
    """Run every rule over the whole catalog.

    Returns ``(blocking, warnings, config_errors)``. ``config_errors`` combines
    policy-configuration failures (malformed source-allowlist / base-images /
    tag-taxonomy) with run-engine config errors (waivers). A non-empty list
    means the ruleset itself is invalid, so any baseline derived from this run
    would be built on an incomplete ruleset and must be rejected.

    One pass, not two — executing the full ruleset over every tracked file is
    the expensive part of this script.
    """
    ctx = build_context(repo, tracked_files(repo))
    result = run_rules(ctx, discover_rules(), apply_ratchet=False)

    def _rows(findings) -> list[dict]:
        return sorted(
            ({"rule_id": f.rule_id, "file": f.file, "message": f.message}
             for f in findings),
            key=lambda v: (v["rule_id"], v["file"]),
        )

    config_errors = [
        f"{rel_path}: {message}" for rel_path, message in ctx.policy.config_errors
    ]
    config_errors.extend(result.config_errors)

    # Only blocking findings belong in the baseline. Warning-severity rules are
    # already non-blocking, so recording them would suppress signal the rule
    # exists to surface.
    return _rows(result.blocking), _rows(result.warnings), config_errors


def load_existing(repo: Path) -> list[dict]:
    path = repo / BASELINE_PATH
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"could not read {BASELINE_PATH}: {exc}") from exc

    # Reuse the same strict validation the runtime baseline loader applies, so
    # `--check` and production never disagree on what a valid baseline is.
    pairs, errors = parse_baseline_document(payload)
    if errors:
        raise ValueError(f"{BASELINE_PATH}: " + "; ".join(errors))
    return [{"rule_id": rule_id, "file": file} for rule_id, file in pairs]


def write_baseline(repo: Path, violations: list[dict]) -> None:
    path = repo / BASELINE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    pairs = sorted({(v["rule_id"], v["file"]) for v in violations})
    payload = {
        "_comment": (
            "Pre-existing rule violations recorded at ruleset rollout. Entries "
            "here are reported as warnings instead of blocking. Do not add to "
            "this file by hand — fix the violation, or request a waiver in "
            ".github/policy/waivers.yaml. Regenerate with "
            "python .github/scripts/generate_baseline.py"
        ),
        "count": len(pairs),
        "violations": [
            {"rule_id": rule_id, "file": file} for rule_id, file in pairs
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def summarize(violations: list[dict]) -> str:
    if not violations:
        return "No violations found across agents/ and starter-kits/."
    by_rule = Counter(v["rule_id"] for v in violations)
    lines = [f"{len(violations)} violation(s) across {len(by_rule)} rule(s):", ""]
    for rule_id, count in sorted(by_rule.items()):
        lines.append(f"  {rule_id}: {count}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    parser.add_argument("--check", action="store_true",
                        help="Fail if the catalog has violations not already baselined.")
    parser.add_argument("--report", action="store_true",
                        help="Print a per-rule summary and per-file detail.")
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    violations, warnings, config_errors = audit(repo)

    # A malformed policy makes the whole ruleset untrustworthy. Refuse to
    # report, check, or write a baseline derived from an invalid configuration.
    if config_errors:
        print("POLICY CONFIGURATION ERROR — refusing to generate a baseline "
              "from an invalid ruleset:", file=sys.stderr)
        for err in config_errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    if args.report:
        print(summarize(violations))
        if violations:
            print()
            for v in violations:
                print(f"  [{v['rule_id']}] {v['file']}")
                print(f"      {v['message']}")

        if warnings:
            by_rule = Counter(w["rule_id"] for w in warnings)
            print(f"\n{len(warnings)} non-blocking warning(s):")
            for rule_id, count in sorted(by_rule.items()):
                print(f"  {rule_id}: {count}")
        return 0

    if args.check:
        try:
            existing = load_existing(repo)
        except ValueError as exc:
            print(f"BASELINE ERROR: {exc}", file=sys.stderr)
            return 1
        recorded = {(v["rule_id"], v["file"]) for v in existing}
        current = {(v["rule_id"], v["file"]) for v in violations}
        added = sorted(current - recorded)
        if added:
            print("Catalog has violations that are not in the ratchet baseline:\n")
            for rule_id, file in added:
                print(f"  [{rule_id}] {file}")
            print("\nFix them, or regenerate the baseline if this is an intentional rollout.")
            return 1
        removed = recorded - current
        if removed:
            print(f"{len(removed)} baselined violation(s) have been fixed — "
                  f"regenerate the baseline to lock in the improvement.")
        print(summarize(violations))
        return 0

    write_baseline(repo, violations)
    print(f"Wrote {BASELINE_PATH} — {len(violations)} violation(s).")
    print(summarize(violations))
    return 0


if __name__ == "__main__":
    sys.exit(main())
