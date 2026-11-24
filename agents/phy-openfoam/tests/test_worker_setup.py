"""Synthetic setup/solve stand-ins audit initial fields without executing OpenFOAM."""

from __future__ import annotations

import json
import re
import sys
from types import SimpleNamespace

import pytest

from discovery_physics import worker
from discovery_physics.benchmarks.cases import forward_step_bundle
from discovery_physics.core import integrity
from discovery_physics.core.hashing import sha256_json
from discovery_physics.openfoam import runner
from discovery_physics.openfoam.extract import Metrics

from test_core import TUT, healthy_metrics


@pytest.fixture
def staged_worker(tmp_path, monkeypatch):
    for name, suffix in (("DISCOVERY_PHYSICS_RUNS", "runs"), ("DISCOVERY_PHYSICS_HOME", "home"),
                         ("DISCOVERY_PHYSICS_KEY_FILE", "keys/journal.key"), ("LOCALAPPDATA", "app")):
        monkeypatch.setenv(name, str(tmp_path / suffix))
    monkeypatch.delenv("DISCOVERY_PHYSICS_IN_CONTAINER", raising=False)
    monkeypatch.setitem(sys.modules, "discovery_physics.openfoam.figures", SimpleNamespace(render=lambda *a: []))

    def stage(*, ranks=1, mesh=None, reference=False):
        bundle = forward_step_bundle(TUT)
        bundle["mesh"] = mesh or [{"executable": "blockMesh"}, {"executable": "setFields"}]
        bundle["files"]["system/setFieldsDict"] = "defaultFieldValues (volScalarFieldValue T 301);\nregions ();\n"
        bundle["budget"]["mpi_ranks"] = ranks
        bundle["budget"]["cpus"] = max(bundle["budget"]["cpus"], ranks)
        if reference:
            from discovery_physics.core.hashing import sha256_text

            bundle["diagnostics"]["reference_hashes"] = {"0/T": sha256_text(bundle["files"]["0/T"])}
        state = SimpleNamespace(rid=runner.prepare(bundle)["run_id"], commands=[], hook=None,
                                incomplete=False, raw=None, set_fields_calls=0, return_codes={})

        def fake_run(argv, case, log, timeout):
            state.commands.append(list(argv))
            log.write_text("Synthetic command stand-in; no native solver.\n", encoding="utf-8")
            if argv[0] == "blockMesh":
                geometry = case / "constant/polyMesh/points"
                geometry.parent.mkdir(parents=True, exist_ok=True)
                geometry.write_text("synthetic generated mesh\n", encoding="utf-8")
            elif argv[0] == "setFields":
                state.set_fields_calls += 1
                field = case / "0/T"
                text = field.read_text(encoding="utf-8")
                changed, count = re.subn(r"internalField\s+uniform\s+[^;]+;",
                                        f"internalField uniform {300 + state.set_fields_calls};", text, count=1)
                assert count == 1 and changed != text
                field.write_text(changed, encoding="utf-8")
            if state.hook:
                state.hook(argv, case)
            return state.return_codes.get(argv[0], 0)

        def fake_extract(case, diagnostics, exit_code, end_time, mesh_ok):
            values = healthy_metrics(runner.verified(state.rid)["bundle"].contract)
            values["solver.exit_code"] = {"value": exit_code, "unit": "1", "source": "synthetic command result"}
            values["solver.final_time"] = {"value": 2.0 if state.incomplete else 4.0,
                                           "unit": "1", "source": "synthetic checkpoint time"}
            values["solver.reached_target_time"]["value"] = not state.incomplete
            values["mesh.stage_clean"]["value"] = mesh_ok
            result = Metrics()
            for name, metric in values.items():
                result.put(name, metric["value"], metric["unit"], metric["source"])
            return result

        def execute():
            path = runner.run_dir(state.rid)
            plan = runner.verified(state.rid)["plan"]
            output = path / "output"
            output.mkdir()
            integrity.append(path, "execution_started", executor="synthetic", runtime="fixture", image="fixture")
            assert worker.main([str(path / "input"), str(output)]) == 0
            state.raw = json.loads((output / "evidence.json").read_text(encoding="utf-8"))
            return runner._assess_run(path, plan, 0, 1.0, "sha256:synthetic", "synthetic fixture")

        monkeypatch.setattr(worker, "_run", fake_run)
        monkeypatch.setattr(worker, "extract", fake_extract)
        state.execute = execute
        return state

    return stage


@pytest.mark.parametrize("ranks", [1, 2])
def test_worker_tracks_setfields_rewrite_without_weakening_original_input_hash(staged_worker, ranks):
    state = staged_worker(ranks=ranks)
    path = runner.run_dir(state.rid)
    plan = runner.verified(state.rid)["plan"]
    original = (path / "input/case/0/T").read_bytes()
    assert state.execute()["verdict"] == "ACCEPT"
    assert state.raw["metrics"]["setup.case_hash_matches"]["value"] is True
    assert (path / "input/case/0/T").read_bytes() == original
    assert (path / "output/case/0/T").read_bytes() != original
    assert worker.frozen_sha256(path / "input/case") == plan["frozen_sha256"]
    assert worker.frozen_sha256(path / "output/case") != plan["frozen_sha256"]
    audit = state.raw["runtime"]["setup_audit"]
    assert audit["input_frozen_sha256"] == audit["expected_input_frozen_sha256"] == plan["frozen_sha256"]
    assert audit["post_setup_frozen_sha256"] == audit["final_frozen_sha256"]
    step = next(s for s in audit["steps"] if s["command"]["executable"] == "setFields")
    assert step["permitted"] and set(step["changed_files"]) == {"0/T"}
    assert step["changed_files"]["0/T"]["before_sha256"] != step["changed_files"]["0/T"]["after_sha256"]
    assert runner.verify(state.rid)["ok"]


