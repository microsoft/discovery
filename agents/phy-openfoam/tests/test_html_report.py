"""Offline HTML presentation tests; synthetic cases never supply CFD acceptance."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "skills/phy-openfoam/scripts/render_report.py"
SPEC = importlib.util.spec_from_file_location("phy_openfoam_html_report", HELPER)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)
_generate = report.generate


def generate(*, out, **kwargs):
    # Presentation tests select an explicit marked user project; they do not
    # weaken the production API's project/result-container requirement.
    project = out.parent
    project.mkdir(parents=True, exist_ok=True)
    marker = project / "results-html-test/results-manifest.json"
    if marker.is_file():
        results = marker.parent
    else:
        results = Path(report.results_policy.initialize(project, "html-test", exact=True)["results_root"])
    kwargs.update(project=project, results=results, out=results)
    return _generate(**kwargs)


RUN = "20261124T010203Z-1234abcd"
STUDY = "S20261124T010203Z-1234abcd"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==")


class HTMLFacts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.images = []
        self.sections = []
        self.in_section = None

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        attributes = dict(attrs)
        if tag == "section":
            self.in_section = attributes.get("id", "detail")
            self.sections.append(self.in_section)
        if tag == "img":
            self.images.append((self.in_section, attributes))
        assert not any(key.startswith("on") for key in attributes)


def bundle():
    return {"files": {"system/blockMeshDict": """FoamFile { format ascii; class dictionary; object blockMeshDict; }
