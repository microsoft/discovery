"""Developer CLI routing only: temporary paths and stubs, never native CFD/CLIO."""

from __future__ import annotations

import ast
import json
import os
import runpy
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from discovery_physics.benchmarks import comparison, output_paths, report, study_s8
from discovery_physics.benchmarks import run as campaign_run

from scripts import (
    clio_driver,
    fixture_probe,
    heldout,
    live_paths,
    model_comparison,
    result_paths,
    validation_receipts,
)

ENTRY = Path(__file__).resolve().parents[1]
BUILDERS = ("build_bundle.py", "build_bfs_bundle.py", "build_poiseuille10pa.py", "gen_bundle.py")
WRITERS = ("run", "comparison", "report", "study", "paths", "fixture", "clio", "heldout",
           "models", "receipts")


@pytest.fixture
def routed(tmp_path):
    project = tmp_path / "project-\u00e9"
    project.mkdir()
    manifest = result_paths.load_guard(project).initialize(project, "developer", exact=True)
    results = Path(manifest["results_root"])
    return project.resolve(), results, result_paths.ResultPaths(project, results)


def _arguments(project, results):
    return ["--project-root", str(project), "--results-dir", str(results)]


def _invoke(writer, arguments):
    # Missing inputs are intentional: rejection of an invalid destination must
    # precede tutorial discovery, native-store reads, solves or model calls.
    if writer == "run":
        return campaign_run.main(arguments)
    if writer == "comparison":
        return comparison.main([*arguments, "--results", "absent-input"])
    if writer == "report":
        return report.main([*arguments, "--results", "absent-input"])
    if writer == "study":
        return study_s8.main(arguments)
    if writer == "paths":
        return live_paths.main(["mpi", *arguments])
    if writer == "fixture":
        return fixture_probe.cli(arguments)
    if writer == "clio":
        return clio_driver.main(["run", "absent-prompt", *arguments, "--cwd", arguments[1]])
    if writer == "heldout":
        return heldout.main(["run", *arguments])
    if writer == "models":
        return model_comparison.main(["run", *arguments, "--packets", "absent-input"])
    return validation_receipts.main([*arguments, "--results", "absent-input"])


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("destination", ["missing", "outside", "source", "existing", "traversal"])
def test_cli_refuses_bad_destinations_before_any_computation(
    tmp_path, monkeypatch, routed, writer, destination,
):
    project, results, _ = routed

    def forbidden(*args, **kwargs):
        pytest.fail("No native operation, model call or evidence read may precede routing refusal")

    for name in ("tutorial", "prepare", "execute", "verified", "run_dir", "container_runtime"):
        monkeypatch.setattr(campaign_run.runner, name, forbidden)
    monkeypatch.setattr(study_s8.study, "prepare", forbidden)
    monkeypatch.setattr(clio_driver, "run", forbidden)
    monkeypatch.setattr(heldout, "require_skill", forbidden)
    monkeypatch.setattr(heldout, "run_one", forbidden)
    monkeypatch.setattr(model_comparison, "run_comparison", forbidden)
    monkeypatch.setattr(comparison, "build_points", forbidden)
    monkeypatch.setattr(validation_receipts, "campaign", forbidden)
    monkeypatch.setattr(live_paths, "run", forbidden)
    monkeypatch.setattr(fixture_probe, "main", forbidden)
    arguments = _arguments(project, results)
    existing = results / "analysis" / "existing.json"
    existing.write_text("original\n", encoding="utf-8")
    selected = {
        "outside": tmp_path / "outside.json",
        "source": project / "agents" / "acquired" / "new.json",
        "existing": existing,
        "traversal": results / "analysis" / ".." / "escape.json",
    }.get(destination)
    if selected is not None:
        arguments += ["--out", str(selected)]
    with pytest.raises(SystemExit) as exc:
        _invoke(writer, arguments)
    assert exc.value.code == 2
    assert existing.read_text(encoding="utf-8") == "original\n"
    assert not (tmp_path / "outside.json").exists()
    assert not (project / "agents").exists()


@pytest.mark.parametrize("writer", WRITERS)
def test_cli_requires_explicit_project_and_marked_results_before_native_work(routed, writer):
    project, results, _ = routed
    with pytest.raises(SystemExit) as exc:
        _invoke(writer, ["--project-root", str(project), "--out", str(results / "new.json")])
    assert exc.value.code == 2