@pytest.mark.parametrize("bad_path", ["system/fvSchemes", "constant/physicalProperties", "0/include/value", "0/p"])
def test_setfields_does_not_authorize_dictionary_include_or_deletion_changes(staged_worker, bad_path):
    state = staged_worker()

    def mutate(argv, case):
        if argv[0] == "setFields":
            target = case / bad_path
            if bad_path == "0/p":
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("unauthorized setup change\n", encoding="utf-8")

    state.hook = mutate
    assert state.execute()["verdict"] != "ACCEPT"
    assert state.raw["metrics"]["setup.case_hash_matches"]["value"] is False
    assert not any("foamRun" in args for args in state.commands)


@pytest.mark.parametrize("command", ["blockMesh", "checkMesh", "foamRun", "foamPostProcess"])
def test_other_commands_cannot_rewrite_initial_fields(staged_worker, command):
    state = staged_worker()

    def mutate(argv, case):
        if argv[0] == command:
            target = case / "0/U"
            target.write_text(target.read_text(encoding="utf-8") + "\n// unauthorized rewrite\n", encoding="utf-8")

    state.hook = mutate
    assert state.execute()["verdict"] != "ACCEPT"
    assert state.raw["metrics"]["setup.case_hash_matches"]["value"] is False


def test_bad_input_copy_is_not_rebaselined_by_later_setfields(staged_worker, monkeypatch):
    state = staged_worker()
    copy = worker.shutil.copyfile

    def corrupt(src, dst):
        result = copy(src, dst)
        if dst.name == "T" and dst.parent.name == "0":
            dst.write_text(dst.read_text(encoding="utf-8") + "\n// corrupt input copy\n", encoding="utf-8")
        return result

    monkeypatch.setattr(worker.shutil, "copyfile", corrupt)
    assert state.execute()["verdict"] != "ACCEPT"
    assert state.raw["metrics"]["setup.case_hash_matches"]["value"] is False


def test_failed_setfields_is_not_an_authorized_rewrite(staged_worker):
    state = staged_worker()
    state.return_codes["setFields"] = 1
    assert state.execute()["verdict"] != "ACCEPT"
    assert state.raw["metrics"]["setup.case_hash_matches"]["value"] is False


def test_multiple_setfields_steps_keep_a_hash_chain(staged_worker):
    state = staged_worker(mesh=[{"executable": "blockMesh"}, {"executable": "setFields"}, {"executable": "setFields"}])
    assert state.execute()["verdict"] == "ACCEPT"
    steps = [step for step in state.raw["runtime"]["setup_audit"]["steps"]
             if step["command"]["executable"] == "setFields"]
    assert len(steps) == 2
    assert steps[0]["changed_files"]["0/T"]["after_sha256"] == steps[1]["changed_files"]["0/T"]["before_sha256"]


def test_reference_hashes_are_not_exempted_for_generated_fields(staged_worker):
    state = staged_worker(reference=True)
    assert state.execute()["verdict"] != "ACCEPT"
    assert state.raw["metrics"]["setup.case_hash_matches"]["value"] is True
    assert state.raw["metrics"]["setup.reference_files_match"]["value"] is False


@pytest.mark.parametrize("ranks", [1, 2])
def test_continuation_uses_verified_post_setup_hash_without_repeating_initialization(staged_worker, ranks):
    state = staged_worker(ranks=ranks)
    state.incomplete = True
    assert state.execute()["verdict"] == "CORRECT_AND_RERUN"
    parent = state.rid
    post_setup = state.raw["runtime"]["setup_audit"]["post_setup_frozen_sha256"]
    approved = runner.propose(parent, {"action": "CONTINUE_RUN", "end_time": 4.0,
                                      "rationale": "Synthetic healthy incomplete member needs its frozen horizon."})
    assert approved["approved"]
    state.rid = approved["child_run_id"]
    plan = runner.verified(state.rid)["plan"]
    assert plan["restart_frozen_sha256"] == post_setup
    assert plan["frozen_sha256"] == runner.verified(parent)["plan"]["frozen_sha256"]
    state.commands.clear()
    state.incomplete = False
    assert state.execute()["verdict"] == "ACCEPT"
    assert not any(args[0] == "setFields" for args in state.commands)
    assert state.raw["runtime"]["setup_audit"]["input_frozen_sha256"] == post_setup
    assert runner.verify(parent)["ok"] and runner.verify(state.rid)["ok"]


def test_setup_audit_is_pinned_as_part_of_raw_worker_evidence(staged_worker):
    state = staged_worker()
    assert state.execute()["verdict"] == "ACCEPT"
    path = runner.run_dir(state.rid)
    raw = state.raw
    raw["runtime"]["setup_audit"]["input_frozen_sha256"] = "0" * 64
    (path / "output/evidence.json").write_text(json.dumps(raw), encoding="utf-8")
    (path / "output/evidence.sha256").write_text(sha256_json(raw), encoding="utf-8")
    assert not runner.verify(state.rid)["ok"]