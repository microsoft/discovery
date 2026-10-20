"""Focused tests for the agent-removal impact gate."""

import json

import pytest

from pathlib import Path

from check_agent_removal_impact import (
    get_base_registry_paths,
    get_head_registry_paths,
)


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


def _write_base_registry(root: Path, agent_paths: list[str]) -> None:
    registry = {
        "entries": [{"type": "agent", "path": p} for p in agent_paths]
    }
    dest = root / ".auto-registry" / "agent-registry.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(registry), encoding="utf-8")


def test_base_registry_read_from_trusted_root(tmp_path: Path):
    """When a base-registry root is given, agent paths come from the committed
    registry on disk — no git access, which forks often cannot satisfy."""
    trusted = tmp_path / "trusted"
    _write_base_registry(trusted, ["agents/alpha", "agents/beta"])

    paths = get_base_registry_paths(
        tmp_path / "pr", "deadbeef", base_registry_root=trusted
    )
    assert paths == {"agents/alpha", "agents/beta"}


def test_missing_base_registry_is_blocking(tmp_path: Path):
    """A missing base registry must raise, not silently return an empty set that
    would hide every removal."""
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    with pytest.raises(RuntimeError):
        get_base_registry_paths(
            tmp_path / "pr", "deadbeef", base_registry_root=trusted
        )


def test_corrupt_base_registry_is_blocking(tmp_path: Path):
    """A base registry that exists but cannot be parsed must raise."""
    trusted = tmp_path / "trusted"
    dest = trusted / ".auto-registry" / "agent-registry.json"
    dest.parent.mkdir(parents=True)
    dest.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(RuntimeError):
        get_base_registry_paths(
            tmp_path / "pr", "deadbeef", base_registry_root=trusted
        )