def test_source_loader_uses_canonical_guard_and_writes_only_exclusive_results(routed):
    project, results, paths = routed
    expected = ENTRY / "skills" / "phy-openfoam" / "scripts" / "project_results.py"
    assert Path(paths.guard.__file__).resolve() == expected.resolve()
    destination = paths.write_text("inputs/nested dir/bundle-\u03bb.json", '{"synthetic": true}\n')
    assert destination == results / "inputs" / "nested dir" / "bundle-\u03bb.json"
    with pytest.raises(FileExistsError):
        paths.write_text(destination, "overwrite")
    assert destination.read_text(encoding="utf-8") == '{"synthetic": true}\n'
    assert paths.project == project


@pytest.mark.parametrize("kind", ["relative", "missing", "agents", "acquired"])
def test_project_identity_is_absolute_existing_and_not_source(tmp_path, kind):
    root = tmp_path / "project"
    root.mkdir()
    guard = result_paths.load_guard(root)
    if kind == "relative":
        project = Path("relative-project")
    elif kind == "missing":
        project = root / "absent"
    elif kind == "agents":
        project = root / "Agents" / "acquired"
        project.mkdir(parents=True)
    else:
        project = root / "renamed-contribution"
        (project / "tools/openfoam").mkdir(parents=True)
        (project / "agent.yaml").write_text("{}", encoding="utf-8")
        (project / "metadata.yaml").write_text("{}", encoding="utf-8")
    with pytest.raises((OSError, ValueError)):
        guard.initialize(project, "test", exact=True)
    assert not list(root.rglob("results-test"))


@pytest.mark.parametrize("kind", [
    "unmarked", "wrong-project", "wrong-folder", "nested", "linked-marker",
])
def test_container_guard_is_required_and_no_fallback_is_created(tmp_path, routed, kind, monkeypatch):
    project, results, paths = routed
    marker = results / "results-manifest.json"
    selected = results
    if kind == "unmarked":
        marker.unlink()
    elif kind in {"wrong-project", "wrong-folder"}:
        record = json.loads(marker.read_text(encoding="utf-8"))
        record["project_root" if kind == "wrong-project" else "folder"] = str(tmp_path)
        marker.write_text(json.dumps(record), encoding="utf-8")
    elif kind == "nested":
        selected = results / "results-nested"
        selected.mkdir()
    else:
        linked = paths.guard.linked
        monkeypatch.setattr(paths.guard, "linked", lambda value: value == marker or linked(value))
        with pytest.raises(ValueError):
            paths.guard.validate_container(project, results)
        return
    with pytest.raises((OSError, ValueError)):
        result_paths.ResultPaths(project, selected)


@pytest.mark.parametrize("value", ["../escape", "analysis/../../escape", "agents/new.json",
                                   "runs/new.json", "studies/new.json", "RUNS/new.json"])
def test_destination_guard_rejects_traversal_source_and_native_stores(routed, value):
    _, _, paths = routed
    with pytest.raises((OSError, ValueError)):
        paths.output(value)


def test_signed_records_and_nested_native_stores_are_not_output_targets(routed):
    _, results, paths = routed
    record = results / "analysis" / "signed"
    record.mkdir()
    (record / "journal.jsonl").write_text("synthetic signed marker\n", encoding="utf-8")
    with pytest.raises(ValueError, match="signed native record"):
        paths.output(record / "derivative.json")
    native = results / "runs" / "synthetic-record"
    native.mkdir()
    (native / "journal.jsonl").write_text("synthetic signed marker\n", encoding="utf-8")
    with pytest.raises(ValueError, match="signed native record"):
        paths.run_root(native / "nested-runs")


def test_existing_symlink_escape_is_refused_when_supported(tmp_path, routed):
    _, results, paths = routed
    outside = tmp_path / "outside"
    outside.mkdir()
    link = results / "analysis" / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Host does not permit symlink creation; reparse-point control is tested separately")
    with pytest.raises(ValueError):
        paths.output(link / "escaped.json")
    assert not list(outside.iterdir())


