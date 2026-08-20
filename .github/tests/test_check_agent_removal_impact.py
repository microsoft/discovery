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


def test_head_registry_paths_tolerate_missing_agents_directory(tmp_path: Path):
    assert get_head_registry_paths(tmp_path) == set()