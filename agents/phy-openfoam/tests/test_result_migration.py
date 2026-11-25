"""Unsigned report cleanup is explicit, byte-preserving and never a native rewrite."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import ModuleType

import pytest

ENTRY = Path(__file__).resolve().parents[1]
SOURCE = ENTRY / "skills/phy-openfoam/scripts/migrate_results.py"
migration = ModuleType("project_results_test_migration")
migration.__file__ = str(SOURCE)
exec(compile(SOURCE.read_text(encoding="utf-8"), str(SOURCE), "exec"), migration.__dict__)


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_report_migration_preserves_exact_bytes_and_historical_receipts(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "agents/contribution/local-evidence/reports/case"
    source.mkdir(parents=True)
    (source / "report.html").write_bytes(b"<!doctype html>\r\n<p>old native result</p>\r\n")
    (source / "report-receipt.json").write_bytes(b'{"original_path":"unchanged/historical/path"}\r\n')
    (source / "evidence-snapshot.json").write_bytes(b'{"scope":"measurement-only"}\n')
    before = files(source)
    result = migration.migrate(project, source, "case", exact=True)
    destination = Path(result["results_dir"])
    assert files(source) == before
    assert all((destination / p).read_bytes() == data for p, data in before.items())
    manifest = json.loads((destination / "migration-manifest.json").read_text(encoding="utf-8"))
    assert manifest["verified_files"] == 3 and not manifest["existing_receipts_and_report_bytes_rewritten"]
    assert not manifest["source_cleanup_authorized"] and result["source_preserved"]
    assert manifest["files"]["report.html"]["sha256"] == migration.sha(source / "report.html")


def test_explicit_cleanup_removes_only_successfully_verified_unsigned_tree(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "agents/source/local-evidence/report"
    source.mkdir(parents=True)
    (source / "report.html").write_bytes(b"original HTML bytes\n")
    result = migration.migrate(project, source, "moved-report", exact=True, remove_source=True)
    assert not source.exists() and result["source_removed"]
    destination = Path(result["results_dir"])
    assert (destination / "report.html").read_bytes() == b"original HTML bytes\n"
    assert (source.parent).is_dir()  # No broad recursive deletion of contribution ancestors.


@pytest.mark.parametrize("name", ["journal.jsonl", "journal.key", "config.json", "secret.pem"])
def test_signed_records_and_runtime_secrets_are_never_migrated(tmp_path, name):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "agents/source/archive"
    source.mkdir(parents=True)
    (source / name).write_bytes(b"do not copy or delete")
    with pytest.raises(ValueError):
        migration.migrate(project, source, "refused", remove_source=True)
    assert (source / name).read_bytes() == b"do not copy or delete"
    assert not list(project.glob("results-refused*"))


def test_unsigned_child_of_signed_record_is_not_a_migration_source(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    signed = tmp_path / "original-native-run"
    source = signed / "output/figures"
    source.mkdir(parents=True)
    (signed / "journal.jsonl").write_bytes(b"original native journal")
    (source / "image.png").write_bytes(b"original native image")
    with pytest.raises(ValueError, match="Signed native"):
        migration.migrate(project, source, "native-child", remove_source=True)
    assert (source / "image.png").exists()


def test_source_changed_during_copy_is_preserved_and_no_cleanup_claimed(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "agents/source/report"
    source.mkdir(parents=True)
    original = source / "report.html"
    original.write_bytes(b"original")
    real_copy = migration.shutil.copyfileobj

    def changed(reader, writer):
        real_copy(reader, writer)
        (source / "new-unlisted.txt").write_bytes(b"concurrent write")

    monkeypatch.setattr(migration.shutil, "copyfileobj", changed)
    with pytest.raises(RuntimeError, match="inventory changed"):
        migration.migrate(project, source, "changed", exact=True, remove_source=True)
    assert original.read_bytes() == b"original" and (source / "new-unlisted.txt").exists()
    assert not (project / "results-changed/migration-cleanup.json").exists()


def test_archive_mode_retains_relative_tree_without_touching_curated_source(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "agents/source/local-evidence"
    (source / "benchmarks/old").mkdir(parents=True)
    (source / "benchmarks/old/bundle.json").write_bytes(b"historical input")
    curated = source.parent / "examples/curated.json"
    curated.parent.mkdir()
    curated.write_bytes(b"reviewed source fixture")
    result = migration.migrate(project, source, "legacy-evidence", exact=True, archive=True, remove_source=True)
    destination = Path(result["results_dir"])
    assert (destination / "archive/benchmarks/old/bundle.json").read_bytes() == b"historical input"
    assert curated.read_bytes() == b"reviewed source fixture"
    assert not source.exists()


def test_empty_directory_cleanup_never_recursively_deletes_unlisted_files(tmp_path):
    folder = tmp_path / "not-empty"
    folder.mkdir()
    (folder / "unlisted.txt").write_bytes(b"preserve")
    with pytest.raises(ValueError, match="verified empty"):
        migration.remove_empty_directory(folder)
    assert (folder / "unlisted.txt").read_bytes() == b"preserve"


def test_readonly_empty_unsigned_directory_cleanup_is_bounded(tmp_path):
    folder = tmp_path / "readonly"
    folder.mkdir()
    if os.name == "nt":
        folder.chmod(stat.S_IREAD | stat.S_IEXEC)
    migration.remove_empty_directory(folder)
    assert not folder.exists()