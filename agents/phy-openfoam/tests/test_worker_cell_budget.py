"""Post-meshing measured cell caps gate serial/MPI and restart solves; no CFD."""

from __future__ import annotations

import pytest

from discovery_physics import worker
from discovery_physics.openfoam import runner

import test_worker_setup

staged_worker = test_worker_setup.staged_worker


@pytest.mark.parametrize("log,rc,ok", [("cells: 100\n", 0, True), ("cells: 101\n", 0, False),
                                       ("", 0, False), ("cells: 0\n", 0, False),
                                       ("cells: 100\ncells: 99\n", 0, False), ("cells: 1\n", 1, False),
                                       ("cells: 1e4\n", 0, False), ("cells: -1\n", 0, False)])
def test_measured_budget_gate_requires_one_positive_within_cap(log, rc, ok, tmp_path):
    (tmp_path / "log.checkMesh").write_text(log, encoding="utf-8")
    result = worker._cell_budget(tmp_path, 100, rc)
    assert result["ok"] is ok and result["maximum_cells"] == 100


@pytest.mark.parametrize("ranks", [1, 2])
@pytest.mark.parametrize("bad_count", ["200001", "", "0", "2\ncells: 3"])
def test_oversized_or_unknown_measured_mesh_never_solves(staged_worker, ranks, bad_count):
    state = staged_worker(ranks=ranks)

    def measured(argv, case):
        if argv[0] == "checkMesh":
            (case / "log.checkMesh").write_text("cells: " + bad_count + "\n", encoding="utf-8")

    state.hook = measured
    result = state.execute()
    assert result["verdict"] != "ACCEPT"
    assert not any("foamRun" in args or args[0] == "decomposePar" for args in state.commands)
    assert state.raw["runtime"]["cell_budget"]["ok"] is False
    assert state.raw["metrics"]["mesh.within_cell_budget"]["value"] is False
    assert any("mesh budget:" in error for error in state.raw["errors"])


@pytest.mark.parametrize("ranks", [1, 2])
def test_continuation_remeasures_before_decomposition_or_solve(staged_worker, ranks):
    state = staged_worker(ranks=ranks)
    state.incomplete = True
    assert state.execute()["verdict"] == "CORRECT_AND_RERUN"
    accepted = runner.propose(state.rid, {"action": "CONTINUE_RUN", "end_time": 4.0,
                                         "rationale": "Synthetic healthy incomplete test; keep frozen limits."})
    state.rid = accepted["child_run_id"]
    state.commands.clear()

    def over_cap(argv, case):
        if argv[0] == "checkMesh":
            (case / "log.checkMesh").write_text("cells: 200001\n", encoding="utf-8")

    state.hook = over_cap
    assert state.execute()["verdict"] != "ACCEPT"
    assert state.commands[0] == ["checkMesh"]
    assert not any("foamRun" in args or args[0] == "decomposePar" for args in state.commands)