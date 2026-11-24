"""Packet-level blinding and strict native model output parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import model_comparison
from scripts.model_comparison import audit_tool_events, parse_predictions, prepare_batches


def _packets():
    blind = [{"point": f"F{i:02d}", "group": "fault", "contract_title": "case",
              "regime": "steady", "target_time": 1, "measured": {"solver.completed": True}}
             for i in range(1, 5)]
    full = [{**p, "checks": [{"state": "PASS"}], "verdict": "ACCEPT"} for p in blind]
    return full, blind


def test_paired_batches_remove_group_and_original_identifiers():
    full, blind = _packets()
    aliases, batches = prepare_batches(full, blind, seed=42, batch_size=2)
    assert set(aliases.values()) == {p["point"] for p in blind}
    assert [b["batch"] for b in batches] == ["C01", "C02", "B01", "B02"]
    for batch in batches:
        for p in batch["packets"]:
            assert p["point"].startswith("P") and "group" not in p
            if batch["arm"] == "C_blind":
                assert "checks" not in p and "verdict" not in p
    assert prepare_batches(full, blind, seed=42, batch_size=2) == (aliases, batches)


@pytest.mark.parametrize("change", ["duplicate", "unpaired", "leak", "different_measurements"])
def test_bad_packet_pairing_fails_before_a_model_run(change):
    full, blind = _packets()
    if change == "duplicate":
        full.append(full[0])
    elif change == "unpaired":
        blind.pop()
    elif change == "leak":
        blind[0]["verdict"] = "ACCEPT"
    else:
        blind[0] = {**blind[0], "measured": {"solver.completed": False}}
    with pytest.raises(ValueError):
        prepare_batches(full, blind, seed=42, batch_size=2)


def _response():
    return {"predictions": [{"point": "P01", "verdict": "ACCEPT", "rationale": "completed",
                              "evidence_metrics": ["solver.completed"]}], "limitations": []}


def _expected():
    return [{"point": "P01", "measured": {"solver.completed": True}}]


def test_complete_model_output_parses_without_changing_judgments():
    assert parse_predictions(json.dumps(_response()), _expected()) == _response()


@pytest.mark.parametrize("change", [
    "missing", "duplicate", "unknown", "invalid_label", "invented_metric", "no_reason",
])
def test_bad_model_outputs_are_not_scored(change):
    data = _response()
    row = data["predictions"][0]
    if change == "missing":
        data["predictions"] = []
    elif change == "duplicate":
        data["predictions"].append(dict(row))
    elif change == "unknown":
        row["point"] = "P99"
    elif change == "invalid_label":
        row["verdict"] = "PASS"
    elif change == "invented_metric":
        row["evidence_metrics"] = ["fabricated.metric"]
    else:
        row["rationale"] = ""
    with pytest.raises(ValueError):
        parse_predictions(json.dumps(data), _expected())


def test_duplicate_json_keys_are_rejected_before_dictionary_normalization():
    with pytest.raises(ValueError, match="duplicate JSON key"):
        parse_predictions('{"predictions":[],"predictions":[],"limitations":[]}', _expected())


def _start(name, args, call="read-packet"):
    return {"type": "tool.execution_start", "data": {
        "toolCallId": call, "toolName": name, "arguments": args,
    }}


def _spill(path, *, success=True):
    return {"type": "tool.execution_complete", "data": {
        "toolCallId": "read-packet", "success": success, "result": {
            "content": f"Output too large to read at once (32.2 KB). Saved to: {path}\n",
        },
    }}


def test_same_session_packet_overflow_is_not_external_evidence(tmp_path, monkeypatch):
    from scripts import model_comparison

    temp = tmp_path / "temp"
    temp.mkdir()
    output = temp / "copilot-tool-output-1234-abc.txt"
    monkeypatch.setattr(model_comparison.tempfile, "gettempdir", lambda: str(temp))
    events = [_start("powershell", {"command": "Get-Content packet.json"}),
              _spill(output), _start("view", {"path": str(output)}, "read-output")]
    result = audit_tool_events(events, tmp_path / "input")
    assert result["policy_violations"] == []
    assert len(result["same_session_overflow_outputs"]) == 1


@pytest.mark.parametrize("invalid", ["no_creation", "failed", "forbidden_origin", "wrong_name"])
def test_temp_files_require_exact_allowed_creation_provenance(tmp_path, monkeypatch, invalid):
    from scripts import model_comparison

    temp = tmp_path / "temp"
    temp.mkdir()
    output = temp / ("other.txt" if invalid == "wrong_name" else "copilot-tool-output-1234.txt")
    monkeypatch.setattr(model_comparison.tempfile, "gettempdir", lambda: str(temp))
    command = (
        "Get-Content truth.json" if invalid == "forbidden_origin" else "Get-Content packet.json"
    )
    events = [_start("powershell", {"command": command})]
    if invalid != "no_creation":
        events.append(_spill(output, success=invalid != "failed"))
    events.append(_start("view", {"path": str(output)}, "read-output"))
    assert audit_tool_events(events, tmp_path / "input")["policy_violations"]


def _native_state(root, *, session="synthetic-session", events=None):
    index = root / "science-runs" / "abc123.json"
    index.parent.mkdir(parents=True)
    index.write_text(json.dumps({"session_id": session}), encoding="utf-8")
    if events is None:
        events = [
            {"type": "assistant.message", "data": {"model": "synthetic-model",
                                                  "apiCallId": "opaque-not-for-publication"}},
            {"type": "session.shutdown", "data": {"modelMetrics": {"synthetic-model": {
                "requests": {"count": 1}, "usage": {"inputTokens": 12, "outputTokens": 7},
            }}}},
        ]
    if "/" not in session and "\\" not in session:
        path = root / "session-state" / session / "events.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")


def test_native_state_override_retains_only_bounded_model_provenance(tmp_path, monkeypatch):
    root = tmp_path / "selected-native-state"
    _native_state(root)
    monkeypatch.setenv("DISCOVERY_CLIO_STATE_HOME", str(root))
    assert model_comparison.native_state_home() == root.resolve()
    receipt = model_comparison.native_receipt("abc123", tmp_path / "input")
    assert receipt["response_models"] == ["synthetic-model"]
    assert receipt["model_metrics"]["synthetic-model"] == {
        "requests": 1, "input_tokens": 12, "output_tokens": 7,
    }
    assert receipt["policy_violations"] == []
    assert "opaque-not-for-publication" not in json.dumps(receipt)


def test_native_state_explicit_root_overrides_environment(tmp_path, monkeypatch):
    root = tmp_path / "selected-native-state"
    _native_state(root)
    monkeypatch.setenv("DISCOVERY_CLIO_STATE_HOME", str(tmp_path / "wrong-state"))
    receipt = model_comparison.native_receipt("abc123", tmp_path / "input", state_home=root)
    assert receipt["session_id"] == "synthetic-session"


@pytest.mark.parametrize("invalid", ["../outside", "..\\outside", "/absolute", ""])
def test_native_receipt_rejects_session_path_traversal(tmp_path, invalid):
    root = tmp_path / "state"
    _native_state(root, session=invalid)
    with pytest.raises(ValueError, match="invalid native CLIO session ID"):
        model_comparison.native_receipt("abc123", tmp_path / "input", state_home=root)


def test_native_receipt_rejects_run_path_traversal_before_reading(tmp_path):
    with pytest.raises(ValueError, match="invalid native CLIO run ID"):
        model_comparison.native_receipt("../abc123", tmp_path, state_home=tmp_path)


@pytest.mark.parametrize("events", [
    [{"type": "assistant.message", "data": {"model": "synthetic-model"}}],
    [{"type": "session.shutdown", "data": {"modelMetrics": {
        "synthetic-model": {"requests": {"count": 1}},
    }}}],
    [{"type": "assistant.message", "data": {"model": "synthetic-model"}},
     {"type": "session.shutdown", "data": {"modelMetrics": {
         "synthetic-model": {"requests": {"count": 0}},
     }}}],
])
def test_native_state_override_does_not_relax_response_model_evidence(tmp_path, events):
    root = tmp_path / "state"
    _native_state(root, events=events)
    with pytest.raises(ValueError, match="nonzero request evidence"):
        model_comparison.native_receipt("abc123", tmp_path / "input", state_home=root)


def test_relocated_native_state_is_still_disallowed_review_data(tmp_path):
    events = [_start("bash", {"command": "cat /custom/state/session-state/id/events.jsonl"})]
    assert audit_tool_events(events, tmp_path / "input")["policy_violations"]


def test_comparison_defaults_do_not_require_localappdata(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("DISCOVERY_CLIO_STATE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert model_comparison.data_home() == tmp_path / "DiscoveryPhysics"
    assert model_comparison.native_state_home() == (tmp_path / ".copilot").resolve()


@pytest.mark.parametrize("explicit", [False, True])
def test_comparison_work_store_is_portable_without_model_calls(tmp_path, monkeypatch, explicit):
    packets = tmp_path / "packets"
    packets.mkdir()
    full, blind = _packets()
    for name, value in (("B_full", full), ("C_blind", blind)):
        (packets / f"packets_{name}.json").write_text(json.dumps(value), encoding="utf-8")
    (packets / "truth.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    observed = []

    def fake_review(batch, work, published, timeout):
        observed.append(work)
        return {"batch": batch["batch"]}

    monkeypatch.setattr(model_comparison, "review_batch", fake_review)
    monkeypatch.setattr(model_comparison, "score_reviews", lambda *args: {"synthetic": True})
    selected = tmp_path / "selected-work" if explicit else None
    result = model_comparison.run_comparison(
        packets, tmp_path / "published", seed=42, batch_size=2, jobs=1, timeout=1,
        work_root=selected,
    )
    expected = selected or tmp_path / "published" / "work"
    assert result == {"synthetic": True}
    assert len(observed) == 4 and len(set(observed)) == 1
    assert observed[0].parent == expected.resolve()