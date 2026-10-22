"""Focused tests for the agent-removal impact gate."""

import json
import io
import subprocess
import sys
import urllib.error
from urllib.parse import urlsplit, parse_qs

import pytest

from pathlib import Path

import check_agent_removal_impact as gate
from agent_removal_report import validate_report
from check_agent_removal_impact import (
    get_base_registry_paths,
    get_head_registry_paths,
)

pytestmark = pytest.mark.usefixtures("removal_offline")


def make_catalog(root: Path, resolution: str = "blocked") -> tuple[Path, Path]:
    trusted, head = root / "trusted", root / "pr"
    _write_base_registry(trusted, ["agents/old", "agents/kept"])
    agent = head / "agents" / "kept"
    agent.mkdir(parents=True)
    (agent / "metadata.yaml").write_text("name: kept\n", encoding="utf-8")
    if resolution in {"renamed_agent", "rename_replacement"}:
        renamed = head / "agents" / "renamed"
        renamed.mkdir()
        (renamed / "metadata.yaml").write_text("name: renamed\n", encoding="utf-8")
    if resolution == "no_removal":
        old = head / "agents" / "old"
        old.mkdir()
        (old / "metadata.yaml").write_text("name: old\n", encoding="utf-8")
    if resolution != "deleted_kit":
        kit = head / "starter-kits" / "example" / "kit.json"
        kit.parent.mkdir(parents=True)
        kit.write_text(json.dumps({
            "lifecycle": "archived" if resolution == "archived" else "active",
            "agentRefs": [{
                "ref": (
                    "agents/kept" if resolution == "replacement" else
                    "agents/renamed" if resolution == "rename_replacement" else "agents/old"
                ),
                **({} if resolution == "flag_removed" else {"required": resolution != "optional"}),
            }],
        }), encoding="utf-8")
    return trusted, head


def invoke_gate(monkeypatch, trusted, head, *, extra=(), structured=True):
    report_path = head.parent / "report.json"
    args = [
        "check_agent_removal_impact.py", "--repo-root", str(head),
        "--base-registry-root", str(trusted), "--base-sha", "b" * 40,
        "--repo", "microsoft/discovery", "--pr-number", "17",
    ]
    if structured:
        args.extend(["--report-json", str(report_path)])
    monkeypatch.setattr(sys, "argv", args + list(extra))
    with pytest.raises(SystemExit) as exited:
        gate.main()
    return exited.value.code, json.loads(report_path.read_bytes()) if structured else None


class RecordingHTTP:
    def __init__(self, *, permission="write", missing_label=False, event="labeled", broken_page=False):
        self.permission = permission
        self.missing_label = missing_label
        self.event = event
        self.broken_page = broken_page
        self.calls = []

    def __call__(self, request):
        assert request.get_method() == "GET"
        assert request.get_header("Authorization") == "Bearer fixture-token"
        url = urlsplit(request.full_url)
        assert url.scheme == "https" and url.netloc == "api.github.com"
        self.calls.append(request.full_url)
        if url.path.endswith("/labels"):
            data = [] if self.missing_label else [{"name": "starter-kit-impact-approved"}]
        elif url.path.endswith("/events"):
            page = parse_qs(url.query)["page"][0]
            if page == "1":
                data = [{"event": "commented"}] * 100
            elif self.broken_page:
                raise urllib.error.URLError("incomplete event history")
            else:
                data = [{
                    "event": self.event, "label": {"name": "starter-kit-impact-approved"},
                    "actor": {"login": "maintainer"},
                }]
        elif url.path.endswith("/permission"):
            if self.permission == "unavailable":
                raise urllib.error.URLError("permission unavailable")
            data = {"permission": self.permission}
        else:
            pytest.fail(f"Unexpected validator API path: {url.path}")
        return io.BytesIO(json.dumps(data).encode())


def test_head_registry_paths_come_from_agent_metadata(tmp_path: Path):
    (tmp_path / "agents" / "kept").mkdir(parents=True)
    (tmp_path / "agents" / "kept" / "metadata.yaml").write_text(
        "name: kept\n",
        encoding="utf-8",
    )
    (tmp_path / "agents" / "incomplete").mkdir()
    (tmp_path / "agents" / "README.md").write_text("Agents\n", encoding="utf-8")

    assert get_head_registry_paths(tmp_path) == {"agents/kept"}


