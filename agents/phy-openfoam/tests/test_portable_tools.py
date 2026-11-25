"""Portable authoring/path tools: synthetic plumbing and lint only, no native solver/CLIO."""

from __future__ import annotations

import ast
import builtins
import json
import re
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from discovery_physics.openfoam import runner
from discovery_physics.openfoam.catalog import BASELINE

from scripts import fixture_probe, heldout, live_paths, result_paths

ENTRY = Path(__file__).resolve().parents[1]
BUILDERS = [
    ("build_bfs_bundle.py", "bfs_bundle.json"),
    ("build_bundle.py", "channel.json"),
    ("build_poiseuille10pa.py", "poiseuille10pa_bundle.json"),
    ("gen_bundle.py", "square_obstacle.json"),
]
SCRIPTS = [
    "clio_driver.py", "heldout.py", "model_comparison.py", "live_paths.py", "fixture_probe.py",
    "result_paths.py", "validation_receipts.py",
]


@pytest.fixture
def routed_project(tmp_path):
    project = tmp_path / "project-\u03bb"
    project.mkdir()
    manifest = result_paths.load_guard(project).initialize(project, "developer-test", exact=True)
    return project.resolve(), Path(manifest["results_root"])


def test_assigned_python_sources_parse_and_no_tool_depends_on_private_source_stores():
    paths = [ENTRY / "scripts" / name for name in SCRIPTS]
    paths += [ENTRY / "examples" / "development" / name for name, _ in BUILDERS]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
    paths += [ENTRY / "examples" / "development" / "build_dns_channel.js",
              live_paths.DEFAULT_BUNDLE]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"[A-Za-z]:[/\\]Users[/\\]|SRC_RUN|local-evidence", source), path
        assert '"agents" / "openfoam"' not in source, path


@pytest.mark.parametrize("ranks", [1, 2])
def test_public_channel_is_self_contained_and_passes_current_health_lint(monkeypatch, ranks):
    monkeypatch.setattr(runner, "runs_root", lambda: pytest.fail("no historical store may be read"))
    data = live_paths.bundle(ranks)
    frozen, info = runner.freeze(data)
    assert info["warnings"] == []
    assert info["estimate"]["cells"] == frozen.diagnostics.expected_cells == 6000
    assert frozen.budget.mpi_ranks == ranks
    assert frozen.budget.cpus >= ranks
    assert {objective.claim for objective in frozen.contract.objectives} == {"numerical_health"}
    assert {check.metric for check in BASELINE} <= {c.metric for c in frozen.contract.checks}
    horizon = next(c for c in frozen.contract.checks if c.metric == "solver.reached_target_time")
    assert horizon.category == "horizon" and horizon.failure == "incomplete"
    mesh = frozen.files["system/blockMeshDict"]
    assert "(0.5 0.01 0.001)" in mesh and "(150 40 1)" in mesh
    assert "uniform (0.01 0 0)" in frozen.files["0/U"]


def test_bundle_override_preserves_contract_and_does_not_edit_input(tmp_path):
    source = tmp_path / "custom bundle.json"
    data = live_paths.bundle(1)
    data["name"] = "custom_health_case"
    source.write_text(json.dumps(data), encoding="utf-8")
    before = source.read_bytes()
    selected = live_paths.bundle(2, source)
    assert selected["name"] == data["name"]
    assert selected["contract"] == data["contract"]
    assert selected["budget"]["mpi_ranks"] == 2
    assert source.read_bytes() == before


def test_bundle_override_accepts_omitted_optional_budget(tmp_path):
    source = tmp_path / "default-budget.json"
    data = live_paths.bundle(1)
    data.pop("budget")
    source.write_text(json.dumps(data), encoding="utf-8")
    selected = live_paths.bundle(2, source)
    assert runner.lint_bundle(selected)["ok"]
    assert selected["budget"]["cpus"] == selected["budget"]["mpi_ranks"] == 2


