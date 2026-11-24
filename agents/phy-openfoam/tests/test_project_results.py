"""Explicit project results policy and CLI plumbing; no native solver execution."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from scripts import check_release

ENTRY = Path(__file__).resolve().parents[1]
SOURCE = ENTRY / "skills/phy-openfoam/scripts/project_results.py"
policy = ModuleType("project_results_test_policy")
policy.__file__ = str(SOURCE)
exec(compile(SOURCE.read_text(encoding="utf-8"), str(SOURCE), "exec"), policy.__dict__)


def initialize(tmp_path, slug="screen"):
    project = tmp_path / "user project"
    project.mkdir()
    manifest = policy.initialize(project, slug, exact=True)
    return project.resolve(), Path(manifest["results_root"]), manifest


def test_initializer_uses_explicit_project_not_cwd_or_source(tmp_path, monkeypatch):
    project = tmp_path / "user project"
    project.mkdir()
    monkeypatch.chdir(ENTRY)
    record = policy.initialize(project, "thermal-screen", exact=True)
    results = project / "results-thermal-screen"
    assert Path(record["results_root"]) == results.resolve()
    assert (results / policy.MARKER).is_file()
    assert {p.name for p in results.iterdir()} == {*policy.SUBDIRECTORIES, policy.MARKER}
    assert not results.is_relative_to(ENTRY)
    with pytest.raises(FileExistsError):
        policy.initialize(project, "thermal-screen", exact=True)
    newer = policy.initialize(project, "thermal-screen")
    assert Path(newer["results_root"]) != results


@pytest.mark.parametrize("slug", ["", ".", "../escape", "UPPER", "under_score", "a--b", "a/escape", "a\\escape", "x" * 81])
def test_invalid_slug_cannot_create_output(tmp_path, slug):
    with pytest.raises(ValueError):
        policy.initialize(tmp_path, slug)
    assert not list(tmp_path.iterdir())


def test_initializer_rejects_case_insensitive_agents_and_acquired_entry(tmp_path):
    agents = tmp_path / "AgEnTs/acquired"
    agents.mkdir(parents=True)
    renamed = tmp_path / "renamed-contribution"
    (renamed / "tools/openfoam").mkdir(parents=True)
    (renamed / "agent.yaml").write_text("{}", encoding="utf-8")
    (renamed / "metadata.yaml").write_text("{}", encoding="utf-8")
    for project in (agents, renamed):
        with pytest.raises(ValueError, match="project root"):
            policy.initialize(project, "nope")
        assert not list(project.glob("results-*"))


def test_container_requires_own_manifest_and_unlinked_direct_project_child(tmp_path):
    project, results, record = initialize(tmp_path)
    assert policy.validate_container(project, results) == results
    other = project / "results-other"
    other.mkdir()
    with pytest.raises(ValueError, match="manifest"):
        policy.validate_container(project, other)
    fake = copy.deepcopy(record)
    fake["folder"] = other.name
    fake["project_root"] = str(tmp_path)
    (other / policy.MARKER).write_text(json.dumps(fake), encoding="utf-8")
    with pytest.raises(ValueError, match="does not belong"):
        policy.validate_container(project, other)
    with pytest.raises(ValueError, match="direct child"):
        policy.validate_container(project, results / "results-nested")


@pytest.mark.parametrize("path", ["../escape", "analysis/../../escape", "agents/new", "AgEnTs/new"])
def test_destination_rejects_traversal_and_agents_anywhere(tmp_path, path):
    project, results, _ = initialize(tmp_path)
    with pytest.raises(ValueError):
        policy.validate_destination(project, results, path)
    assert not (results / "agents").exists()


def test_destination_refuses_escape_and_simulated_junction(tmp_path, monkeypatch):
    project, results, _ = initialize(tmp_path)
    with pytest.raises(ValueError):
        policy.validate_destination(project, results, tmp_path / "outside.json")
    junction = results / "analysis/junction"
    junction.mkdir()
    old = policy.linked
    monkeypatch.setattr(policy, "linked", lambda p: p == junction or old(p))
    with pytest.raises(ValueError, match="Symlink/junction"):
        policy.validate_destination(project, results, junction / "escape.json")


def test_native_wrapper_only_scopes_selected_runs_and_preserves_operator_policy(tmp_path, monkeypatch, capsys):
    project, results, _ = initialize(tmp_path)
    data = results / "inputs/case.json"
    data.write_text("{}", encoding="utf-8")
    for name in ("DISCOVERY_PHYSICS_HOME", "DISCOVERY_PHYSICS_CONFIG", "DISCOVERY_PHYSICS_KEY_FILE",
                 "DISCOVERY_PHYSICS_MAX_CONCURRENT", "DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS"):
        monkeypatch.setenv(name, "unchanged-synthetic-value")
    before = os.environ.copy()
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"ok":true}\n', stderr="")

    monkeypatch.setattr(policy, "cli_path", lambda _: "synthetic-installed-cli")
    monkeypatch.setattr(policy.subprocess, "run", fake_run)
    assert policy.run_native(project, results, ["lint", "inputs/case.json"]) == 0
    assert dict(os.environ) == before
    assert calls[0][0] == ["synthetic-installed-cli", "lint", str(data)]
    assert calls[0][1]["cwd"] == results
    assert calls[0][1]["env"]["DISCOVERY_PHYSICS_RUNS"] == str(results / "runs")
    assert all(calls[0][1]["env"][k] == before[k] for k in before if k != "DISCOVERY_PHYSICS_RUNS")
    assert len(list((results / "logs").glob("cli-*.json"))) == 1
    assert '"ok":true' in capsys.readouterr().out


def test_wrapper_routes_explicit_generated_files_and_refuses_overwrite(tmp_path):
    project, results, _ = initialize(tmp_path)
    args = policy.route_arguments(project, results, ["example", "nozzle", "inputs/nozzle.json"])
    assert args[2] == str(results / "inputs/nozzle.json")
    (results / "inputs/nozzle.json").write_text("old", encoding="utf-8")
    with pytest.raises(FileExistsError):
        policy.route_arguments(project, results, ["example", "nozzle", "inputs/nozzle.json"])
    for args in (["export", "identifier", str(project / "agents/export.zip")], ["arbitrary-command"]):
        with pytest.raises(ValueError):
            policy.route_arguments(project, results, args)


def test_native_output_options_cannot_shift_the_unchecked_destination(tmp_path):
    project, results, _ = initialize(tmp_path)
    outside = project / "agents/escape.zip"
    with pytest.raises(ValueError):
        policy.route_arguments(project, results, ["export", "--include-fields", "native-run", str(outside)])
    args = policy.route_arguments(project, results, ["export", "--include-fields", "native-run", "exports/native.zip"])
    assert args[-1] == str(results / "exports/native.zip")
    cad = results / "inputs/source.step"
    cad.write_text("synthetic CAD", encoding="utf-8")
    args = policy.route_arguments(project, results, ["geometry", "--mesh-size", "0.01", str(cad), "inputs/shape.stl"])
    assert args[-1] == str(results / "inputs/shape.stl")
    with pytest.raises(ValueError):
        policy.route_arguments(project, results, ["geometry", "--mesh-size=0.01", str(cad), str(outside)])
    prepared = policy.route_arguments(project, results, ["prepare", "--parent", "native-id", str(cad)])
    assert prepared[-1] == str(cad)


def test_release_guard_flags_generated_output_but_allows_curated_static_inputs(tmp_path):
    root = tmp_path / "source"
    curated = root / "examples/cases/input.json"
    curated.parent.mkdir(parents=True)
    curated.write_text("{}", encoding="utf-8")
    base = check_release.check(root)
    assert not any(f["issue"] == "generated_results_inside_contribution" for f in base["findings"])
    misplaced = root / "results-should-not-be-here"
    misplaced.mkdir()
    (misplaced / policy.MARKER).write_text("{}", encoding="utf-8")
    archive = root / "local-evidence"
    archive.mkdir()
    result = check_release.check(root)
    flagged = [f for f in result["findings"] if f["issue"] == "generated_results_inside_contribution"]
    assert {f["path"] for f in flagged} >= {"results-should-not-be-here", "local-evidence"}