"""Comparison accuracy must never hide missing answers or unverified evidence."""

from __future__ import annotations

import json

import pytest
from discovery_physics.benchmarks import comparison
from discovery_physics.core.integrity import IntegrityError


@pytest.fixture
def truth(tmp_path):
    path = tmp_path / "truth.json"
    path.write_text(json.dumps({
        "A": {"truth": "ACCEPT", "group": "archived", "detectable": True},
        "B": {"truth": "CORRECT_AND_RERUN", "group": "archived", "detectable": True},
        "F": {"truth": "NOT_ACCEPT", "group": "fault", "detectable": False},
    }), encoding="utf-8")
    return path


def _answers(**changes):
    return {"A": "ACCEPT", "B": "CORRECT_AND_RERUN", "F": "REJECT", **changes}


def test_complete_model_answers_are_scored_by_group(truth):
    result = comparison.score_model(_answers(), truth)
    assert result["archived"]["points"] == 2 and result["archived"]["correct"] == 2
    assert result["fault"]["correct"] == 1


@pytest.mark.parametrize("answers", [{}, {"A": "ACCEPT"}, _answers(X="REJECT")])
def test_incomplete_or_unknown_model_points_are_rejected(truth, answers):
    with pytest.raises(ValueError, match="coverage mismatch"):
        comparison.score_model(answers, truth)


@pytest.mark.parametrize("label", ["NOT_ACCEPT", "PASS", "", None, True, ["REJECT"]])
def test_arbitrary_verdict_cannot_score_as_a_correct_nonaccept(truth, label):
    with pytest.raises(ValueError, match="invalid model verdicts"):
        comparison.score_model(_answers(F=label), truth)


def test_paper_runtime_alias_is_explicitly_normalized(truth):
    assert (
        comparison.score_model(_answers(B="NEEDS_MORE_RUNTIME"), truth)["archived"]["correct"]
        == 2
    )


def test_false_accepts_separate_blind_detectability(truth):
    result = comparison.score_model(_answers(F="ACCEPT"), truth)
    assert result["fault"]["false_accept"] == 1
    assert result["fault"]["false_accept_detectable"] == 0


def test_packet_loading_requires_a_verified_assessment(monkeypatch):
    monkeypatch.setattr(comparison.runner, "verified", lambda _: {"assessed": None})
    with pytest.raises(ValueError, match="no verified assessment"):
        comparison._load("unassessed")


def test_packet_loading_propagates_integrity_failure(monkeypatch):
    def fail(_):
        raise IntegrityError("bad signature")

    monkeypatch.setattr(comparison.runner, "verified", fail)
    with pytest.raises(IntegrityError, match="bad signature"):
        comparison._load("tampered")