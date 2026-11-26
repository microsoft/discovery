"""Service-only study confirmation refusals are atomic; no CFD, keys or stores."""

from __future__ import annotations

import base64
import copy
import gzip
import json
from pathlib import Path

import pytest
import yaml

from discovery_physics import service
from discovery_physics.core import config, integrity
from discovery_physics.core.models import CaseBundle
from discovery_physics.openfoam import runner, study


def assumption(parameter, source="needs_confirmation"):
    return {"parameter": parameter, "value": "proposed", "source": source,
            "justification": "Synthetic service-boundary test assumption."}


def study_spec(names=("baseline", "candidate")):
    members = []
    for name in names:
        bundle = {
            "name": name, "solver": "incompressibleFluid",
            "files": {"system/controlDict": "application foamRun; endTime 1;\n",
                      "system/fvSchemes": "ddtSchemes { default steadyState; }\n",
                      "system/fvSolution": "solvers {}\n"},
            "diagnostics": {"fields": [{"name": "p"}], "target_time": 1.0},
            "contract": {
                "id": "service_contract", "title": "Synthetic service boundary",
                "requested_prompt": "Check service validation without running a solver.",
                "regime": "steady",
                "objectives": [{"id": "health", "description": "Solver completes normally.",
                                "claim": "numerical_health", "check_ids": ["completed"]}],
                "checks": [{"id": "completed", "metric": "solver.completed", "operator": "true",
                            "category": "execution", "rationale": "Require normal solver completion."}],
                "assumptions": [],
            },
        }
        members.append({"name": name, "bundle": bundle})
    return {"id": "service_study", "title": "Synthetic service study",
            "requested_prompt": "Validate every member before staging anything.", "kind": "sweep",
            "members": members,
            "criteria": [{"id": "health", "kind": "all_accept",
                          "rationale": "Every member must have verified accepted evidence."}]}


@pytest.fixture(autouse=True)
def isolated_service(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "OUTPUT", tmp_path / "output")
    for name, value in {
        "DISCOVERY_PHYSICS_IN_CONTAINER": "1",
        "DISCOVERY_PHYSICS_RUNS": str(tmp_path / "runs"),
        "DISCOVERY_PHYSICS_KEY_FILE": str(tmp_path / "keys/journal.key"),
        "DISCOVERY_PHYSICS_HOME": str(tmp_path / "home"),
        "DISCOVERY_PHYSICS_CONFIG": str(tmp_path / "operator.json"),
        "LOCALAPPDATA": str(tmp_path / "local"),
    }.items():
        monkeypatch.setenv(name, value)

    def forbidden(*args, **kwargs):
        pytest.fail("Service prevalidation reached staging, execution, confirmation or private state.")

    for module, symbols in (
        (study, ("prepare", "assess", "studies_root")),
        (runner, ("prepare", "execute", "confirm", "runs_root")),
        (service, ("_drive",)), (integrity, ("_key",)), (config, ("load",)),
    ):
        for symbol in symbols:
            monkeypatch.setattr(module, symbol, forbidden)
    return tmp_path


def invoke(spec, tmp_path, capsys, expected_status=2):
    payload = base64.b64encode(gzip.compress(json.dumps(spec).encode("utf-8"), mtime=0)).decode("ascii")
    assert service.main(["study", "--spec-b64gz", payload]) == expected_status
    result = json.loads((tmp_path / "output/result.json").read_text(encoding="utf-8"))
    assert json.loads(capsys.readouterr().out) == result
    # Even a refused call may write its error result, but nothing else.
    assert {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")} == {
        "output", "output/result.json",
    }
    return result


@pytest.mark.parametrize("pending", [
    {"baseline": ["method_substitution"]},
    {"candidate": ["wall_temperature"]},
    {"baseline": ["wall_temperature", "method_substitution"],
     "candidate": ["wall_temperature", "material_model"]},
])
def test_service_refuses_pending_members_before_any_staging(pending, tmp_path, capsys):
    spec = study_spec()
    for member in spec["members"]:
        member["bundle"]["contract"]["assumptions"] = [
            assumption("already_supplied", "user"),
            *(assumption(parameter) for parameter in pending.get(member["name"], [])),
        ]
    # The local models still allow these bundles; only the service transport refuses them.
    model = study.Study.model_validate(spec)
    for member in model.members:
        CaseBundle.model_validate(member.bundle)
    original = copy.deepcopy(spec)
    result = invoke(spec, tmp_path, capsys)
    assert result["error"] == "StudyConfirmationRequired"
    assert result["pending_parameters_by_member"] == pending
    assert "member-scoped confirmation" in result["detail"]
    assert "local" in result["detail"] and "study-prepare" in result["detail"]
    assert "confirm each member" in result["detail"]
    assert "discovery-physics confirm <run_id>" in result["detail"]
    for name, parameters in pending.items():
        assert name in result["detail"]
        assert all(parameter in result["detail"] for parameter in parameters)
    assert spec == original


def test_pending_parameter_details_survive_bounded_error_text(tmp_path, capsys):
    spec = study_spec(tuple(f"member_{i}" for i in range(32)))
    parameters = [f"pending_{i}_" + "x" * 100 for i in range(4)]
    pending = {}
    for member in spec["members"]:
        member["bundle"]["contract"]["assumptions"] = [assumption(p) for p in parameters]
        pending[member["name"]] = parameters
    result = invoke(spec, tmp_path, capsys)
    assert len(result["detail"]) == 4000
    assert "study-prepare" in result["detail"] and "confirm each member" in result["detail"]
    assert result["pending_parameters_by_member"] == pending


