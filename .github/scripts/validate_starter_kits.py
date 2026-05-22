#!/usr/bin/env python3
"""
validate_starter_kits.py — PR-time validation for discovery-catalog starter kits.

Checks performed (in order):
  SKT-SCH-001  JSON Schema validation against docs/schemas/starter-kit-schema.json
  SKT-STR-001  name field equals parent directory name
  SKT-STR-003  Exactly one agentRef with role:primary and required:true
  SKT-STR-006  No duplicate ref values within agentRefs[]
  SKT-STR-008  Kit folder must contain only kit.json (no other files)
  SKT-REF-001  For active kits: every agentRef.ref exists in dry-run registry build
  SKT-POL-001  Newly added kit directories must have lifecycle:active
  SKT-AST-001  logo / screenshots, if set, must be HTTPS URLs (kit folder cannot host assets)

Usage:
  python .github/scripts/validate_starter_kits.py --repo-root .
  python .github/scripts/validate_starter_kits.py --repo-root . --changed-kits protein-structure-analysis
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import jsonschema
except ImportError:
    print("ERROR: jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(1)


def load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def load_schema(repo_root: Path, schema_name: str) -> dict:
    schema_path = repo_root / "docs" / "schemas" / schema_name
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")
    return load_json(schema_path)


def build_dry_run_registry(repo_root: Path) -> set[str]:
    """Run update_registry.py on the current checkout; return set of agent path strings."""
    script = repo_root / ".github" / "scripts" / "update_registry.py"
    if not script.exists():
        raise FileNotFoundError(f"update_registry.py not found: {script}")
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--repo-root", str(repo_root), "--output", tmp_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"update_registry.py failed:\n{result.stderr}")
        registry = load_json(Path(tmp_path))
        return {
            e["path"]
            for e in registry.get("entries", [])
            if e.get("type") == "agent"
        }
    finally:
        os.unlink(tmp_path)


def get_kit_dirs(repo_root: Path) -> list[Path]:
    """Return all kit directories directly under starter-kits/."""
    kits = []
    base = repo_root / "starter-kits"
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if d.is_dir() and (d / "kit.json").exists():
                kits.append(d)
    return kits


def get_kit_relpath(repo_root: Path, kit_dir: Path) -> str:
    """Return canonical kit identifier, e.g. 'protein-structure-analysis'."""
    return str(kit_dir.relative_to(repo_root / "starter-kits")).replace(os.sep, "/")


def get_git_added_relpaths(repo_root: Path) -> set[str]:
    """Return set of canonical kit relpaths (e.g. 'my-kit') newly added in this branch vs main."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=A", "origin/main...HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        if result.returncode != 0:
            print(
                f"  WARNING: git diff failed (SKT-POL-001 policy check disabled). "
                f"Ensure 'origin/main' is fetched.\n  stderr: {result.stderr.strip()}",
                file=sys.stderr,
            )
            return set()
        added = set()
        for line in result.stdout.splitlines():
            parts = Path(line).parts
            # starter-kits/<name>/... → "<name>"
            if len(parts) >= 2 and parts[0] == "starter-kits":
                added.add(parts[1])
        return added
    except Exception as e:
        print(f"  WARNING: git diff exception (SKT-POL-001 policy check disabled): {e}", file=sys.stderr)
        return set()


def validate_kit(
    kit_dir: Path,
    kit_rel_path: str,
    manifest: dict,
    kit_schema: dict,
    agent_paths: set[str],
    added_kit_relpaths: set[str],
    errors: list[str],
    warnings: list[str],
) -> None:
    name = kit_dir.name
    lifecycle = manifest.get("lifecycle", "")

    # SKT-SCH-001: JSON Schema validation
    try:
        validator = jsonschema.Draft7Validator(kit_schema)
        schema_errors = sorted(validator.iter_errors(manifest), key=lambda e: list(e.path))
        for err in schema_errors:
            path_str = " -> ".join(str(p) for p in err.absolute_path) or "(root)"
            errors.append(f"[{kit_rel_path}] SKT-SCH-001: Schema error at {path_str}: {err.message}")
    except jsonschema.SchemaError as e:
        errors.append(f"[{kit_rel_path}] SKT-SCH-001: Invalid schema file: {e.message}")

    # SKT-STR-001: name == leaf directory name
    if manifest.get("name") != name:
        errors.append(
            f"[{kit_rel_path}] SKT-STR-001: name field '{manifest.get('name')}' must equal directory name '{name}'"
        )

    # SKT-STR-003: exactly one primary+required agentRef
    agent_refs = manifest.get("agentRefs", [])
    primary_refs = [r for r in agent_refs if r.get("role") == "primary" and r.get("required") is True]
    if len(primary_refs) != 1:
        errors.append(
            f"[{kit_rel_path}] SKT-STR-003: Expected exactly 1 agentRef with role:primary and required:true, found {len(primary_refs)}"
        )

    # SKT-STR-006: no duplicate refs
    all_refs = [r.get("ref") for r in agent_refs if r.get("ref")]
    if len(all_refs) != len(set(all_refs)):
        seen: set[str] = set()
        dupes = [r for r in all_refs if r in seen or seen.add(r)]  # type: ignore[func-returns-value]
        errors.append(f"[{kit_rel_path}] SKT-STR-006: Duplicate agentRef values: {dupes}")

    # SKT-REF-001: active kits — each ref must exist in dry-run registry
    if lifecycle == "active":
        for ref_entry in agent_refs:
            ref = ref_entry.get("ref", "")
            if ref not in agent_paths:
                errors.append(
                    f"[{kit_rel_path}] SKT-REF-001: agentRef '{ref}' not found in registry dry-run build "
                    f"(agent must have a valid metadata.yaml with name field)"
                )
    elif lifecycle == "archived":
        for ref_entry in agent_refs:
            ref = ref_entry.get("ref", "")
            if ref not in agent_paths:
                warnings.append(
                    f"[{kit_rel_path}] SKT-REF-001 (archived, informational): agentRef '{ref}' not in registry"
                )

    # SKT-POL-001: newly added kits must have lifecycle:active
    if kit_rel_path in added_kit_relpaths and lifecycle != "active":
        errors.append(
            f"[{kit_rel_path}] SKT-POL-001: Newly added kit must have lifecycle:active, got '{lifecycle}'"
        )

    # SKT-STR-008: kit.json must be the ONLY file in the kit folder
    extra_entries = sorted(
        p.name for p in kit_dir.iterdir()
        if p.name != "kit.json"
    )
    if extra_entries:
        errors.append(
            f"[{kit_rel_path}] SKT-STR-008: starter-kits/{kit_rel_path}/ must contain only 'kit.json'; "
            f"found extra entr{'y' if len(extra_entries) == 1 else 'ies'}: {extra_entries}. "
            f"Move logos, screenshots, READMEs, or any other assets out of the kit folder and reference them via HTTPS URLs."
        )

    # SKT-AST-001: logo / screenshots, if set, must be HTTPS URLs since the
    # kit folder is restricted to kit.json only. Relative paths are not permitted.
    def _check_asset(asset_value: str, field: str) -> None:
        s = str(asset_value or "")
        if not s.startswith("https://"):
            errors.append(
                f"[{kit_rel_path}] SKT-AST-001: {field} '{asset_value}' must be an HTTPS URL; "
                f"assets cannot live inside the kit folder (see SKT-STR-008)."
            )

    logo = manifest.get("logo")
    if logo:
        _check_asset(logo, "logo")
    for screenshot in manifest.get("screenshots", []) or []:
        _check_asset(screenshot, "screenshot")