def test_malformed_metadata_is_treated_as_absent(tmp_path: Path):
    # A folder whose metadata would be rejected by registry generation (no
    # name) must not be counted as present, so it cannot mask a real removal.
    (tmp_path / "agents" / "nameless").mkdir(parents=True)
    (tmp_path / "agents" / "nameless" / "metadata.yaml").write_text(
        "description: no name here\n",
        encoding="utf-8",
    )
    (tmp_path / "agents" / "broken").mkdir()
    (tmp_path / "agents" / "broken" / "metadata.yaml").write_text(
        "name: [unterminated\n",
        encoding="utf-8",
    )

    assert get_head_registry_paths(tmp_path) == set()


def test_head_registry_paths_tolerate_missing_agents_directory(tmp_path: Path):
    assert get_head_registry_paths(tmp_path) == set()


def _write_base_registry(root: Path, agent_paths: list[str]) -> None:
    registry = {
        "entries": [{"type": "agent", "path": p} for p in agent_paths]
    }
    dest = root / ".auto-registry" / "agent-registry.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(registry), encoding="utf-8")


def test_base_registry_read_from_trusted_root(tmp_path: Path):
    """When a base-registry root is given, agent paths come from the committed
    registry on disk — no git access, which forks often cannot satisfy."""
    trusted = tmp_path / "trusted"
    _write_base_registry(trusted, ["agents/alpha", "agents/beta"])

    paths = get_base_registry_paths(
        tmp_path / "pr", "deadbeef", base_registry_root=trusted
    )
    assert paths == {"agents/alpha", "agents/beta"}


def test_missing_base_registry_is_blocking(tmp_path: Path):
    """A missing base registry must raise, not silently return an empty set that
    would hide every removal."""
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    with pytest.raises(RuntimeError):
        get_base_registry_paths(
            tmp_path / "pr", "deadbeef", base_registry_root=trusted
        )


def test_corrupt_base_registry_is_blocking(tmp_path: Path):
    """A base registry that exists but cannot be parsed must raise."""
    trusted = tmp_path / "trusted"
    dest = trusted / ".auto-registry" / "agent-registry.json"
    dest.parent.mkdir(parents=True)
    dest.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(RuntimeError):
        get_base_registry_paths(
            tmp_path / "pr", "deadbeef", base_registry_root=trusted
        )


@pytest.mark.parametrize("resolution,expected", [
    ("blocked", "blocked"), ("no_removal", "success"), ("deleted_kit", "success"),
    ("archived", "success"), ("optional", "success"), ("flag_removed", "success"),
    ("replacement", "success"),
    ("renamed_agent", "blocked"), ("rename_replacement", "success"),
])
def test_real_gate_decisions_and_report_contract(tmp_path, monkeypatch, resolution, expected):
    trusted, head = make_catalog(tmp_path, resolution)
    code, report = invoke_gate(monkeypatch, trusted, head)
    assert validate_report(report) is report
    assert report["outcome"] == expected
    assert code == report["exit_code"] == (1 if expected == "blocked" else 0)
    if expected == "blocked":
        assert report["removed_paths"] == ["agents/old"]
        assert report["impacted_kits"] == [{
            "path": "starter-kits/example", "required_refs": ["agents/old"],
        }]


@pytest.mark.parametrize("problem", ["missing", "json", "shape", "head", "metadata_io", "kit", "checkout"])
def test_fatal_input_failures_are_explicit_errors(tmp_path, monkeypatch, problem):
    trusted, head = make_catalog(tmp_path)
    registry = trusted / ".auto-registry" / "agent-registry.json"
    if problem == "missing":
        registry.unlink()
    elif problem in {"json", "shape"}:
        registry.write_text("{" if problem == "json" else '{"entries": [42]}', encoding="utf-8")
    elif problem in {"head", "metadata_io"}:
        def fail(*args):
            raise PermissionError("fixture read denied")
        if problem == "head":
            monkeypatch.setattr(gate, "get_head_registry_paths", fail)
        else:
            monkeypatch.setattr(gate.update_registry, "build_entry", fail)
    elif problem == "kit":
        (head / "starter-kits" / "example" / "kit.json").write_text("{", encoding="utf-8")
    else:
        head = tmp_path / "missing-checkout"
    code, report = invoke_gate(monkeypatch, trusted, head)
    assert code == 1 and report["outcome"] == "error" and report["issues"]
    validate_report(report)


