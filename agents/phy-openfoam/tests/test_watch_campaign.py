"""Synthetic heartbeat tests: no CFD, runtime, signing key, or real-time waits."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import watch_campaign as monitor

RID = "20261124T013732Z-3e98a21d"


def fixture_run(root: Path, *, state: str = "running", log: bool = True) -> Path:
    path = root / RID
    case = path / "output/case"
    (case / "system").mkdir(parents=True)
    (path / "plan.json").write_text(json.dumps({"run_id": RID, "end_time": 4000.0}), encoding="utf-8")
    (path / "state.json").write_text(json.dumps({"state": state}), encoding="utf-8")
    (path / "bundle.json").write_text(json.dumps({"name": "heated_H5_fine"}), encoding="utf-8")
    (case / "system/fvSchemes").write_text("ddtSchemes { default steadyState; }", encoding="utf-8")
    if log:
        (case / "log.foamRun.01").write_text("Time = 31s\nTime = 32s\npartial", encoding="utf-8")
    return path


def hashes(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_snapshot_is_read_only_and_iteration_is_not_wall_time(tmp_path):
    fixture_run(tmp_path)
    before = hashes(tmp_path)
    data = monitor.snapshot(tmp_path, now=0)
    line = monitor.format_line(data, label="channel", now=0, stale_seconds=120)
    assert "finalized 0/1" in line and "heated_H5_fine" in line
    assert "iteration 32/4000" in line and "reported running" in line
    assert "hints only" in line and "liveness evidence" in line
    assert hashes(tmp_path) == before


@pytest.mark.parametrize("content", ["", "{", "{}", "null", '{"state":"unknown"}'])
def test_partial_state_is_unknown_not_complete(tmp_path, content):
    path = fixture_run(tmp_path)
    (path / "state.json").write_text(content, encoding="utf-8")
    data = monitor.snapshot(tmp_path, now=0)
    assert data["unavailable"] == 1 and not data["all_final_hints"]
    assert "progress unavailable" in monitor.format_line(data, label="x", now=0, stale_seconds=120)


def test_new_container_without_solver_log_is_not_a_crash(tmp_path):
    fixture_run(tmp_path, log=False)
    data = monitor.snapshot(tmp_path, now=0)
    assert "log not yet available" in data["active"][0]
    assert not data["all_final_hints"]


def test_stale_output_does_not_assert_hung_or_healthy(tmp_path):
    path = fixture_run(tmp_path)
    timestamp = (path / "output/case/log.foamRun.01").stat().st_mtime
    data = monitor.snapshot(tmp_path, now=timestamp + 180)
    line = monitor.format_line(data, label="x", now=timestamp + 180, stale_seconds=120)
    assert "liveness uncertain, not proven hung" in line


def test_no_acceptance_from_partial_or_mismatched_final(tmp_path):
    path = fixture_run(tmp_path, state="done")
    for final in [{"final_verdict": "ACCEPT"},
                  {"run_id": "wrong", "final_verdict": "ACCEPT", "live_acceptance": True}]:
        (path / "final_decision.json").write_text(json.dumps(final), encoding="utf-8")
        data = monitor.snapshot(tmp_path, now=0)
        assert data["finalized"] == 0 and not data["all_final_hints"]


def test_mismatched_plan_cannot_make_other_final_hints_terminal(tmp_path):
    path = fixture_run(tmp_path)
    (path / "plan.json").write_text(json.dumps({"run_id": "wrong"}), encoding="utf-8")
    data = monitor.snapshot(tmp_path, now=0)
    assert data["total"] == 1 and data["unavailable"] == 1 and not data["all_final_hints"]


def test_log_reader_uses_bounded_tail_and_ignores_partial_new_time(tmp_path):
    path = fixture_run(tmp_path)
    (path / "output/case/log.foamRun.01").write_text(
        "Time = 1s\n" + "older output\n" * monitor.TAIL_BYTES + "Time = 123s\nTime = 456",
        encoding="utf-8",
    )
    data = monitor.snapshot(tmp_path, now=0)
    assert "iteration 123/4000" in data["active"][0]
    assert "456" not in data["active"][0]


def test_complete_final_stops_observer_but_never_claims_verified_winner(tmp_path):
    path = fixture_run(tmp_path, state="done")
    (path / "final_decision.json").write_text(json.dumps({
        "run_id": RID, "final_verdict": "REJECT", "live_acceptance": False,
    }), encoding="utf-8")
    output = []
    def no_wait(_):
        pytest.fail("A terminal hint should stop observation immediately")
    assert monitor.watch(tmp_path, now=lambda: 0, wait=no_wait, emit=output.append) == 0
    assert len(output) == 1 and "REJECT 1" in output[0]
    assert "study/design decision requires verification" in output[0]


def test_periodic_lines_use_fake_time_and_never_control_campaign(tmp_path):
    fixture_run(tmp_path)
    ticks = [0.0]
    waits, output = [], []
    def advance(seconds):
        waits.append(seconds)
        ticks[0] += seconds
    before = hashes(tmp_path)
    assert monitor.watch(tmp_path, max_seconds=125, clock=lambda: ticks[0], now=lambda: ticks[0],
                         wait=advance, emit=output.append) == 0
    assert waits == [60.0, 60.0, 5.0]
    assert len(output) == 4  # Initial, +60, +120, observer-only deadline notice.
    assert "00:01:00Z" in output[1] and "00:02:00Z" in output[2]
    assert "campaign untouched" in output[-1]
    assert hashes(tmp_path) == before


def test_labels_cannot_inject_lines_or_terminal_controls(tmp_path):
    fixture_run(tmp_path)
    data = monitor.snapshot(tmp_path, now=0)
    line = monitor.format_line(data, label="channel\n\x1b[31mred\r", now=0, stale_seconds=120)
    assert "\n" not in line and "\r" not in line and "\x1b" not in line


@pytest.mark.parametrize("interval", [0, 1, 59, float("nan"), float("inf")])
def test_no_hot_polling_intervals(tmp_path, interval):
    with pytest.raises(ValueError):
        monitor.watch(tmp_path, interval=interval, once=True)


def test_missing_store_not_created(tmp_path, capsys):
    missing = tmp_path / "not-created"
    with pytest.raises(SystemExit) as exc:
        monitor.main(["--runs-root", str(missing), "--once"])
    assert exc.value.code == 2 and not missing.exists()
    assert "nothing was created" in capsys.readouterr().err


def test_once_does_not_wait(tmp_path):
    fixture_run(tmp_path)
    def no_wait(_):
        pytest.fail("--once must not wait")
    assert monitor.watch(tmp_path, once=True, now=lambda: 0, wait=no_wait, emit=lambda _: None) == 0


def test_read_failure_reports_unknown_without_campaign_action(tmp_path, monkeypatch):
    output = []
    def inaccessible(*args, **kwargs):
        raise PermissionError("synthetic inaccessible store")
    monkeypatch.setattr(monitor, "snapshot", inaccessible)
    assert monitor.watch(tmp_path, once=True, emit=output.append) == 1
    assert len(output) == 1 and "progress unavailable" in output[0]
    assert not list(tmp_path.iterdir())