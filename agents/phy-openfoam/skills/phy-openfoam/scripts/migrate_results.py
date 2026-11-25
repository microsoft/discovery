"""Copy unsigned generated artifacts byte-for-byte into project-owned results.

Removal is a separate explicit opt-in after full source/destination verification.
Signed native records, keys and runtime state are never migrated or rewritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

_file = Path(__file__).resolve().with_name("project_results.py")
policy = ModuleType("phy_openfoam_migration_policy")
policy.__file__ = str(_file)
exec(compile(_file.read_text(encoding="utf-8"), str(_file), "exec"), policy.__dict__)
FORBIDDEN_NAMES = {"journal.jsonl", "journal.key", ".env", "config.json"}
FORBIDDEN_EXTENSIONS = {".key", ".pem", ".pfx", ".p12"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(source: Path) -> dict:
    if not source.is_dir() or policy.linked(source):
        raise ValueError("Migration source must be an unlinked existing unsigned directory")
    if any((p / "journal.jsonl").is_file() for p in (source, *source.parents)):
        raise ValueError("Signed native records must remain in their original store")
    files = {}
    for base, directories, names in os.walk(source, followlinks=False):
        parent = Path(base)
        for name in [*directories, *names]:
            item = parent / name
            if policy.linked(item):
                raise ValueError("A linked/reparse migration artifact requires separate operator review")
        for name in names:
            item = parent / name
            if name in FORBIDDEN_NAMES or item.suffix.lower() in FORBIDDEN_EXTENSIONS:
                raise ValueError("Signed records, keys or runtime configuration are not unsigned report artifacts")
            files[item.relative_to(source).as_posix()] = {"sha256": sha(item), "bytes": item.stat().st_size}
    if not files:
        raise ValueError("The selected migration directory contains no files")
    return dict(sorted(files.items()))


def write_new(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")


def remove_empty_directory(path: Path) -> None:
    """Clear only Windows' readonly bit on an approved, already empty source."""
    if policy.linked(path) or not path.is_dir() or any(path.iterdir()):
        raise ValueError("Cleanup requires a verified empty unlinked unsigned source directory")
    try:
        path.rmdir()
    except PermissionError:
        attributes = getattr(path.stat(), "st_file_attributes", 0)
        readonly = getattr(stat, "FILE_ATTRIBUTE_READONLY", 1)
        if os.name != "nt" or not attributes & readonly:
            raise
        # No ACL/owner/host policy changes and no recursive force deletion.
        path.chmod(stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
        path.rmdir()


def migrate(project: Path, source: Path, slug: str, *, remove_source: bool = False,
            exact: bool = False, archive: bool = False) -> dict:
    project = policy.project_root(project)
    original_source = policy.lexical(source)
    for candidate in (original_source, *original_source.parents):
        if policy.linked(candidate):
            raise ValueError("Linked/reparse migration sources require separate review")
    source = original_source.resolve(strict=True)
    before = inventory(source)
    # Preflight source-origin restrictions before creating a destination.
    if source == project or project.is_relative_to(source):
        raise ValueError("Never migrate a project root or ancestor as generated evidence")
    if archive:
        reserved = set()
    else:
        reserved = {policy.MARKER, "migration-manifest.json", "migration-cleanup.json"}
    if reserved & before.keys():
        raise ValueError("Source contains migration/reservation metadata; select a fresh unsigned report set")
    result = policy.initialize(project, slug, exact=exact)
    results = Path(result["results_root"])
    target_root = results / "archive" if archive else results
    if target_root == source or target_root.is_relative_to(source) or source.is_relative_to(target_root):
        raise ValueError("Source and destination must be separate non-overlapping trees")
    if archive:
        target_root.mkdir()
    mapping = {}
    for relative, expected in before.items():
        destination = policy.validate_destination(project, results, target_root / relative, new=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        policy.validate_destination(project, results, destination, new=True)
        original = source / relative
        if sha(original) != expected["sha256"]:
            raise RuntimeError("Migration source changed during copy; original preserved")
        with original.open("rb") as reader, destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
        if sha(destination) != expected["sha256"] or destination.stat().st_size != expected["bytes"]:
            raise RuntimeError("Copied artifact did not match; original preserved")
        mapping[relative] = {**expected, "destination": destination.relative_to(results).as_posix()}
    if inventory(source) != before:
        raise RuntimeError("Migration source inventory changed; no originals removed")
    manifest = {
        "schema": "phy-openfoam-unsigned-migration/1", "copied_utc": now(),
        "source_directory": str(source), "destination_results": str(results),
        "files": mapping, "verified_files": len(mapping),
        "verified_bytes": sum(v["bytes"] for v in mapping.values()),
        "existing_receipts_and_report_bytes_rewritten": False,
        "signed_records_or_keys_moved": False,
        "source_cleanup_authorized": remove_source,
        "policy": "Original paths and renderer hashes remain historical provenance, not claims that the new location was original.",
    }
    write_new(results / "migration-manifest.json", manifest)
    if remove_source:
        # Recheck the whole source and every copied byte immediately before
        # removing only the enumerated originals. New/unlisted files stop cleanup.
        if inventory(source) != before:
            raise RuntimeError("Source changed before cleanup; no original removed")
        for relative, entry in mapping.items():
            destination = policy.validate_destination(project, results, entry["destination"])
            if sha(destination) != entry["sha256"]:
                raise RuntimeError("Destination changed before cleanup; no original removed")
        for relative, entry in mapping.items():
            original = source / relative
            if policy.linked(original) or sha(original) != entry["sha256"]:
                raise RuntimeError("Source changed during cleanup; retain remaining originals and migration manifest")
            original.unlink()
        for base, directories, names in os.walk(source, topdown=False, followlinks=False):
            if names:
                raise RuntimeError("Unexpected source file remains; do not recursively delete it")
            remove_empty_directory(Path(base))
    cleanup = {"checked_utc": now(), "source_removed": remove_source and not source.exists(),
               "source_preserved": not remove_source, "copied_files": len(mapping),
               "signed_records_modified": False, "destination_bytes_verified": True}
    write_new(results / "migration-cleanup.json", cleanup)
    return {"results_dir": str(results), "report": str(target_root / "report.html") if (target_root / "report.html").is_file() else None,
            "migration_manifest": str(results / "migration-manifest.json"), **cleanup}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--exact", action="store_true")
    parser.add_argument("--archive", action="store_true", help="Preserve a legacy tree beneath archive/ instead of root report files")
    parser.add_argument("--remove-source", action="store_true", help="Explicitly remove only hash-verified unsigned source copies after copying")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(migrate(args.project_root, args.source, args.slug,
                                 remove_source=args.remove_source, exact=args.exact, archive=args.archive), indent=2))
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())