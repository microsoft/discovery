"""Focused tests for starter-kit validation helpers."""

from pathlib import Path

from validate_starter_kits import build_dry_run_registry


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