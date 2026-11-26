"""Behavioral contracts for committed generated artifacts."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import registry_refresh
from jsonschema import Draft7Validator, FormatChecker
from referencing import Registry, Resource

from generate_baseline import (
    BASELINE_PATH,
    check_no_growth,
    load_existing,
    write_baseline,
)
from update_registry import build_entry, scan_repo
from update_starter_kits_registry import (
    build_kit_registry_entry,
    build_registry_path_set,
    compute_availability,
    get_kit_dirs,
    get_kit_relpath,
    load_json,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / ".github" / "scripts"
SCHEMA_DIR = REPO_ROOT / "docs" / "schemas"


@pytest.fixture
def registry_repo(tmp_path: Path) -> Path:
    snapshots = {
        "agent-registry.json": {
            "version": "1.0.0", "generated_at": "2026-01-01T00:00:00Z",
            "entries": [{"path": "agents/demo", "version": "1.0.0"}],
        },
        "starter-kit-registry.json": {
            "schemaVersion": "1.0.0", "generatedAt": "2026-01-01T00:00:00Z",
            "commitSha": "old-source",
            "kits": [{"kitPath": "starter-kits/demo", "availability": "healthy",
                      "computedAt": "2026-01-01T00:00:00Z"}],
        },
        "agent-tags.json": {
            "schemaVersion": "1.0.0", "count": 1,
            "agents": [{"path": "agents/demo", "computed_tags": ["tier:bronze"]}],
        },
    }
    for name, payload in snapshots.items():
        write(tmp_path, f".auto-registry/{name}", (json.dumps(payload) + "\n").encode())
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "add", ".auto-registry"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "commit", "-qm", "Published snapshot"],
        cwd=tmp_path, check=True,
    )
    return tmp_path


def registry_cli(monkeypatch, repo: Path) -> Path:
    output = repo / "github-output.txt"
    monkeypatch.setattr(sys, "argv", [
        "registry_refresh.py", "--repo-root", str(repo),
        "--repository", "microsoft/discovery",
    ])
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(repo / "summary.md"))
    return output


def test_registry_refresh_preserves_metadata_only_snapshots(registry_repo, monkeypatch):
    output = registry_cli(monkeypatch, registry_repo)
    previous = {
        relative: (registry_repo / relative).read_bytes()
        for relative in registry_refresh.REGISTRY_COLLECTIONS
    }
    for relative in previous:
        payload = json.loads(previous[relative])
        if "generated_at" in payload:
            payload["generated_at"] = "2026-11-18T00:00:00Z"
        if "kits" in payload:
            payload["generatedAt"] = "2026-11-18T00:00:00Z"
            payload["commitSha"] = "unrelated-main-commit"
            payload["kits"][0]["computedAt"] = "2026-11-18T00:00:00Z"
        write(registry_repo, relative, json.dumps(payload, indent=2))
    monkeypatch.setattr(
        registry_refresh, "existing_refresh_prs",
        lambda repository: pytest.fail("A semantic no-op must not query or create PRs"),
    )

    assert registry_refresh.main() == 0
    assert output.read_text(encoding="utf-8") == "publish=false\n"
    assert {
        relative: (registry_repo / relative).read_bytes()
        for relative in previous
    } == previous


@pytest.mark.parametrize(("filename", "collection", "field", "value"), [
    ("agent-registry.json", "entries", "version", "2.0.0"),
    ("agent-registry.json", None, "version", "2.0.0"),
    ("starter-kit-registry.json", "kits", "availability", "degraded"),
    ("agent-tags.json", "agents", "computed_tags", ["tier:silver"]),
])
def test_registry_refresh_detects_real_payload_changes(
    registry_repo, filename, collection, field, value,
):
    relative = f".auto-registry/{filename}"
    payload = json.loads((registry_repo / relative).read_bytes())
    target = payload[collection][0] if collection else payload
    target[field] = value
    write(registry_repo, relative, json.dumps(payload))

    assert registry_refresh.prepare_changes(registry_repo) == [relative]
    current = json.loads((registry_repo / relative).read_bytes())
    target = current[collection][0] if collection else current
    assert target[field] == value


def test_registry_refresh_detects_untracked_bootstrap_outputs(registry_repo):
    subprocess.run(
        ["git", "rm", "--cached", "-r", ".auto-registry"],
        cwd=registry_repo, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "commit", "-qm", "Before first publication"],
        cwd=registry_repo, check=True,
    )

    assert registry_refresh.prepare_changes(registry_repo) == list(
        registry_refresh.REGISTRY_COLLECTIONS
    )


@pytest.mark.parametrize(("existing", "publish"), [([], "true"), ([77], "false")])
def test_registry_refresh_queues_changes_without_rewriting_reviewed_prs(
    registry_repo, monkeypatch, existing, publish,
):
    output = registry_cli(monkeypatch, registry_repo)
    relative = ".auto-registry/agent-registry.json"
    payload = json.loads((registry_repo / relative).read_bytes())
    payload["entries"].append({"path": "agents/new"})
    write(registry_repo, relative, json.dumps(payload))
    calls = []

    def lookup(repository):
        calls.append(repository)
        return existing

    monkeypatch.setattr(registry_refresh, "existing_refresh_prs", lookup)
    assert registry_refresh.main() == 0
    assert calls == ["microsoft/discovery"]
    assert output.read_text(encoding="utf-8") == f"publish={publish}\n"
    assert subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=registry_repo,
    ).returncode == 0
    summary = (registry_repo / "summary.md").read_text(encoding="utf-8")
    if existing:
        assert "https://github.com/microsoft/discovery/pull/77" in summary
        assert "will not be rewritten" in summary


def test_registry_refresh_lookup_requires_trusted_same_repository_pr(monkeypatch):
    def pr(number, author="discovery-registry-bot[bot]",
           repository="microsoft/discovery", ref="chore/registry-refresh-123"):
        return {
            "number": number, "state": "open", "base": {"ref": "main"},
            "head": {"ref": ref, "repo": {"full_name": repository}},
            "user": {"login": author},
        }

    pages = [
        [pr(1, author="octocat"), pr(2, repository="octocat/discovery")],
        [pr(3, ref="feature/update"), pr(4)],
    ]
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(pages))

    monkeypatch.setattr(registry_refresh.subprocess, "run", run)
    assert registry_refresh.existing_refresh_prs("microsoft/discovery") == [4]
    assert calls == [[
        "gh", "api",
        "repos/microsoft/discovery/pulls?state=open&base=main&per_page=100",
        "--paginate", "--slurp",
    ]]


def test_registry_refresh_api_failure_does_not_permit_publication(
    registry_repo, monkeypatch, capsys,
):
    output = registry_cli(monkeypatch, registry_repo)
    relative = ".auto-registry/agent-tags.json"
    payload = json.loads((registry_repo / relative).read_bytes())
    payload["agents"][0]["computed_tags"] = ["tier:gold"]
    write(registry_repo, relative, json.dumps(payload))

    def unavailable(repository):
        raise subprocess.CalledProcessError(1, ["gh", "api"], stderr="HTTP 403")

    monkeypatch.setattr(registry_refresh, "existing_refresh_prs", unavailable)
    assert registry_refresh.main() == 1
    assert not output.exists()
    assert "HTTP 403" in capsys.readouterr().err


def test_registry_refresh_rejects_malformed_published_snapshot(registry_repo):
    relative = ".auto-registry/agent-registry.json"
    generated = (registry_repo / relative).read_bytes()
    write(registry_repo, relative, "{}")
    subprocess.run(["git", "add", relative], cwd=registry_repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "commit", "-qm", "Invalid snapshot"],
        cwd=registry_repo, check=True,
    )
    write(registry_repo, relative, generated)

    with pytest.raises(ValueError, match="array of objects"):
        registry_refresh.prepare_changes(registry_repo)


def baseline_entry(rule_id: str, file: str) -> dict[str, str]:
    return {
        "rule_id": rule_id,
        "file": file,
        "owner": "Discovery catalog CODEOWNERS",
        "tracking_ref": "docs/validation-baseline-debt.md#test-entry",
        "remove_by": "2099-12-31",
    }


def write_baseline_payload(repo: Path, entries: list[dict[str, str]]) -> None:
    write(
        repo,
        BASELINE_PATH.as_posix(),
        json.dumps({"count": len(entries), "violations": entries}),
    )

AGENT_METADATA = """\
name: {name}
version: {version}
publisher:
    name: Example Publisher