def run_validations(repo_root: Path, changed_kit_relpaths: list[str] | None) -> int:
    errors: list[str] = []
    warnings: list[str] = []

    # Load schemas
    try:
        kit_schema = load_schema(repo_root, "starter-kit-schema.json")
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # Build dry-run registry once for all kits
    print("Building dry-run registry from current checkout...")
    try:
        agent_paths = build_dry_run_registry(repo_root)
        print(f"  Registry contains {len(agent_paths)} agent entries")
    except Exception as e:
        print(f"ERROR: Could not build dry-run registry: {e}", file=sys.stderr)
        return 1

    # Get all kit dirs and newly added ones
    all_kit_dirs = get_kit_dirs(repo_root)
    added_kit_relpaths_set = get_git_added_relpaths(repo_root)

    # Build relpath→dir mapping
    all_kits: list[tuple[str, Path]] = [
        (get_kit_relpath(repo_root, d), d) for d in all_kit_dirs
    ]

    if changed_kit_relpaths:
        kits_to_check = [
            (rp, d) for rp, d in all_kits if rp in changed_kit_relpaths
        ]
    else:
        kits_to_check = all_kits

    if not kits_to_check:
        print("No starter kits found to validate.")

    # Load manifests for all kits (needed for duplicate check)
    all_manifests: list[tuple[str, Path, dict]] = []
    for kit_relpath, kit_dir in all_kits:
        try:
            manifest = load_json(kit_dir / "kit.json")
            all_manifests.append((kit_relpath, kit_dir, manifest))
        except json.JSONDecodeError as e:
            errors.append(f"[{kit_relpath}] Invalid JSON in kit.json: {e}")

    # SKT-DUP-001: name must be globally unique across ALL kits
    name_to_kits: dict[str, list[str]] = {}
    for kit_relpath, _, manifest in all_manifests:
        n = manifest.get("name", "")
        name_to_kits.setdefault(n, []).append(kit_relpath)
    for n, paths in name_to_kits.items():
        if len(paths) > 1:
            errors.append(
                f"SKT-DUP-001: Kit name '{n}' is not globally unique — used by: {paths}"
            )

    # Validate each changed kit
    for kit_relpath, kit_dir in kits_to_check:
        plugin_path = kit_dir / "kit.json"
        print(f"Validating {kit_relpath}...")
        # Find pre-loaded manifest
        manifest_entry = next((m for rp, _, m in all_manifests if rp == kit_relpath), None)
        if manifest_entry is None:
            # Already reported as parse error above
            continue
        validate_kit(
            kit_dir, kit_relpath, manifest_entry, kit_schema,
            agent_paths, added_kit_relpaths_set, errors, warnings,
        )

    # Print results
    for warning in warnings:
        print(f"  WARNING: {warning}")
    for error in errors:
        print(f"  ERROR: {error}")

    if errors:
        print(f"\n✗ Validation failed with {len(errors)} error(s).")
        return 1

    print(f"\n✓ All checks passed. {len(warnings)} warning(s).")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate starter kit kit.json files.")
    parser.add_argument("--repo-root", required=True, help="Repository root directory")
    parser.add_argument(
        "--changed-kits",
        nargs="*",
        help=(
            "Canonical kit relpaths to validate (default: all). "
            "E.g. --changed-kits protein-structure-analysis my-other-kit"
        ),
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    if not repo_root.is_dir():
        print(f"ERROR: repo-root does not exist: {repo_root}", file=sys.stderr)
        sys.exit(1)

    sys.exit(run_validations(repo_root, args.changed_kits))


if __name__ == "__main__":
    main()