def test_windows_junction_reparse_bit_is_refused_without_creating_a_junction(routed, monkeypatch):
    _, results, paths = routed
    junction = results / "analysis" / "junction"
    junction.mkdir()
    original = Path.lstat

    def attributes(path, *args, **kwargs):
        if path == junction:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR,
                st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
            )
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", attributes)
    with pytest.raises(ValueError, match="Symlink/junction/reparse"):
        paths.output(junction / "new.json")


def test_installed_benchmark_loads_selected_project_skill_or_fails_closed(routed, monkeypatch):
    project, results, paths = routed
    canonical = Path(paths.guard.__file__)
    monkeypatch.setattr(output_paths, "_source_guard", lambda: None)
    with pytest.raises(FileNotFoundError, match="complete phy-openfoam skill"):
        output_paths.ResultPaths(project, results)
    installed = project / ".github/skills/phy-openfoam/scripts/project_results.py"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(canonical.read_bytes())
    before = installed.read_bytes()
    selected = output_paths.ResultPaths(project, results)
    assert Path(selected.guard.__file__) == installed
    assert selected.output("analysis/new.json") == results / "analysis" / "new.json"
    assert installed.read_bytes() == before and not (installed.parent / "__pycache__").exists()


@pytest.mark.parametrize("previous", [None, "operator-run-store"])
def test_native_store_only_scopes_runs_and_restores_environment_on_failure(routed, monkeypatch, previous):
    _, results, paths = routed
    if previous is None:
        monkeypatch.delenv("DISCOVERY_PHYSICS_RUNS", raising=False)
    else:
        monkeypatch.setenv("DISCOVERY_PHYSICS_RUNS", previous)
    for key in ("DISCOVERY_PHYSICS_HOME", "DISCOVERY_PHYSICS_KEY_FILE",
                "DISCOVERY_PHYSICS_CONFIG", "DISCOVERY_PHYSICS_MAX_CONCURRENT",
                "DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS", "HOME"):
        monkeypatch.setenv(key, "synthetic-unchanged")
    before = os.environ.copy()
    with pytest.raises(RuntimeError, match="synthetic"):
        with paths.native_store():
            assert os.environ == {**before, "DISCOVERY_PHYSICS_RUNS": str(results / "runs")}
            raise RuntimeError("synthetic")
    assert dict(os.environ) == before
    child = paths.child_env()
    assert child == {**before, "DISCOVERY_PHYSICS_RUNS": str(results / "runs")}
    assert dict(os.environ) == before


@pytest.mark.parametrize("writer", ["run", "study"])
def test_benchmark_native_calls_use_results_store_and_restore_it_on_error(routed, monkeypatch, writer):
    project, results, _ = routed
    monkeypatch.setenv("DISCOVERY_PHYSICS_RUNS", "operator-store")
    observed = []

    def tutorial(_):
        observed.append(os.environ["DISCOVERY_PHYSICS_RUNS"])
        raise RuntimeError("synthetic tutorial refusal; no solver")

    monkeypatch.setattr(campaign_run.runner, "tutorial", tutorial)
    with pytest.raises(RuntimeError, match="synthetic tutorial refusal"):
        _invoke(writer, [*_arguments(project, results), "--out", "analysis/new-benchmark"])
    assert observed == [str(results / "runs")]
    assert os.environ["DISCOVERY_PHYSICS_RUNS"] == "operator-store"


def test_report_cli_reads_explicit_inputs_and_never_uses_cwd_defaults(tmp_path, routed, monkeypatch):
    project, results, _ = routed
    source = tmp_path / "historical-input"
    source.mkdir()
    comp = tmp_path / "historical-comparison.json"
    comp.write_text(json.dumps({"synthetic": {"points": 1, "correct": 1, "false_accept": 0}}),
                    encoding="utf-8")
    monkeypatch.chdir(ENTRY)
    output = results / "exports" / "benchmark.md"
    assert report.main([*_arguments(project, results), "--results", str(source),
                        "--comparison", str(comp), "--out", str(output)]) == 0
    assert "synthetic" in output.read_text(encoding="utf-8")
    before = output.read_bytes()
    with pytest.raises(SystemExit) as exc:
        report.main([*_arguments(project, results), "--results", str(source), "--out", str(output)])
    assert exc.value.code == 2 and output.read_bytes() == before
    assert not list(source.iterdir())