description: Generated registry test agent.
associated_tools:
    - agents/{folder}/tools/example
supported_regions:
    - eastus
tags:
    - chemistry
"""


def run_script(script: str, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / script),
            "--repo-root",
            str(repo),
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def write(repo: Path, relative: str, content: bytes | str) -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def write_agent(repo: Path, folder: str, *, name: str | None = None,
                version: str = "1.2.3") -> Path:
    agent_dir = repo / "agents" / folder
    write(
        repo,
        f"agents/{folder}/metadata.yaml",
        AGENT_METADATA.format(name=name or folder, version=version, folder=folder),
    )
    write(
        repo,
        f"agents/{folder}/agent.yaml",
        "tools:\n  - name: web_search\n  - mcp\n  - {}\n",
    )
    return agent_dir


def seed_policy(repo: Path) -> None:
    shutil.copytree(REPO_ROOT / ".github" / "policy", repo / ".github" / "policy")


def schema_validator(schema_name: str) -> Draft7Validator:
    schemas = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in SCHEMA_DIR.glob("*schema*.json")
    }
    registry = Registry().with_resources(
        (name, Resource.from_contents(schema)) for name, schema in schemas.items()
    )
    return Draft7Validator(
        schemas[schema_name], registry=registry, format_checker=FormatChecker()
    )


def test_baseline_writer_deduplicates_and_sorts_entries(tmp_path: Path):
    write_baseline_payload(
        tmp_path,
        [
            baseline_entry("POL-015", "agents/zeta/Dockerfile"),
            baseline_entry("POL-008", "agents/alpha/blob.bin"),
        ],
    )
    write_baseline(
        tmp_path,
        [
            {"rule_id": "POL-015", "file": "agents/zeta/Dockerfile"},
            {"rule_id": "POL-008", "file": "agents/alpha/blob.bin"},
            {"rule_id": "POL-015", "file": "agents/zeta/Dockerfile"},
        ],
    )

    payload = json.loads((tmp_path / BASELINE_PATH).read_text(encoding="utf-8"))
    assert payload["count"] == 2
    assert payload["violations"] == [
        baseline_entry("POL-008", "agents/alpha/blob.bin"),
        baseline_entry("POL-015", "agents/zeta/Dockerfile"),
    ]


def test_baseline_writer_rejects_new_entries_without_governance(tmp_path: Path):
    with pytest.raises(ValueError, match="baseline growth is prohibited"):
        write_baseline(
            tmp_path,
            [{"rule_id": "POL-008", "file": "agents/new/blob.bin"}],
        )


@pytest.mark.parametrize(
    "payload",
    [
        "{not-json",
        json.dumps([]),
        json.dumps({"violations": {}}),
        json.dumps({"violations": [{"rule_id": "POL-008"}]}),
        json.dumps(
            {
                "violations": [
                    {"rule_id": "POL-008", "file": "agents/demo/blob.bin"},
                    {"rule_id": "POL-008", "file": "agents/demo/blob.bin"},
                ]
            }
        ),
    ],
)
def test_baseline_loader_rejects_malformed_state(tmp_path: Path, payload: str):
    path = tmp_path / BASELINE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError):
        load_existing(tmp_path)


def test_baseline_check_fails_closed_on_corrupt_state(tmp_path: Path):
    seed_policy(tmp_path)
    path = tmp_path / BASELINE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")

    result = run_script("generate_baseline.py", tmp_path, "--check")

    assert result.returncode == 1
    assert "BASELINE ERROR" in result.stderr


def test_baseline_cli_detects_added_and_removed_violations_and_reports(
    tmp_path: Path,
):
    seed_policy(tmp_path)
    write_agent(tmp_path, "demo")
    original = write(
        tmp_path,
        "agents/demo/tools/example/original.txt",
        b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 56,
    )
    write_baseline_payload(
        tmp_path,
        [
            baseline_entry("POL-008", "agents/demo/agent.yaml"),
            baseline_entry("POL-008", "agents/demo/metadata.yaml"),
            baseline_entry(
                "POL-008", "agents/demo/tools/example/original.txt"
            ),
            # Linux libmagic also reaches the Unicode-safety rule for this
            # synthetic ELF payload. Windows stops at the binary classifier,
            # so the writer simply removes this unused entry there.
            baseline_entry(
                "POL-020", "agents/demo/tools/example/original.txt"
            ),
        ],
    )

    generated = run_script("generate_baseline.py", tmp_path)
    current = run_script("generate_baseline.py", tmp_path, "--check")
    report = run_script("generate_baseline.py", tmp_path, "--report")

    assert generated.returncode == current.returncode == report.returncode == 0
    assert "violation(s)" in report.stdout

    added_path = write(
        tmp_path,
        "agents/demo/tools/example/added.txt",
        b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 56,
    )
    added = run_script("generate_baseline.py", tmp_path, "--check")
    assert added.returncode == 1
    assert "agents/demo/tools/example/added.txt" in added.stdout

    added_path.unlink()
    original.unlink()
    removed = run_script("generate_baseline.py", tmp_path, "--check")
    assert removed.returncode == 1
    assert "baselined violation(s) have been fixed" in removed.stdout


def test_baseline_no_growth_compares_with_git_base(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
    )
    original = baseline_entry("POL-015", "agents/demo/original.html")
    write_baseline_payload(tmp_path, [original])
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base_ref = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert check_no_growth(tmp_path, base_ref) == []

    added = baseline_entry("POL-016", "agents/demo/new.png")
    write_baseline_payload(tmp_path, [original, added])
    assert check_no_growth(tmp_path, base_ref) == [
        ("POL-016", "agents/demo/new.png")
    ]


def test_baseline_no_growth_allows_one_time_governed_bootstrap(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
    )
    write(tmp_path, "README.md", "base\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base_ref = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    write_baseline_payload(
        tmp_path,
        [baseline_entry("POL-015", "agents/demo/original.html")],
    )

    assert check_no_growth(tmp_path, base_ref) == []


def test_rule_docs_cli_is_deterministic_and_detects_missing_or_stale_output(
    tmp_path: Path,
):
    generated = run_script("generate_rule_docs.py", tmp_path)
    path = tmp_path / "docs" / "validation-rules.md"
    first_content = path.read_text(encoding="utf-8")
    regenerated = run_script("generate_rule_docs.py", tmp_path)

    assert generated.returncode == regenerated.returncode == 0
    assert path.read_text(encoding="utf-8") == first_content
    rule_ids = [
        line.removeprefix("## ")
        for line in first_content.splitlines()
        if line.startswith("## ") and line.removeprefix("## ").split("-")[-1].isdigit()
    ]
    assert rule_ids == sorted(rule_ids)
    assert len(rule_ids) == len(set(rule_ids))
    assert run_script("generate_rule_docs.py", tmp_path, "--check").returncode == 0

    path.write_text(first_content + "stale\n", encoding="utf-8")
    stale = run_script("generate_rule_docs.py", tmp_path, "--check")
    assert stale.returncode == 1
    assert "out of date" in stale.stderr

    path.unlink()
    missing = run_script("generate_rule_docs.py", tmp_path, "--check")
    assert missing.returncode == 1
    assert "out of date" in missing.stderr


def test_computed_tags_cli_detects_drift_and_report_has_no_side_effect(
    tmp_path: Path,
):
    seed_policy(tmp_path)
    write_agent(tmp_path, "demo")

    missing = run_script("compute_tags.py", tmp_path, "--check")
    generated = run_script("compute_tags.py", tmp_path)
    output = tmp_path / ".auto-registry" / "agent-tags.json"
    payload = json.loads(output.read_text(encoding="utf-8"))
    current = run_script("compute_tags.py", tmp_path, "--check")

    assert missing.returncode == 1
    assert generated.returncode == current.returncode == 0
    assert payload["count"] == 1
    assert payload["agents"][0]["path"] == "agents/demo"

    output.write_text("{}\n", encoding="utf-8")
    stale = run_script("compute_tags.py", tmp_path, "--check")
    report = run_script("compute_tags.py", tmp_path, "--report")

    assert stale.returncode == 1
    assert "out of date" in stale.stderr
    assert report.returncode == 0
    assert "1 agent(s) tagged." in report.stdout
    assert output.read_text(encoding="utf-8") == "{}\n"


def test_agent_registry_entry_extracts_public_fields(tmp_path: Path):
    agent_dir = write_agent(tmp_path, "demo")

    entry = build_entry(str(agent_dir), "agents/demo", "agent")

    assert entry == {
        "name": "demo",
        "type": "agent",
        "publisher_name": "Example Publisher",
        "path": "agents/demo",
        "version": "1.2.3",
        "associated_tools": ["agents/demo/tools/example"],
        "foundry_tools": ["web_search", "mcp"],
        "supported_regions": ["eastus"],
        "description": "Generated registry test agent.",
        "tags": ["chemistry"],
    }


@pytest.mark.parametrize("version", ["", "v1.2.3", "1.2", "not-semver"])
def test_agent_registry_normalizes_invalid_versions(tmp_path: Path, version: str):
    agent_dir = write_agent(tmp_path, "demo", version=version)

    assert build_entry(str(agent_dir), "agents/demo", "agent")["version"] == "0.0.0"


def test_agent_registry_scan_is_sorted_and_skips_non_agents(tmp_path: Path):
    write_agent(tmp_path, "zeta")
    write_agent(tmp_path, "alpha")
    write(tmp_path, "agents/notes/README.md", "# Not an agent\n")

    entries = scan_repo(str(tmp_path))

    assert [entry["path"] for entry in entries] == ["agents/alpha", "agents/zeta"]


@pytest.mark.parametrize("metadata", ["name: [", "- not\n- a\n- mapping\n"])
def test_agent_registry_cli_rejects_malformed_metadata(tmp_path: Path, metadata: str):
    write(tmp_path, "agents/broken/metadata.yaml", metadata)
    output = tmp_path / ".auto-registry" / "agent-registry.json"

    result = run_script(
        "update_registry.py", tmp_path, "--output", str(output)
    )

    assert result.returncode == 1
    assert "ERROR:" in result.stderr
    assert "metadata.yaml" in result.stderr
    assert not output.exists()


def test_agent_registry_cli_is_stable_removes_stale_entries_and_matches_schema(
    tmp_path: Path,
):
    write_agent(tmp_path, "zeta")
    write_agent(tmp_path, "alpha")
    output = tmp_path / ".auto-registry" / "agent-registry.json"
    output.parent.mkdir(parents=True)
    output.write_text(
        json.dumps({"entries": [{"path": "agents/removed"}]}),
        encoding="utf-8",
    )

    first = run_script("update_registry.py", tmp_path, "--output", str(output))
    first_payload = json.loads(output.read_text(encoding="utf-8"))
    second = run_script("update_registry.py", tmp_path, "--output", str(output))
    second_payload = json.loads(output.read_text(encoding="utf-8"))

    assert first.returncode == second.returncode == 0
    assert "- removed: agents/removed" in first.stdout
    assert [entry["path"] for entry in first_payload["entries"]] == [
        "agents/alpha",
        "agents/zeta",
    ]
    assert first_payload["entries"] == second_payload["entries"]
    errors = list(schema_validator("registry-schema.json").iter_errors(second_payload))
    assert not errors, [error.message for error in errors]


@pytest.mark.parametrize(
    ("lifecycle", "required", "present", "expected_availability", "expected_missing"),
    [
        ("active", True, False, "degraded", ["agents/demo"]),
        ("active", False, False, "healthy", ["agents/demo"]),
        ("active", True, True, "healthy", []),
        ("archived", True, False, "healthy", ["agents/demo"]),
    ],
)
def test_starter_kit_availability_contract(
    lifecycle: str,
    required: bool,
    present: bool,
    expected_availability: str,
    expected_missing: list[str],
):
    manifest = {
        "lifecycle": lifecycle,
        "agentRefs": [{"ref": "agents/demo", "required": required}],
    }
    registry_paths = {"agents/demo"} if present else set()

    assert compute_availability(manifest, registry_paths) == (
        expected_availability,
        expected_missing,
    )


def test_starter_kit_entry_enriches_present_agents_without_mutating_manifest(
    tmp_path: Path,
):
    write_agent(tmp_path, "demo")
    write(tmp_path, "agents/demo/agent.yaml", "displayName: Demo Agent\n")
    manifest = {
        "name": "demo-kit",
        "lifecycle": "active",
        "agentRefs": [
            {"ref": "agents/demo", "role": "primary", "required": True},
            {"ref": "agents/missing", "role": "supporting", "required": False},
        ],
    }

    entry = build_kit_registry_entry(
        manifest,
        tmp_path / "starter-kits" / "demo-kit",
        "demo-kit",
        tmp_path,
        {"agents/demo"},
        "2026-01-02T03:04:05Z",
    )

    assert "agentMeta" not in manifest["agentRefs"][0]
    assert entry["agentRefs"][0]["agentMeta"] == {
        "name": "demo",
        "displayName": "Demo Agent",
        "version": "1.2.3",
        "tags": ["chemistry"],
        "description": "Generated registry test agent.",
    }
    assert "agentMeta" not in entry["agentRefs"][1]
    assert entry["availability"] == "healthy"
    assert entry["missingAgents"] == ["agents/missing"]
    assert entry["computedAt"] == "2026-01-02T03:04:05Z"
    assert entry["kitPath"] == "starter-kits/demo-kit"


def test_starter_kit_discovery_is_sorted_and_ignores_directories_without_manifest(
    tmp_path: Path,
):
    write(tmp_path, "starter-kits/zeta/kit.json", "{}")
    write(tmp_path, "starter-kits/alpha/kit.json", "{}")
    write(tmp_path, "starter-kits/notes/README.md", "# Notes\n")

    directories = get_kit_dirs(tmp_path)

    assert [get_kit_relpath(tmp_path, path) for path in directories] == [
        "alpha",
        "zeta",
    ]


@pytest.mark.parametrize(
    ("registry_content", "message"),
    [
        ("{not-json", "invalid agent registry"),
        (json.dumps([]), "entries"),
        (json.dumps({"entries": {}}), "entries"),
        (json.dumps({"entries": ["bad"]}), "entries[0]"),
        (json.dumps({"entries": [{"type": "agent"}]}), "requires a path"),
    ],
)
def test_starter_kit_cli_rejects_corrupt_agent_registry(
    tmp_path: Path, registry_content: str, message: str
):
    write(tmp_path, ".auto-registry/agent-registry.json", registry_content)

    result = run_script("update_starter_kits_registry.py", tmp_path)

    assert result.returncode == 1
    assert message in result.stderr
    assert "Traceback" not in result.stderr


def test_starter_kit_cli_requires_agent_registry(tmp_path: Path):
    result = run_script("update_starter_kits_registry.py", tmp_path)

    assert result.returncode == 1
    assert "agent-registry.json not found" in result.stderr


def test_starter_kit_cli_reports_malformed_kit_without_partial_output(tmp_path: Path):
    write(tmp_path, ".auto-registry/agent-registry.json", json.dumps({"entries": []}))
    write(tmp_path, "starter-kits/broken/kit.json", "{not-json")

    result = run_script("update_starter_kits_registry.py", tmp_path)

    assert result.returncode == 1
    assert "[broken] Failed to load kit.json" in result.stderr
    assert not (tmp_path / ".auto-registry" / "starter-kit-registry.json").exists()


def test_regenerated_starter_kit_registry_matches_public_schema():
    registry = load_json(REPO_ROOT / ".auto-registry" / "agent-registry.json")
    agent_paths = build_registry_path_set(registry)
    generated_at = "2026-01-02T03:04:05Z"
    entries = []
    for kit_dir in get_kit_dirs(REPO_ROOT):
        kit_relpath = get_kit_relpath(REPO_ROOT, kit_dir)
        entries.append(
            build_kit_registry_entry(
                load_json(kit_dir / "kit.json"),
                kit_dir,
                kit_relpath,
                REPO_ROOT,
                agent_paths,
                generated_at,
            )
        )

    payload = {
        "schemaVersion": "1.0.0",
        "generatedAt": generated_at,
        "commitSha": "0123456789abcdef0123456789abcdef01234567",
        "kits": entries,
    }
    errors = list(
        schema_validator("starter-kit-registry-schema.json").iter_errors(payload)
    )

    assert [entry["kitPath"] for entry in entries] == sorted(
        entry["kitPath"] for entry in entries
    )
    assert not errors, [error.message for error in errors]