vertices ((0 0 0) (1 0 0) (1 .1 0) (0 .1 0) (0 0 .01) (1 0 .01) (1 .1 .01) (0 .1 .01));
blocks (hex (0 1 2 3 4 5 6 7) (10 4 1) simpleGrading (1 1 1));
"""}, "diagnostics": {"fields": [{"name": "U", "unit": "m/s", "components": 3}]},
        "contract": {"title": "Synthetic channel <script>alert(1)</script>", "regime": "steady",
                     "objectives": [{"description": "Measurement only", "claim": "quantity"}],
                     "checks": [], "assumptions": [], "limitations": ["Not CFD evidence"],
                     "reference": "No physical validation."}}


def status(verdict="ACCEPT", final=True):
    return {"run_id": RUN, "state": "done", "verdict": verdict,
            "live_acceptance": verdict == "ACCEPT", "passed": 2, "total_checks": 2,
            "not_passing": [], "unresolved": [],
            "final": {"final_verdict": verdict, "live_acceptance": verdict == "ACCEPT"} if final else None,
            "runtime": {"wall_s": 30.0, "figures": ["field_U.png"], "image_id": "synthetic-image"},
            "metrics": {"quantity.cd": [2.1, "1"], "solver.final_time": [100.0, "1"]}}


def fixture_run(tmp_path, monkeypatch, state=None):
    root = tmp_path / "private/runs"
    run = root / RUN
    images = run / "output/figures"
    images.mkdir(parents=True)
    (images / "field_U.png").write_bytes(PNG)
    (run / "bundle.json").write_text(json.dumps(bundle()), encoding="utf-8")
    (run / "plan.json").write_text(json.dumps({"contract_sha256": "synthetic-contract"}), encoding="utf-8")
    calls = []

    def fake_native(cli, runs_root, operation, identifier):
        assert operation in {"verify", "status", "study-status"}
        calls.append((operation, identifier))
        return ({"run_id": RUN, "ok": True} if operation == "verify" else copy.deepcopy(state or status()))

    monkeypatch.setattr(report, "native", fake_native)
    monkeypatch.setattr(report, "resolve_cli", lambda explicit: "synthetic-cli")
    return root, run, calls


def tree_digest(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_native_renderer_embeds_summary_images_and_preserves_input_tree(tmp_path, monkeypatch):
    root, _, calls = fixture_run(tmp_path, monkeypatch)
    before = tree_digest(root)
    out = tmp_path / "reports/new"
    result = generate(out=out, root=root, cli=None, run_ids=[RUN], study_ids=[], title="Flow report")
    out = Path(result["report"]).parent
    text = (out / "report.html").read_text(encoding="utf-8")
    facts = HTMLFacts()
    facts.feed(text)
    assert facts.sections[0] == "executive-summary"
    assert any(section == "executive-summary" for section, _ in facts.images)
    assert all(image["src"].startswith("data:image/png;base64,") for _, image in facts.images)
    assert "steady iteration 100" in text and "U magnitude [m/s]" in text
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert not {"script", "iframe", "link", "object"} & set(facts.tags)
    assert "Content-Security-Policy" in text
    assert "0.5 min" in text and "not automatically its entire restart lineage" in text
    assert {op for op, _ in calls} == {"status", "verify"}
    assert tree_digest(root) == before
    assert result["presentation_only"] is True and result["solver_executed"] is False
    snapshot = json.loads((out / "evidence-snapshot.json").read_text(encoding="utf-8"))
    assert "uri" not in snapshot["runs"][0]["images"][0]
    receipt = json.loads((out / "report-receipt.json").read_text(encoding="utf-8"))
    assert receipt["report_sha256"] == report.sha(out / "report.html")


@pytest.mark.parametrize("verification,state,expected", [
    ({"ok": True}, status(), "ACCEPT"),
    ({"ok": False}, status(), "UNVERIFIED"),
    ({"ok": True}, status(final=False), "NOT FINAL"),
    ({"ok": True}, {**status(), "live_acceptance": False}, "UNVERIFIED"),
    ({"ok": True}, status("REJECT"), "REJECT"),
    ({"ok": True}, status("INCONCLUSIVE"), "INCONCLUSIVE"),
])
def test_only_verified_final_live_native_acceptance_can_be_labeled_accepted(verification, state, expected):
    assert report.final_label({"verification": verification, "status": state}) == expected


def test_separate_baseline_failure_is_not_concealed_by_accepted_members(tmp_path, monkeypatch):
    root, _, _ = fixture_run(tmp_path, monkeypatch)
    analysis = tmp_path / "separate.json"
    analysis.write_text(json.dumps({"baseline_gate_state": "FAIL", "reference_discrepancy_pct": 5.65}), encoding="utf-8")
    out = tmp_path / "report"
    result = generate(out=out, root=root, cli=None, run_ids=[RUN], study_ids=[], title="Baseline", analysis=analysis)
    out = Path(result["report"]).parent
    text = (out / "report.html").read_text(encoding="utf-8")
    assert "BASELINE ANALYSIS: FAIL" in text
    assert "not independently verified" in text and "not a new native criterion" in text
    assert "not override the baseline/reference result" in text
    assert "5.65" in text


def test_separate_pass_cannot_hide_a_native_rejection(tmp_path, monkeypatch):
    root, _, _ = fixture_run(tmp_path, monkeypatch, state=status("REJECT"))
    analysis = tmp_path / "separate.json"
    analysis.write_text(json.dumps({"baseline_gate_state": "PASS"}), encoding="utf-8")
    out = tmp_path / "report"
    result = generate(out=out, root=root, cli=None, run_ids=[RUN], study_ids=[], title="Conflicting scopes", analysis=analysis)
    out = Path(result["report"]).parent
    text = (out / "report.html").read_text(encoding="utf-8")
    opening = text.split('id="executive-summary"', 1)[1].split("</section>", 1)[0]
    assert "NATIVE RESULT: REJECT" in opening
    assert "does not override the non-accepted" in opening
    assert 'class="badge bad"' in opening


def test_missing_cost_is_not_reported_as_zero_minutes(tmp_path, monkeypatch):
    state = status()
    del state["runtime"]["wall_s"]
    root, _, _ = fixture_run(tmp_path, monkeypatch, state=state)
    out = tmp_path / "report"
    result = generate(out=out, root=root, cli=None, run_ids=[RUN], study_ids=[], title="Unknown cost")
    out = Path(result["report"]).parent
    opening = (out / "report.html").read_text(encoding="utf-8").split('id="executive-summary"', 1)[1].split("</section>", 1)[0]
    assert "Unavailable" in opening and "0.0 min" not in opening


def test_blocked_report_needs_no_runtime_and_never_fabricates_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "resolve_cli", lambda *_: pytest.fail("Blocked report must not resolve or call runtime"))
    b = tmp_path / "input.json"
    b.write_text(json.dumps(bundle()), encoding="utf-8")
    out = tmp_path / "blocked"
    result = generate(out=out, root=None, cli=None, run_ids=[], study_ids=[], title="Blocked",
                      blocked="Runtime unavailable <img src=x onerror=alert(1)>", bundle=b)
    out = Path(result["report"]).parent
    text = (out / "report.html").read_text(encoding="utf-8")
    facts = HTMLFacts()
    facts.feed(text)
    assert "BLOCKED · NOT RUN" in text and "Input schematic only" in text
    assert "not a flow solution" in text and "Not run" in text
    assert "&lt;img" in text and not facts.images
    assert report.geometry_svg({"files": {"system/blockMeshDict": "#calc malicious"}}) is None


def test_missing_visuals_are_disclosed_not_synthesized(tmp_path, monkeypatch):
    root, run, _ = fixture_run(tmp_path, monkeypatch)
    (run / "output/figures/field_U.png").unlink()
    b = bundle()
    b["files"] = {}
    (run / "bundle.json").write_text(json.dumps(b), encoding="utf-8")
    out = tmp_path / "report"
    result = generate(out=out, root=root, cli=None, run_ids=[RUN], study_ids=[], title="No image")
    out = Path(result["report"]).parent
    text = (out / "report.html").read_text(encoding="utf-8")
    assert "No native field image is available" in text
    assert "No flow visualization has been invented" in text
    assert "Illustrative figure unavailable or refused" in text


def test_output_refuses_overwrite_and_native_stores_even_without_runtime(tmp_path, monkeypatch):
    root, run, _ = fixture_run(tmp_path, monkeypatch)
    selected = report.results_policy.initialize(tmp_path, "paths-test", exact=True)
    results = Path(selected["results_root"])
    existing = results / "existing"
    existing.mkdir()
    for path in (existing, run / "new-report", root.parent / "studies/new-report"):
        with pytest.raises((ValueError, FileExistsError)):
            report.generate(project=tmp_path, results=results, out=path, root=root, cli=None,
                            run_ids=[], study_ids=[], title="X", blocked="No run")
    signed = results / "analysis/signed"
    signed.mkdir()
    (signed / "journal.jsonl").write_text("synthetic journal", encoding="utf-8")
    with pytest.raises(ValueError, match="signed native record"):
        report.generate(project=tmp_path, results=results, out=signed / "blocked-report", root=None,
                        cli=None, run_ids=[], study_ids=[], title="X", blocked="No runtime")


def test_report_api_requires_explicit_marked_project_and_rejects_source_output(tmp_path):
    results = Path(report.results_policy.initialize(tmp_path, "report-api", exact=True)["results_root"])
    with pytest.raises(TypeError):
        report.generate(out=tmp_path / "out", root=None, cli=None, run_ids=[], study_ids=[], title="No", blocked="No run")
    for bad in (tmp_path / "agents/new-report", tmp_path / "elsewhere", results / "runs/new-report"):
        with pytest.raises(ValueError):
            report.generate(project=tmp_path, results=results, out=bad, root=None, cli=None,
                            run_ids=[], study_ids=[], title="No", blocked="No run")
    assert not (tmp_path / "agents").exists()


def test_report_root_reuses_initialized_container_but_never_overwrites_files(tmp_path):
    results = Path(report.results_policy.initialize(tmp_path, "existing-root", exact=True)["results_root"])
    (results / "inputs/keep.json").write_text("original", encoding="utf-8")
    kwargs = dict(project=tmp_path, results=results, root=None, cli=None, run_ids=[], study_ids=[], title="Blocked", blocked="No run")
    record = report.generate(**kwargs)
    before = Path(record["report"]).read_bytes()
    with pytest.raises(FileExistsError):
        report.generate(**kwargs)
    assert Path(record["report"]).read_bytes() == before
    assert (results / "inputs/keep.json").read_text(encoding="utf-8") == "original"
    second = report.generate(**kwargs, out=results / "reports/revision-2")
    assert Path(second["report"]).is_relative_to(results)


@pytest.mark.parametrize("path", ["../escape.png", "/absolute.png", "bad\\name.png", "https:bad.png"])
def test_images_refuse_path_traversal(tmp_path, path):
    with pytest.raises(ValueError):
        report.inside(tmp_path, path)


def test_arbitrary_svg_or_oversized_images_are_never_embedded(tmp_path):
    svg = tmp_path / "figure.png"
    svg.write_text('<svg onload="x"/>', encoding="utf-8")
    with pytest.raises(ValueError, match="PNG"):
        report.png_asset(svg, "unsafe", "synthetic")
    with svg.open("wb") as stream:
        stream.truncate(report.MAX_IMAGE + 1)
    with pytest.raises(ValueError, match="8 MiB"):
        report.png_asset(svg, "large", "synthetic")


def test_native_command_allowlist_and_store_environment_are_read_only(tmp_path, monkeypatch):
    invoked = []

    def fake_run(argv, **kwargs):
        invoked.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True}), stderr="")

    monkeypatch.setattr(report.subprocess, "run", fake_run)
    assert report.native("approved-cli", tmp_path, "verify", RUN)["ok"]
    argv, options = invoked[0]
    assert argv == ["approved-cli", "verify", RUN]
    assert options["env"]["DISCOVERY_PHYSICS_RUNS"] == str(tmp_path)
    for operation in ("execute", "finalize", "recover", "reassess", "study-assess", "prepare"):
        with pytest.raises(ValueError):
            report.native("approved-cli", tmp_path, operation, RUN)
    assert len(invoked) == 1


def test_study_selects_verified_leaf_and_hides_stale_assessment(tmp_path, monkeypatch):
    root, _, _ = fixture_run(tmp_path, monkeypatch)
    folder = root.parent / "studies" / STUDY
    folder.mkdir(parents=True)
    (folder / "study.json").write_text(json.dumps({"title": "Synthetic study"}), encoding="utf-8")
    (folder / "journal.jsonl").write_text(json.dumps({"event": "study_assessed", "record": {
        "verdict": "ACCEPT", "members": {"fine": {"leaf_run": "old-run"}}}}) + "\n", encoding="utf-8")

    def fake_native(cli, runs_root, op, identifier):
        if op == "study-status":
            return {"members": {"fine": {"leaf_run": RUN}}}
        return {"ok": True} if op == "verify" else status()

    monkeypatch.setattr(report, "native", fake_native)
    result = report.collect("synthetic-cli", root, [], [STUDY])
    assert result["runs"][0]["run_id"] == RUN
    assert result["studies"][0]["assessment"] is None