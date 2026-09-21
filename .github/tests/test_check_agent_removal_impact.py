"""Focused tests for the agent-removal impact gate."""

from pathlib import Path

from check_agent_removal_impact import get_head_registry_paths


def test_head_registry_paths_come_from_agent_metadata(tmp_path: Path):
    (tmp_path / "agents" / "kept").mkdir(parents=True)
    (tmp_path / "agents" / "kept" / "metadata.yaml").write_text(
        "name: kept\n",
        encoding="utf-8",
    )
    (tmp_path / "agents" / "incomplete").mkdir()
    (tmp_path / "agents" / "README.md").write_text("Agents\n", encoding="utf-8")

    assert get_head_registry_paths(tmp_path) == {"agents/kept"}


def test_malformed_metadata_is_treated_as_absent(tmp_path: Path):
    # A folder whose metadata would be rejected by registry generation (no
    # name) must not be counted as present, so it cannot mask a real removal.
    (tmp_path / "agents" / "nameless").mkdir(parents=True)
    (tmp_path / "agents" / "nameless" / "metadata.yaml").write_text(
        "description: no name here\n",
        encoding="utf-8",
    )
    (tmp_path / "agents" / "broken").mkdir()
    (tmp_path / "agents" / "broken" / "metadata.yaml").write_text(
        "name: [unterminated\n",
        encoding="utf-8",
    )

    assert get_head_registry_paths(tmp_path) == set()


def test_head_registry_paths_tolerate_missing_agents_directory(tmp_path: Path):
    assert get_head_registry_paths(tmp_path) == set()