def test_probe_bundle_uses_all_function_objects_and_current_lint_without_old_stores(monkeypatch):
    monkeypatch.setattr(runner, "runs_root", lambda: pytest.fail("no historical store may be read"))
    data = fixture_probe.probe_bundle()
    assert runner.lint_bundle(data)["ok"]
    assert data["diagnostics"]["target_time"] == 3.0
    assert data["budget"]["max_end_time"] == 3.0
    assert {q["function"] for q in data["diagnostics"]["quantities"]} == {
        "surfaceFieldValue", "forces", "forceCoeffs", "yPlus", "probes", "volFieldValue",
    }
    assert "functions" not in data["files"]["system/controlDict"]


@pytest.mark.parametrize("end_time", [0, -1, float("nan"), float("inf")])
def test_probe_rejects_invalid_horizon_before_preparation(end_time):
    with pytest.raises(ValueError, match="finite and positive"):
        fixture_probe.probe_bundle(end_time=end_time)


def test_fixture_path_cannot_turn_a_physical_contract_into_a_short_health_run(tmp_path):
    data = live_paths.bundle(1)
    data["contract"]["objectives"][0]["claim"] = "physical_validation"
    source = tmp_path / "physical.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="numerical_health-only"):
        fixture_probe.probe_bundle(source)


def test_work_directory_requires_an_explicit_parent(tmp_path):
    with pytest.raises(ValueError, match="explicit work root"):
        live_paths.work_directory("fixtures")
    parent = tmp_path / "explicit temporary plumbing"
    first = live_paths.work_directory("fixtures", parent)
    second = live_paths.work_directory("fixtures", parent)
    assert first.parent == second.parent == parent.resolve()
    assert first != second and first.is_dir() and second.is_dir()
    assert not first.is_relative_to(ENTRY.resolve())