def test_model_cli_forwards_routed_work_and_child_environment(routed, monkeypatch):
    project, results, _ = routed
    packets = project / "packets"
    packets.mkdir()
    observed = {}

    def run(packets, published, **kwargs):
        observed.update(packets=packets, published=published, **kwargs)
        return {"synthetic": True}

    monkeypatch.setattr(model_comparison, "run_comparison", run)
    monkeypatch.setenv("DISCOVERY_PHYSICS_RUNS", "operator-store")
    assert model_comparison.main([
        "run", *_arguments(project, results), "--packets", str(packets),
        "--out", "analysis/review",
    ]) == 0
    assert observed["published"] == results / "analysis" / "review"
    assert observed["work_root"] == results / "analysis" / "review" / "work"
    assert observed["env"]["DISCOVERY_PHYSICS_RUNS"] == str(results / "runs")
    assert os.environ["DISCOVERY_PHYSICS_RUNS"] == "operator-store"


def test_comparison_recollection_creates_new_derivative_and_preserves_old_files(routed, monkeypatch):
    _, results, _ = routed
    source = results / "analysis" / "original"
    (source / "inputs").mkdir(parents=True)
    (source / "objectives").mkdir()
    protocol = {"batch_order": ["B01"]}
    (source / "protocol.json").write_text(json.dumps(protocol), encoding="utf-8")
    (source / "inputs" / "B01.json").write_text(json.dumps({"batch": "B01"}), encoding="utf-8")
    (source / "objectives" / "B01.txt").write_text("original objective", encoding="utf-8")
    (source / "failure.json").write_text("retained original failure", encoding="utf-8")
    before = {path.relative_to(source): path.read_bytes() for path in source.rglob("*")
              if path.is_file()}
    monkeypatch.setattr(model_comparison, "collect_batch", lambda batch, *args: batch)
    monkeypatch.setattr(model_comparison, "score_reviews", lambda *args: {"synthetic": True})
    derivative = results / "analysis" / "recollected"
    assert model_comparison.collect_comparison(source, derivative, source, source=source) == {
        "synthetic": True,
    }
    assert {path.relative_to(source): path.read_bytes() for path in source.rglob("*")
            if path.is_file()} == before
    assert (derivative / "protocol.json").read_bytes() == before[Path("protocol.json")]
    with pytest.raises(FileExistsError):
        model_comparison.collect_comparison(source, derivative, source, source=source)


@pytest.mark.parametrize("name", BUILDERS)
def test_builders_refuse_unmarked_or_source_output_without_writing(tmp_path, routed, name):
    project, results, _ = routed
    module = runpy.run_path(str(ENTRY / "examples/development" / name), run_name="builder_test")
    for output in (project / "outside.json", results / "agents" / "new.json"):
        with pytest.raises(SystemExit) as exc:
            module["main"]([*_arguments(project, results), "--output", str(output)])
        assert exc.value.code == 2 and not output.exists()
    with pytest.raises(SystemExit) as exc:
        module["main"](["--output", str(tmp_path / "cwd-default.json")])
    assert exc.value.code == 2 and not (tmp_path / "cwd-default.json").exists()


def test_node_builder_uses_same_guard_for_escape_and_collision_refusal(tmp_path, routed):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed; no installation is attempted")
    project, results, _ = routed
    script = ENTRY / "examples/development/build_dns_channel.js"
    for output in (tmp_path / "outside.json", results / "analysis" / ".." / "escape.json",
                   results / "agents" / "new.json"):
        proc = subprocess.run([node, str(script), *_arguments(project, results),
                               "--python", sys.executable, "--output", str(output)],
                              capture_output=True, text=True, encoding="utf-8", timeout=30,
                              check=False)
        assert proc.returncode != 0 and not output.exists()


def test_developer_python_sources_parse_after_routing_changes():
    paths = [ENTRY / "scripts" / name for name in (
        "result_paths.py", "live_paths.py", "fixture_probe.py", "clio_driver.py",
        "heldout.py", "model_comparison.py", "validation_receipts.py",
    )]
    paths += [ENTRY / "examples/development" / name for name in BUILDERS]
    paths += list((ENTRY / "tools/openfoam/src/discovery_physics/benchmarks").glob("*.py"))
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))