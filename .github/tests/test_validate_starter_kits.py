"""Focused tests for starter-kit validation helpers."""

from pathlib import Path

from validate_starter_kits import build_dry_run_registry, validate_kit


def _validate_extra_files(tmp_path: Path, filenames: list[str]) -> list[str]:
    kit_dir = tmp_path / "starter-kits" / "demo"
    kit_dir.mkdir(parents=True, exist_ok=True)
    for filename in filenames:
        path = kit_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"content")
    errors: list[str] = []
    validate_kit(
        kit_dir,
        "demo",
        {"name": "demo", "lifecycle": "archived", "agentRefs": []},
        {},
        None,  # type: ignore[arg-type]
        set(),
        set(),
        errors,
        [],
    )
    return errors


def test_dry_run_registry_uses_valid_agent_metadata(tmp_path: Path):
    valid = tmp_path / "agents" / "valid"
    valid.mkdir(parents=True)
    (valid / "metadata.yaml").write_text(
        "name: valid\nversion: 1.2.3\n",
        encoding="utf-8",
    )

    unnamed = tmp_path / "agents" / "unnamed"
    unnamed.mkdir()
    (unnamed / "metadata.yaml").write_text("version: 1.2.3\n", encoding="utf-8")

    assert build_dry_run_registry(tmp_path) == {"agents/valid"}


def test_starter_kit_allows_markdown_and_web_images(tmp_path: Path):
    kit_dir = tmp_path / "starter-kits" / "demo"
    kit_dir.mkdir(parents=True)
    (kit_dir / "README.md").write_text(
        "![Diagram](media/diagram.png)\n", encoding="utf-8"
    )
    (kit_dir / "media").mkdir()
    (kit_dir / "media" / "diagram.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 20
        + b"IEND\xaeB`\x82"
    )
    errors = _validate_extra_files(tmp_path, ["kit.json"])
    assert not any("SKT-STR-008" in error for error in errors)
    assert not any("SKT-AST-002" in error for error in errors)


def test_starter_kit_rejects_arbitrary_extra_files(tmp_path: Path):
    errors = _validate_extra_files(tmp_path, ["kit.json", "payload.py"])
    assert any("SKT-STR-008" in error and "payload.py" in error for error in errors)


def test_starter_kit_rejects_orphaned_image(tmp_path: Path):
    kit_dir = tmp_path / "starter-kits" / "demo"
    kit_dir.mkdir(parents=True)
    (kit_dir / "diagram.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 20
        + b"IEND\xaeB`\x82"
    )
    errors = _validate_extra_files(tmp_path, ["kit.json"])
    assert any("SKT-AST-002" in error and "not embedded" in error for error in errors)