def test_isolated_store_restores_operator_environment_even_on_error(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCOVERY_PHYSICS_RUNS", "original-store")
    monkeypatch.setenv("DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS", "0")
    with pytest.raises(RuntimeError, match="synthetic"):
        with live_paths.run_store(tmp_path / "isolated"):
            assert live_paths.os.environ["DISCOVERY_PHYSICS_RUNS"] == str(tmp_path / "isolated")
            raise RuntimeError("synthetic")
    assert live_paths.os.environ["DISCOVERY_PHYSICS_RUNS"] == "original-store"
    assert live_paths.os.environ["DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS"] == "0"


def test_fixture_generation_uses_guarded_runner_and_keeps_native_receipts(tmp_path, monkeypatch):
    observed = {}
    run_id = "20260101T000000Z-00000000"
    monkeypatch.setenv("DISCOVERY_PHYSICS_RUNS", "original-store")
    monkeypatch.setenv("DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS", "0")

    def fake_prepare(data):
        observed["bundle"] = data
        path = Path(live_paths.os.environ["DISCOVERY_PHYSICS_RUNS"]) / run_id
        observed["path"] = path
        case = path / "output" / "case"
        post = case / "postProcessing" / "q_p_in" / "0"
        post.mkdir(parents=True)
        (post / "surfaceFieldValue.dat").write_text(
            "synthetic extractor fixture\n", encoding="utf-8",
        )
        (case / "log.foamRun.01").write_text("synthetic native-log stand-in\n", encoding="utf-8")
        return {"run_id": run_id}

    def fake_execute(selected):
        observed["executed"] = selected
        assert live_paths.os.environ["DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS"] == "0"
        return {"verdict": "ACCEPT", "not_passing": [],
                "runtime": {"resource_limits": "synthetic enforced-limit receipt"}}

    monkeypatch.setattr(runner, "prepare", fake_prepare)
    monkeypatch.setattr(runner, "execute", fake_execute)
    monkeypatch.setattr(runner, "run_dir", lambda _: observed["path"])
    monkeypatch.setattr(runner, "verify", lambda _: {"ok": True})
    monkeypatch.setattr(runner, "foam", lambda *a, **k: pytest.fail("no unguarded fixture shell"))
    monkeypatch.setattr(
        runner, "finalize", lambda *a, **k: pytest.fail("fixtures are not finalized"),
    )
    receipt = fixture_probe.generate(work_root=tmp_path / "work")
    output = Path(receipt["output"])
    assert observed["executed"] == run_id
    assert (observed["path"] / "output" / "case" / "log.foamRun.01").is_file()
    assert (output / "log.foamRun").read_text(encoding="utf-8") == "synthetic native-log stand-in\n"
    assert (output / "postProcessing" / "q_p_in" / "0" / "surfaceFieldValue.dat").is_file()
    assert receipt["fixture_only"]
    assert not receipt["physical_validation"] and not receipt["finalized"]
    assert live_paths.os.environ["DISCOVERY_PHYSICS_RUNS"] == "original-store"


def test_fixture_runner_refusal_is_not_bypassed(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS", "0")
    monkeypatch.setattr(runner, "prepare", lambda _: {"run_id": "synthetic-run"})

    def refuse(_):
        raise RuntimeError("resource limits cannot be enforced")

    monkeypatch.setattr(runner, "execute", refuse)
    monkeypatch.setattr(runner, "foam", lambda *a, **k: pytest.fail("no fallback is permitted"))
    output = tmp_path / "export"
    with pytest.raises(RuntimeError, match="resource limits cannot be enforced"):
        fixture_probe.generate(output, work_root=tmp_path / "work")
    assert not output.exists()
    assert live_paths.os.environ["DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS"] == "0"


@pytest.mark.parametrize("returncode", [0, 125])
def test_local_service_uses_argument_vector_and_never_retries_without_limits(
    tmp_path, monkeypatch, returncode,
):
    work = tmp_path / "work"
    work.mkdir()
    observed = []
    monkeypatch.setattr(runner, "in_container", lambda: False)
    monkeypatch.setattr(runner, "container_runtime", lambda: "synthetic-runtime")
    monkeypatch.setattr(runner, "image", lambda: "synthetic-image")
    monkeypatch.setenv("DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS", "1")

    def fake_run(command, **kwargs):
        observed.append((command, kwargs))
        if returncode == 0:
            result = {"integrity": {"ok": True},
                      "summary": {"runtime": {"resource_limits": "enforced"}}}
            (work / "output" / "result.json").write_text(json.dumps(result), encoding="utf-8")
        return SimpleNamespace(returncode=returncode,
                               stdout="synthetic stdout", stderr="synthetic stderr")

    monkeypatch.setattr(live_paths.subprocess, "run", fake_run)
    result = live_paths.cloud(live_paths.bundle(1), work)
    assert result["rc"] == returncode and len(observed) == 1
    command, kwargs = observed[0]
    assert command[0] == "synthetic-runtime"
    assert command[command.index("--cpus") + 1] == "2"
    assert command[command.index("--memory") + 1] == "4096m"
    assert command[command.index("--pids-limit") + 1] == "4096"
    assert "discovery_physics.service" in command and "bash" not in command
    assert not kwargs.get("shell", False)
    assert all("ALLOW_UNENFORCED" not in item for item in command)
    assert (work / "stdout.log").read_text(encoding="utf-8") == "synthetic stdout"


def test_path_check_cli_uses_marked_results_and_scoped_store(tmp_path, monkeypatch, routed_project):
    project, results = routed_project
    source = tmp_path / "selected.json"
    data = live_paths.bundle(1)
    data["name"] = "selected_channel"
    source.write_text(json.dumps(data), encoding="utf-8")
    observed = []

    def fake_run(selected):
        assert live_paths.os.environ["DISCOVERY_PHYSICS_RUNS"] == str(results / "runs")
        observed.append(selected)
        return {"p_max": [0.0, "m^2/s^2"], "verify": True, "not_passing": []}

    monkeypatch.setattr(live_paths, "run", fake_run)
    monkeypatch.setenv("DISCOVERY_PHYSICS_RUNS", "original-store")
    assert live_paths.main([
        "mpi", "--project-root", str(project), "--results-dir", str(results),
        "--out", "analysis/receipt.json", "--bundle", str(source),
        "--work-root", str(results / "analysis" / "work"),
    ]) == 0
    assert [b["budget"]["mpi_ranks"] for b in observed] == [1, 2]
    assert all(b["name"] == "selected_channel" for b in observed)
    receipt = results / "analysis" / "receipt.json"
    assert json.loads(receipt.read_text(encoding="utf-8"))["p_max_rel_diff"] == 0.0
    assert live_paths.os.environ["DISCOVERY_PHYSICS_RUNS"] == "original-store"


def test_fixture_cli_forwards_validated_outputs_and_store(tmp_path, monkeypatch, routed_project):
    project, results = routed_project
    source = tmp_path / "selected.json"
    source.write_text("{}", encoding="utf-8")
    observed = {}

    def fake_main(out, **kwargs):
        observed.update(out=out, **kwargs)
        return 0

    monkeypatch.setattr(fixture_probe, "main", fake_main)
    assert fixture_probe.cli([
        "--project-root", str(project), "--results-dir", str(results),
        "--out", "exports/fixture", "--bundle", str(source),
        "--work-root", "analysis/work", "--end-time", "2.5",
    ]) == 0
    assert observed == {"out": results / "exports" / "fixture", "source": source.resolve(),
                        "work_root": results / "analysis" / "work", "end_time": 2.5,
                        "runs_root": results / "runs"}


def test_harness_data_home_also_works_without_the_package(tmp_path, monkeypatch):
    original_import = builtins.__import__

    def without_package(name, *args, **kwargs):
        if name == "discovery_physics.core.config":
            raise ModuleNotFoundError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_package)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert heldout.data_home() == tmp_path / "DiscoveryPhysics"


@pytest.mark.parametrize("name,default", BUILDERS)
@pytest.mark.parametrize("mode", ["positional", "option", "missing", "conflict"])
def test_python_builders_only_write_selected_portable_output(
    tmp_path, monkeypatch, name, default, mode,
):
    monkeypatch.chdir(tmp_path)
    module = runpy.run_path(
        str(ENTRY / "examples" / "development" / name), run_name="portable_builder",
    )
    assert not list(tmp_path.iterdir()), "importing a builder must not write a bundle"
    manifest = result_paths.load_guard(tmp_path).initialize(tmp_path, "builder", exact=True)
    results = Path(manifest["results_root"])
    target = results / "inputs" / "nested dir" / "bundle-\u00e9.json"
    routing = ["--project-root", str(tmp_path.resolve()), "--results-dir", str(results)]
    if mode == "positional":
        args = [*routing, str(target)]
    elif mode == "option":
        args = [*routing, "--output", str(target)]
    elif mode == "conflict":
        args = [*routing, str(target), "--output", str(target)]
    else:
        args = routing
    if mode != "option":
        with pytest.raises(SystemExit) as exc:
            module["main"](args)
        assert exc.value.code == 2 and not target.exists()
        assert not (tmp_path / default).exists(), "missing --output must never create a CWD default"
        return
    assert module["main"](args) == 0
    assert json.loads(target.read_text(encoding="utf-8")) == module["bundle"]
    before = target.read_bytes()
    with pytest.raises(SystemExit) as exc:
        module["main"](args)
    assert exc.value.code == 2 and target.read_bytes() == before
    assert {path.resolve() for path in tmp_path.rglob("*.json")} == {
        results / "results-manifest.json", target,
    }


@pytest.mark.parametrize("mode", ["positional", "option", "missing", "conflict"])
def test_js_builder_writes_portable_output_and_retains_confirmation_gate(
    tmp_path, routed_project, mode,
):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed; no installation is attempted")
    project, results = routed_project
    target = results / "inputs" / "nested dir" / "bundle-\u00e9.json"
    args = ([str(target)] if mode == "positional" else ["--output", str(target)] if mode == "option"
            else [str(target), "--output", str(target)] if mode == "conflict" else [])
    command = [node, str(ENTRY / "examples" / "development" / "build_dns_channel.js"),
               "--project-root", str(project), "--results-dir", str(results),
               "--python", sys.executable, *args]
    result = subprocess.run(
        command,
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    if mode != "option":
        assert result.returncode != 0 and not target.exists()
        assert not (tmp_path / "dns_channel_retau180.json").exists()
        return
    assert result.returncode == 0, result.stderr
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["diagnostics"]["expected_cells"] == 36864
    gate = next(a for a in data["contract"]["assumptions"]
                if a["parameter"] == "method_substitution")
    assert gate["source"] == "needs_confirmation"
    assert data["contract"]["authority"] == "proposed"
    before = target.read_bytes()
    repeated = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True,
                              encoding="utf-8", timeout=30, check=False)
    assert repeated.returncode != 0 and target.read_bytes() == before
    assert {path.resolve() for path in tmp_path.rglob("*.json")} == {
        results / "results-manifest.json", target,
    }