@pytest.mark.parametrize("fault,needle", [
    ("missing_id", "id"), ("duplicate_names", "member names must be unique"),
    ("missing_all_accept", "all_accept"), ("single_member", "members"),
    ("unknown_field", "extra_forbidden"),
])
def test_service_validates_study_before_prepare(fault, needle, tmp_path, capsys):
    spec = study_spec()
    if fault == "missing_id":
        del spec["id"]
    elif fault == "duplicate_names":
        spec["members"][1]["name"] = spec["members"][0]["name"]
    elif fault == "missing_all_accept":
        spec["criteria"] = [{"id": "range", "kind": "range", "metric": "solver.steps",
                             "bounds": [0.0, 10.0], "rationale": "Synthetic range criterion."}]
    elif fault == "single_member":
        spec["members"].pop()
    else:
        spec["confirmations"] = []
    result = invoke(spec, tmp_path, capsys)
    assert result["error"] == "ValidationError"
    assert needle in result["detail"]


@pytest.mark.parametrize("member_index", [0, 1])
@pytest.mark.parametrize("fault,needle", [
    ("missing_contract", "contract"), ("malformed_assumptions", "assumptions"),
    ("missing_source", "source"), ("invalid_source", "source"),
    ("missing_case_file", "controlDict"),
])
def test_service_validates_every_case_bundle_before_prepare(
    member_index, fault, needle, tmp_path, capsys,
):
    spec = study_spec()
    bundle = spec["members"][member_index]["bundle"]
    if fault == "missing_contract":
        del bundle["contract"]
    elif fault == "malformed_assumptions":
        bundle["contract"]["assumptions"] = {"source": "needs_confirmation"}
    elif fault in {"missing_source", "invalid_source"}:
        item = assumption("wall_temperature")
        if fault == "missing_source":
            del item["source"]
        else:
            item["source"] = "confirmed"
        bundle["contract"]["assumptions"] = [item]
    else:
        del bundle["files"]["system/controlDict"]
        bundle["files"]["constant/transportProperties"] = "nu 1e-6;\n"
    result = invoke(spec, tmp_path, capsys)
    assert result["error"] == "ValidationError"
    assert needle in result["detail"]


def test_later_invalid_bundle_is_validated_even_after_pending_assumption(tmp_path, capsys):
    spec = study_spec()
    spec["members"][0]["bundle"]["contract"]["assumptions"] = [assumption("method_substitution")]
    spec["members"][1]["bundle"]["contract"]["assumptions"] = [assumption("bad_source", "unknown")]
    result = invoke(spec, tmp_path, capsys)
    assert result["error"] == "ValidationError"
    assert "source" in result["detail"]


@pytest.mark.parametrize("assumptions", [None, [], [
    assumption("wall_temperature", "user"), assumption("cell_size", "derived"),
    assumption("material_model", "documented_default"),
]])
def test_confirmation_free_study_keeps_existing_service_flow(assumptions, tmp_path, capsys, monkeypatch):
    spec = study_spec()
    for member in spec["members"]:
        if assumptions is None:
            del member["bundle"]["contract"]["assumptions"]
        else:
            member["bundle"]["contract"]["assumptions"] = copy.deepcopy(assumptions)
    original = copy.deepcopy(spec)
    events = []
    run_ids = {m["name"]: f"synthetic-{m['name']}" for m in spec["members"]}
    finals = {name: {"run_id": rid, "final_verdict": "INCONCLUSIVE"} for name, rid in run_ids.items()}
    assessment = {"study_id": "synthetic-study", "verdict": "INCONCLUSIVE"}

    def prepare(data):
        assert data == original
        events.append("prepare")
        return {"study_id": "synthetic-study", "members": run_ids}

    def drive(run_id, bundle):
        name = bundle["name"]
        assert run_id == run_ids[name]
        assert bundle == next(m["bundle"] for m in original["members"] if m["name"] == name)
        events.append(name)
        return finals[name], [], run_id

    def assess(study_id):
        assert study_id == "synthetic-study"
        events.append("assess")
        return assessment

    monkeypatch.setattr(study, "prepare", prepare)
    monkeypatch.setattr(service, "_drive", drive)
    monkeypatch.setattr(study, "assess", assess)
    result = invoke(spec, tmp_path, capsys, expected_status=0)
    assert events == ["prepare", *run_ids, "assess"]
    assert result == {"study": assessment, "members": finals}
    assert spec == original


def test_action_descriptions_document_refusal_and_result_trust_limits():
    root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((root / "tools/openfoam/tool.yaml").read_text(encoding="utf-8"))
    actions = {action["name"]: action for action in manifest["actions"]}
    description = actions["study"]["description"]
    assert "needs_confirmation" in description and "before" in description
    assert "study-prepare" in description and "confirm each member" in description
    assert "no member-scoped confirmation transport" in description.lower()
    for name in ("evaluate", "study"):
        description = actions[name]["description"].lower()
        for marker in ("unsigned", "untrusted", "journal", "pinned artifacts", "temporary", "key"):
            assert marker in description
        assert "durable cloud verification" in description
        assert "public signature" in description
    assert "signed verdict record" not in actions["evaluate"]["description"].lower()
    # Preserve the catalog-supported transport schema instead of inventing confirmation keywords.
    assert actions["study"]["input_schema"]["required"] == ["spec_b64gz"]
    assert set(actions["study"]["input_schema"]["properties"]) == {"spec_b64gz"}
    for action in actions.values():
        assert set(action["input_schema"]) == {"type", "required", "properties"}