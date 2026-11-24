"""Held-out behavior scoring must be evidence-gated, not a keyword pass patch."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from discovery_physics.core.integrity import IntegrityError
from discovery_physics.openfoam import runner, study

from scripts import heldout, result_paths
from scripts.heldout import classify_behavior, final_answer


def _run(**changes):
    return {"integrity_ok": True, "executed": False, "ever_started": False,
            "final": None, "live_acceptance": False, "pending": [], **changes}


def _classify(expect, runs, answer="", **kwargs):
    return classify_behavior(expect, runs, kwargs.pop("studies", []), answer,
                             completed=kwargs.pop("completed", True), **kwargs)


def test_h14_signed_method_substitution_is_an_honest_block_not_an_accept():
    result = _classify("refuse", [_run(pending=["method_substitution"])],
                       "Objective could not be completed. No scientific verdict exists.")
    assert result["behaviour_ok"]
    assert result["outcome"] == "blocked_method_substitution"
    assert not result["refused_language"]


@pytest.mark.parametrize("changes", [
    {"executed": True}, {"ever_started": True}, {"integrity_ok": False},
    {"final": "ACCEPT", "live_acceptance": True},
])
def test_h14_gate_does_not_hide_an_execution_or_bad_record(changes):
    result = _classify("refuse", [_run(pending=["method_substitution"], **changes)])
    assert not result["behaviour_ok"]


def test_unrelated_pending_assumption_does_not_count_as_unsupported_refusal():
    assert not _classify("refuse", [_run(pending=["wall_temperature"])])["behaviour_ok"]


@pytest.mark.parametrize("expect,answer", [
    ("run", ""), ("clarify", "What geometry?"), ("refuse", "REJECT_UNSUPPORTED"),
    ("run_honest", "What geometry?"),
])
def test_integrity_is_required_for_every_behavior(expect, answer):
    assert not _classify(expect, [_run(integrity_ok=False, final="REJECT")], answer)["behaviour_ok"]


def test_unassessed_execution_cannot_masquerade_as_clarification():
    assert not _classify("clarify", [_run(ever_started=True)], "Which geometry?")["behaviour_ok"]


@pytest.mark.parametrize("live", [False, None, "true"])
def test_accept_requires_boolean_live_acceptance(live):
    result = _classify("run", [_run(final="ACCEPT", live_acceptance=live)])
    assert not result["behaviour_ok"]
    assert result["reason"] == "accept_without_live_evidence"


def test_failed_or_missing_completion_receipt_cannot_pass():
    assert not _classify("run", [_run(final="REJECT")], completed=False)["behaviour_ok"]


def test_invalid_final_label_cannot_count_as_a_finalized_run():
    assert not _classify("run", [_run(final="SUCCESS")])["behaviour_ok"]


def test_study_requires_verified_run_and_study_records():
    good = {"verdict": "ACCEPT", "integrity_ok": True}
    assert _classify("study", [_run(final="REJECT")], studies=[good])["behaviour_ok"]
    assert not _classify("study", [], studies=[good])["behaviour_ok"]
    assert not _classify(
        "study", [_run()], studies=[{**good, "integrity_ok": False}],
    )["behaviour_ok"]


def test_prepared_only_study_is_not_a_completed_result():
    prepared = {"verdict": None, "integrity_ok": True, "assessed": False}
    assert not _classify("study", [_run()], studies=[prepared])["behaviour_ok"]
    good = {"verdict": "ACCEPT", "integrity_ok": True, "assessed": True}
    assert _classify("study", [_run()], studies=[prepared, good])["behaviour_ok"]


def test_study_integrity_exception_is_a_scoring_failure(tmp_path, monkeypatch):
    (tmp_path / "studies" / "Sbad").mkdir(parents=True)

    def fail(_):
        raise IntegrityError("bad signature")

    monkeypatch.setattr(study, "_verified_study", fail)
    rows = heldout._study_results(tmp_path)
    assert len(rows) == 1 and not rows[0]["integrity_ok"]
    assert "bad signature" in rows[0]["error"]


def test_score_counts_integrity_errors_and_restores_the_store(tmp_path, monkeypatch):
    monkeypatch.setattr(heldout, "OUT", tmp_path)
    prompts = tmp_path / "prompts.json"
    prompts.write_text(
        json.dumps([{"id": "H01", "kind": "internal", "expect": "run"}]), encoding="utf-8",
    )
    monkeypatch.setattr(heldout, "PROMPTS", prompts)
    monkeypatch.setenv("DISCOVERY_PHYSICS_RUNS", "original-store")
    d = tmp_path / "H01"
    (d / "clio").mkdir(parents=True)
    (d / "runs" / "20261122T000000Z-00000000").mkdir(parents=True)
    (d / "driver.json").write_text(json.dumps({"rc": 0, "wall_s": 1}), encoding="utf-8")
    (d / "clio" / "result.json").write_text(
        json.dumps({"run_id": "abc123", "state": "done"}), encoding="utf-8",
    )
    (d / "clio" / "wait.log").write_text(
        "run abc123 [done]\n===== RESULT =====\nREJECT\n---\n", encoding="utf-8",
    )

    def fail(_):
        raise IntegrityError("bad signature")

    monkeypatch.setattr(runner, "verified", fail)
    s = heldout.score(tmp_path / "scored.json")
    assert s["n"] == 1 and s["behaviour_ok"] == 0 and s["tampered_runs"] == 1
    assert heldout.os.environ["DISCOVERY_PHYSICS_RUNS"] == "original-store"


def test_terminal_answer_is_not_truncated_or_taken_from_another_run(tmp_path):
    clio = tmp_path / "clio"
    clio.mkdir()
    (clio / "result.json").write_text(
        json.dumps({"run_id": "abc123", "state": "done"}), encoding="utf-8",
    )
    answer = "Refusal rationale: " + "x" * 7000 + " No solver was executed."
    (clio / "wait.log").write_text(
        "run dead00 [done]\n===== RESULT =====\nwrong answer\n---\n"
        "run abc123 [running] seq=2\nquoted [done] does not finish a run\n---\n"
        f"run abc123 [done]\n===== RESULT =====\n{answer}\n---\n",
        encoding="utf-8",
    )
    assert final_answer(tmp_path) == answer


def test_missing_terminal_marker_is_not_a_completed_answer(tmp_path):
    clio = tmp_path / "clio"
    clio.mkdir()
    (clio / "result.json").write_text(json.dumps({"run_id": "abc123"}), encoding="utf-8")
    (clio / "wait.log").write_text("run abc123 [running] seq=2\nWhich geometry?", encoding="utf-8")
    assert final_answer(tmp_path) == ""


def _installed_skill(workspace):
    path = workspace / ".github" / "skills" / "phy-openfoam" / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("Synthetic installed-skill marker.\n", encoding="utf-8")


def _routed_project(tmp_path):
    workspace = tmp_path / "project"
    _installed_skill(workspace)
    manifest = result_paths.load_guard(workspace).initialize(workspace, "heldout", exact=True)
    return workspace.resolve(), Path(manifest["results_root"])


def test_harness_import_is_portable_without_localappdata(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("DISCOVERY_PHYSICS_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    namespace = runpy.run_path(heldout.__file__, run_name="portable_heldout_import")
    assert namespace["OUT"] == tmp_path / "DiscoveryPhysics" / "heldout"
    assert namespace["PY"] == Path(sys.executable)
    assert not namespace["OUT"].exists()


@pytest.mark.parametrize("inherited", [None, "0", "1"])
@pytest.mark.parametrize("explicit", [False, True])
def test_resource_policy_requires_operator_flag_or_inherited_configuration(
    tmp_path, monkeypatch, inherited, explicit,
):
    workspace, results = _routed_project(tmp_path)
    monkeypatch.setattr(heldout, "WS", workspace)
    monkeypatch.setattr(heldout, "OUT", tmp_path / "work")
    monkeypatch.setenv("DISCOVERY_PHYSICS_RUNS", "operator-original-store")
    config = tmp_path / "operator-config.json"
    config.write_text('{"allow_unenforced_limits": true}', encoding="utf-8")
    monkeypatch.setenv("DISCOVERY_PHYSICS_CONFIG", str(config))
    flag = "DISCOVERY_PHYSICS_ALLOW_UNENFORCED_LIMITS"
    if inherited is None:
        monkeypatch.delenv(flag, raising=False)
    else:
        monkeypatch.setenv(flag, inherited)
    observed = {}
    stdout, stderr = "complete UTF-8 receipt: \u03bb" * 400, "full stderr receipt\n" * 200

    def fake_run(command, **kwargs):
        observed.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(heldout.subprocess, "run", fake_run)
    row = heldout.run_one({"id": "H99", "prompt": "Synthetic prompt"},
                          project_root=workspace, results_dir=results,
                          work_root=results / "analysis" / "work",
                          allow_unenforced_limits=explicit)
    expected = "1" if explicit else inherited
    assert observed["env"].get(flag) == expected
    assert heldout.os.environ.get(flag) == inherited
    assert observed["env"]["DISCOVERY_PHYSICS_CONFIG"] == str(config)
    assert heldout.os.environ["DISCOVERY_PHYSICS_RUNS"] == "operator-original-store"
    assert observed["command"][0] == sys.executable
    assert observed["cwd"] == workspace.resolve()
    directory = results / "analysis" / "work" / "H99"
    assert observed["env"]["DISCOVERY_PHYSICS_RUNS"] == str(results / "runs" / "H99" / "runs")
    command = observed["command"]
    assert command[command.index("--project-root") + 1] == str(workspace)
    assert command[command.index("--results-dir") + 1] == str(results)
    assert (directory / "stdout.log").read_text(encoding="utf-8") == stdout
    assert (directory / "stderr.log").read_text(encoding="utf-8") == stderr
    assert row["operator_resource_policy"]["allow_unenforced_limits_flag"] is explicit


def test_live_run_requires_installed_skill_not_merely_the_packaged_template(tmp_path, monkeypatch):
    packaged = tmp_path / "skills" / "phy-openfoam" / "SKILL.md"
    packaged.parent.mkdir(parents=True)
    packaged.write_text("Packaged template, not installed.\n", encoding="utf-8")
    monkeypatch.setattr(heldout.subprocess, "run", lambda *a, **k: pytest.fail("must fail first"))
    manifest = result_paths.load_guard(tmp_path).initialize(tmp_path, "heldout", exact=True)
    results = Path(manifest["results_root"])
    output = results / "analysis" / "work"
    with pytest.raises(FileNotFoundError, match="installed phy-openfoam skill"):
        heldout.run_one({"id": "H99", "prompt": "test"}, project_root=tmp_path,
                        results_dir=results, workspace=tmp_path, work_root=output)
    assert not output.exists()


def test_run_one_uses_selected_interpreter_workspace_and_clio(tmp_path, monkeypatch):
    workspace, results = _routed_project(tmp_path)
    observed = {}

    def fake_run(command, **kwargs):
        observed.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(heldout.subprocess, "run", fake_run)
    heldout.run_one(
        {"id": "H99", "prompt": "Synthetic prompt"}, workspace=workspace,
        project_root=workspace, results_dir=results, work_root=results / "analysis" / "work",
        python="selected-python", clio_executable="selected-clio",
    )
    command = observed["command"]
    assert command[0] == "selected-python"
    assert command[3] == str(Path(heldout.__file__).with_name("clio_driver.py"))
    assert command[command.index("--cwd") + 1] == str(workspace.resolve())
    assert command[command.index("--clio-executable") + 1] == "selected-clio"


def test_live_cli_forwards_portable_options_and_explicit_operator_flag(tmp_path, monkeypatch):
    workspace, results = _routed_project(tmp_path)
    prompts = tmp_path / "prompts.json"
    prompts.write_text(json.dumps([{"id": "H99", "prompt": "Synthetic prompt"}]), encoding="utf-8")
    monkeypatch.setattr(heldout, "PROMPTS", prompts)
    observed = []

    def fake_run(prompt, **kwargs):
        observed.append((prompt, kwargs))
        return {"rc": 0}

    monkeypatch.setattr(heldout, "run_one", fake_run)
    assert heldout.main([
        "run", "--project-root", str(workspace), "--results-dir", str(results),
        "--out", "analysis/launch.json", "--workspace", str(workspace),
        "--work-root", str(results / "analysis" / "work"),
        "--python", "selected-python", "--clio-executable", "selected-clio",
        "--allow-unenforced-limits", "--parallel", "1",
    ]) == 0
    assert observed[0][1] == {
        "workspace": workspace.resolve(), "work_root": results / "analysis" / "work",
        "project_root": workspace, "results_dir": results,
        "python": "selected-python", "clio_executable": "selected-clio",
        "allow_unenforced_limits": True,
    }


def test_score_work_root_needs_neither_installed_skill_nor_source_path_injection(
    tmp_path, monkeypatch,
):
    prompts = tmp_path / "prompts.json"
    prompts.write_text(
        json.dumps([{"id": "H99", "kind": "missing", "expect": "refuse"}]), encoding="utf-8",
    )
    monkeypatch.setattr(heldout, "PROMPTS", prompts)
    monkeypatch.setattr(heldout, "WS", tmp_path / "not-an-installed-workspace")
    monkeypatch.setattr(heldout, "OUT", tmp_path / "unused-default")
    before = list(sys.path)
    with pytest.raises(ValueError, match="explicit score output"):
        heldout.score(work_root=tmp_path / "selected-work")
    output = tmp_path / "explicit-score.json"
    result = heldout.score(output, work_root=tmp_path / "selected-work")
    assert result["n"] == 1 and result["completed"] == 0
    assert output.is_file() and not (tmp_path / "selected-work").exists()
    assert not (tmp_path / "unused-default").exists()
    assert sys.path == before