@pytest.mark.parametrize("metadata", ["description: nameless\n", "name: [broken\n"])
def test_invalid_metadata_cannot_mask_a_removal(tmp_path, monkeypatch, metadata):
    trusted, head = make_catalog(tmp_path)
    old = head / "agents" / "old"
    old.mkdir()
    (old / "metadata.yaml").write_text(metadata, encoding="utf-8")
    code, report = invoke_gate(monkeypatch, trusted, head)
    assert code == 1 and report["outcome"] == "blocked"


@pytest.mark.parametrize("permission", ["admin", "maintain", "write", "read", "none", "unavailable"])
def test_override_verifies_current_permission_with_gets_only(tmp_path, monkeypatch, permission):
    trusted, head = make_catalog(tmp_path)
    http = RecordingHTTP(permission=permission)
    monkeypatch.setattr(gate.urllib.request, "urlopen", http)
    code, report = invoke_gate(monkeypatch, trusted, head, extra=["--github-token", "fixture-token"])
    approved = permission in {"admin", "maintain", "write"}
    assert code == (0 if approved else 1)
    assert report["override"]["approved"] is approved
    assert report["outcome"] == ("success" if approved else "blocked")
    assert any("page=2" in call for call in http.calls)
    assert "permission" in report["override"]["reason"]


@pytest.mark.parametrize("problem", ["missing_label", "unlabeled", "broken_page", "fork"])
def test_override_fails_closed_and_forks_remain_restricted(tmp_path, monkeypatch, problem):
    trusted, head = make_catalog(tmp_path)
    http = RecordingHTTP(
        missing_label=problem == "missing_label",
        event="unlabeled" if problem == "unlabeled" else "labeled",
        broken_page=problem == "broken_page",
    )
    monkeypatch.setattr(gate.urllib.request, "urlopen", http)
    extra = ["--github-token", "fixture-token"] + (["--is-fork"] if problem == "fork" else [])
    code, report = invoke_gate(monkeypatch, trusted, head, extra=extra)
    assert code == 1 and report["outcome"] == "blocked"
    assert not report["override"]["approved"] and report["override"]["reason"]
    if problem == "fork":
        assert not http.calls


@pytest.mark.parametrize("resolution,expected", [("blocked", 1), ("replacement", 0)])
def test_legacy_and_shadow_callers_retain_exit_codes(tmp_path, monkeypatch, resolution, expected):
    trusted, head = make_catalog(tmp_path, resolution)
    code, report = invoke_gate(monkeypatch, trusted, head, structured=False)
    assert code == expected and report is None
    assert not (tmp_path / "report.json").exists()

    raw = (trusted / ".auto-registry" / "agent-registry.json").read_text(encoding="utf-8")
    def git_show(command, **kwargs):
        assert command == ["git", "show", "base:.auto-registry/agent-registry.json"]
        return subprocess.CompletedProcess(command, 0, stdout=raw)
    monkeypatch.setattr(gate.subprocess, "run", git_show)
    assert gate.evaluate(head, "base")["exit_code"] == expected


@pytest.mark.parametrize("resolution,expected", [("blocked", 1), ("replacement", 0)])
def test_executable_cli_emits_real_exit_and_report_bytes(tmp_path, resolution, expected):
    trusted, head = make_catalog(tmp_path, resolution)
    path = tmp_path / "result.json"
    process = subprocess.run([
        sys.executable, str(Path(gate.__file__)), "--repo-root", str(head),
        "--base-registry-root", str(trusted), "--base-sha", "base",
        "--report-json", str(path),
    ], capture_output=True, text=True)
    assert process.returncode == expected, process.stderr
    assert validate_report(json.loads(path.read_bytes()))["exit_code"] == expected


def test_report_write_failure_is_not_success(tmp_path, monkeypatch, capsys):
    trusted, head = make_catalog(tmp_path, "replacement")
    (tmp_path / "report.json").mkdir()
    monkeypatch.setattr(sys, "argv", [
        "gate", "--repo-root", str(head), "--base-registry-root", str(trusted),
        "--base-sha", "base", "--report-json", str(tmp_path / "report.json"),
    ])
    with pytest.raises(SystemExit) as exited:
        gate.main()
    assert exited.value.code == 1
    assert "Could not write removal report" in capsys.readouterr().err


def test_legacy_token_invocation_is_get_only_and_never_posts(tmp_path, monkeypatch):
    trusted, head = make_catalog(tmp_path)
    http = RecordingHTTP(permission="read")
    monkeypatch.setattr(gate.urllib.request, "urlopen", http)
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-token")
    code, report = invoke_gate(monkeypatch, trusted, head, structured=False)
    assert code == 1 and report is None and http.calls
    assert not hasattr(gate, "post_pr_comment")