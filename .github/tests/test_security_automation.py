"""Regression tests for GitHub-native security automation."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_SCAN_PATH = REPO_ROOT / ".github" / "workflows" / "code-scan.yml"
DEPENDENCY_REVIEW_PATH = REPO_ROOT / ".github" / "workflows" / "dependency-review.yml"
DEPENDABOT_PATH = REPO_ROOT / ".github" / "dependabot.yml"
CI_REQUIREMENTS_PATH = REPO_ROOT / ".github" / "requirements-ci.txt"
DOTNET_TOOL_MANIFEST_PATH = REPO_ROOT / ".config" / "dotnet-tools.json"

CODEQL_SCOPES = {
    ("python", "catalog-python"): ".github/codeql/codeql-config.yml",
}

CODEQL_PATHS = {
    ".github/codeql/codeql-config.yml": {"agents", "starter-kits"},
}

CODEQL_TRIGGER_PATHS = {
    "agents/**",
    "starter-kits/**",
}
CATALOG_TRIGGER_PATHS = CODEQL_TRIGGER_PATHS


def load_yaml(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"Expected a YAML mapping in {path}"
    return document


def load_workflow(path: Path) -> dict[str, Any]:
    # BaseLoader preserves the GitHub Actions key `on` instead of treating it
    # as a YAML 1.1 boolean.
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict), f"Expected a workflow mapping in {path}"
    return document


def uses_action(step: dict[str, Any], action: str) -> bool:
    """Match an action independently of whether its revision is a tag or SHA."""
    return step.get("uses", "").partition("@")[0] == action


def dependabot_update(ecosystem: str) -> dict[str, Any]:
    updates = load_yaml(DEPENDABOT_PATH)["updates"]
    matches = [
        update for update in updates if update["package-ecosystem"] == ecosystem
    ]
    assert len(matches) == 1, f"Expected one Dependabot block for {ecosystem}"
    return matches[0]


def directory_matches(directory: str, patterns: list[str]) -> bool:
    relative = PurePosixPath(directory.lstrip("/"))
    return any(relative.match(pattern.lstrip("/")) for pattern in patterns)


def test_codeql_matrix_keeps_scopes_separate_and_supported():
    workflow = load_workflow(CODE_SCAN_PATH)
    codeql_job = workflow["jobs"]["codeql"]
    matrix = codeql_job["strategy"]["matrix"]["include"]

    actual_scopes = {
        (entry["language"], entry["scope"]): entry["config"].removeprefix("./")
        for entry in matrix
    }
    assert actual_scopes == CODEQL_SCOPES
    assert codeql_job["strategy"]["fail-fast"] == "false"

    action_refs = {
        step["uses"]
        for step in codeql_job["steps"]
        if step.get("uses", "").startswith("github/codeql-action/")
    }
    assert action_refs == {
        "github/codeql-action/init@v4",
        "github/codeql-action/analyze@v4",
    }
    analyze_step = next(step for step in codeql_job["steps"] if step.get("name") == "Analyze")
    assert analyze_step["with"]["category"] == (
        "/language:${{ matrix.language }}/scope:${{ matrix.scope }}"
    )
    assert analyze_step["with"]["output"] == "codeql-results"
    assert analyze_step["with"]["upload"] == (
        "${{ github.event_name != 'pull_request' || "
        "github.event.pull_request.head.repo.full_name == github.repository }}"
    )
    artifact_step = next(
        step for step in codeql_job["steps"]
        if step.get("name") == "Upload CodeQL SARIF artifact"
    )
    assert artifact_step["if"] == "always()"


def test_codeql_configs_cover_expected_sources_and_queries():
    for relative_path, expected_paths in CODEQL_PATHS.items():
        config_path = REPO_ROOT / relative_path
        config = load_yaml(config_path)

        assert set(config["paths"]) == expected_paths
        assert all((REPO_ROOT / path).exists() for path in config["paths"])
        suites = {query["uses"] for query in config["queries"]}
        assert suites <= {"security-and-quality", "security-extended"}
        assert suites


def test_all_codeql_actions_use_current_supported_major():
    references: list[tuple[str, str]] = []
    for workflow_path in (REPO_ROOT / ".github" / "workflows").glob("*.yml"):
        for reference in re.findall(
            r"github/codeql-action/[^@\s]+@v\d+",
            workflow_path.read_text(encoding="utf-8"),
        ):
            references.append((workflow_path.name, reference))

    assert references, "Expected at least one CodeQL action reference"
    stale = [(path, reference) for path, reference in references if not reference.endswith("@v4")]
    assert not stale, f"CodeQL actions not using v4: {stale}"


def test_codeql_runs_when_any_scanned_source_changes():
    workflow = load_workflow(CODE_SCAN_PATH)
    triggers = workflow["on"]

    assert set(triggers["pull_request"]["paths"]) == CODEQL_TRIGGER_PATHS
    assert set(triggers["push"]["paths"]) == CODEQL_TRIGGER_PATHS


def test_dependabot_monitors_each_supported_ecosystem():
    config = load_yaml(DEPENDABOT_PATH)
    ecosystems = {update["package-ecosystem"] for update in config["updates"]}
    assert ecosystems == {"github-actions", "nuget", "uv", "pip", "docker"}

    for update in config["updates"]:
        assert update["schedule"]["interval"] == "weekly"
        assert update["open-pull-requests-limit"] > 0

    assert dependabot_update("github-actions")["directory"] == "/"

    uv_directory = dependabot_update("uv")["directory"].lstrip("/")
    assert (REPO_ROOT / uv_directory / "pyproject.toml").is_file()
    assert (REPO_ROOT / uv_directory / "uv.lock").is_file()


def test_dependency_review_blocks_new_high_severity_vulnerabilities():
    workflow = load_workflow(DEPENDENCY_REVIEW_PATH)
    assert "pull_request" in workflow["on"]
    assert set(workflow["on"]["pull_request"]["paths"]) == CATALOG_TRIGGER_PATHS
    assert workflow["permissions"] == {"contents": "read"}

    job = workflow["jobs"]["dependency-review"]
    review_step = next(
        step
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/dependency-review-action@")
    )
    assert review_step["uses"] == "actions/dependency-review-action@v5"
    assert review_step["with"] == {
        "fail-on-severity": "high",
        "fail-on-scopes": "runtime, development, unknown",
        "show-patched-versions": "true",
    }


def test_weekly_msdo_checks_out_only_catalog_roots():
    workflow = load_workflow(
        REPO_ROOT / ".github" / "workflows" / "weekly-deep-scan.yml"
    )
    checkout = next(
        step for step in workflow["jobs"]["msdo"]["steps"]
        if step.get("uses") == "actions/checkout@v6"
    )

    assert checkout["with"]["sparse-checkout"].splitlines() == [
        "/agents/",
        "/starter-kits/",
    ]
    assert checkout["with"]["sparse-checkout-cone-mode"] == "false"
    assert checkout["with"]["persist-credentials"] == "false"

    msdo_step = next(
        step for step in workflow["jobs"]["msdo"]["steps"]
        if step.get("name") == "Run Microsoft Security DevOps"
    )
    assert msdo_step["with"]["tools"].split(",") == [
        "bandit",
        "checkov",
        "trivy",
    ]


def test_weekly_manual_dry_run_suppresses_repository_writes():
    workflow = load_workflow(
        REPO_ROOT / ".github" / "workflows" / "weekly-deep-scan.yml"
    )
    dry_run = workflow["on"]["workflow_dispatch"]["inputs"]["dry_run"]
    assert dry_run["type"] == "boolean"
    assert dry_run["default"] == "true"
    assert workflow["permissions"] == {"contents": "read"}

    msdo_steps = workflow["jobs"]["msdo"]["steps"]
    security_upload = next(
        step for step in msdo_steps
        if step.get("name") == "Upload results to the Security tab"
    )
    assert security_upload["if"] == (
        "${{ !inputs.dry_run && steps.msdo.outputs.sarifFile != '' }}"
    )

    report = workflow["jobs"]["report"]
    assert report["permissions"] == {"issues": "write"}
    assert "!inputs.dry_run" in report["if"]


def test_weekly_url_reputation_provider_errors_are_report_only():
    workflow = load_workflow(
        REPO_ROOT / ".github" / "workflows" / "weekly-deep-scan.yml"
    )
    reputation_step = next(
        step for step in workflow["jobs"]["url-reputation-audit"]["steps"]
        if step.get("id") == "reputation"
    )
    command = reputation_step["run"]
    assert "EXIT_CODE=0" in command
    assert "|| EXIT_CODE=$?" in command
    assert command.rstrip().endswith("exit 0")


def test_validation_workflows_publish_actionable_diagnostics():
    unit_workflow = load_workflow(
        REPO_ROOT / ".github" / "workflows" / "unit-tests.yml"
    )
    unit_steps = unit_workflow["jobs"]["pytest"]["steps"]
    unit_test_step = next(step for step in unit_steps if step.get("id") == "unit_tests")
    assert "-n auto --dist worksteal" in unit_test_step["run"]
    assert "set -o pipefail" in unit_test_step["run"]
    assert "--junitxml=\"$RUNNER_TEMP/unit-tests.xml\"" in unit_test_step["run"]
    assert "2>&1 | tee \"$RUNNER_TEMP/unit-tests.log\"" in unit_test_step["run"]
    unit_summary = next(
        step for step in unit_steps if step.get("name") == "Summarize unit test results"
    )
    assert "render_ci_summary.py pytest" in unit_summary["run"]
    unit_artifact = next(
        step for step in unit_steps if step.get("name") == "Upload unit test diagnostics"
    )
    assert unit_artifact["if"].startswith("${{ always()")

    full_workflow = load_workflow(
        REPO_ROOT / ".github" / "workflows" / "validate-everything.yml"
    )
    full_steps = full_workflow["jobs"]["validate-all-agents"]["steps"]
    full_checkout = next(
        step for step in full_steps if uses_action(step, "actions/checkout")
    )
    assert full_checkout["with"]["lfs"] == "true"
    assert "validate-all-starter-kits" not in full_workflow["jobs"]
    assert any(
        step.get("name") == "Validate every starter kit against current schema"
        for step in full_steps
    )
    validation_step_ids = {"unit_tests", "catalog", "starter_kits"}
    for step in full_steps:
        if step.get("id") in validation_step_ids:
            assert step.get("continue-on-error") == "true"
    aggregate_failure = next(
        step for step in full_steps
        if step.get("name") == "Fail when any full-catalog validation failed"
    )
    assert aggregate_failure["if"] == "always()"
    assert "UNIT_TEST_OUTCOME" in aggregate_failure["env"]
    assert "CATALOG_OUTCOME" in aggregate_failure["env"]
    assert "STARTER_KIT_OUTCOME" in aggregate_failure["env"]
    for step in full_steps:
        if "| tee" in step.get("run", ""):
            assert "set -o pipefail" in step["run"] or "|| true" in step["run"]
    assert any(
        "render_ci_summary.py pytest" in step.get("run", "") for step in full_steps
    )
    assert any(
        "render_ci_summary.py catalog" in step.get("run", "") for step in full_steps
    )
    shadow_steps = full_workflow["jobs"]["shadow-pr"]["steps"]
    shadow_summary = next(
        step for step in shadow_steps
        if step.get("name") == "Summarize report-only results"
    )
    assert "trusted/.github/scripts/render_ci_summary.py shadow" in shadow_summary["run"]
    assert "--catalog-report" in shadow_summary["run"]
    assert "--schema-log" in shadow_summary["run"]

    pr_workflow = load_workflow(
        REPO_ROOT / ".github" / "workflows" / "pr-review.yml"
    )
    pr_steps = pr_workflow["jobs"]["validate"]["steps"]
    pr_summary = next(
        step for step in pr_steps if step.get("name") == "Summarize validation results"
    )
    assert pr_summary["if"] == "always()"
    assert "trusted/.github/scripts/render_ci_summary.py catalog" in pr_summary["run"]
    post_results = pr_workflow["jobs"]["post-results"]["steps"]
    feedback = next(
        step for step in post_results
        if step.get("name") == "Manage labels and post PR feedback"
    )["with"]["script"]
    assert "**How to fix:** ${remediation(f)}" in feedback
    assert "**Guidance:** ${guidanceUrl(f)}" in feedback
    assert "results.has_markdown_only" in feedback
    assert "results.has_dockerfile" in feedback
    assert "results.has_code" in feedback
    assert "'markdown-only':             { color: '8250df'" in feedback
    assert "'contains-dockerfile':       { color: '2496ed'" in feedback
    assert "'contains-code':             { color: '1f883d'" in feedback


def test_dependabot_covers_all_requirements_files():
    requirements = sorted(
        [CI_REQUIREMENTS_PATH]
        + [*REPO_ROOT.glob("agents/**/requirements.txt")]
        + [*REPO_ROOT.glob("utilities/**/requirements.txt")]
    )
    expected_directories = {
        f"/{path.parent.relative_to(REPO_ROOT).as_posix()}" for path in requirements
    }

    assert requirements, "Expected at least one requirements.txt"
    assert set(dependabot_update("pip")["directories"]) == expected_directories


def test_ci_python_dependencies_are_pinned_and_workflows_use_the_manifest():
    requirements = [
        line
        for line in CI_REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert all(
        re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", requirement)
        for requirement in requirements
    )
    assert {requirement.split("==", 1)[0].lower() for requirement in requirements} == {
        "codespell",
        "dnspython",
        "jsonschema",
        "onnx",
        "picklescan",
        "pytest",
        "pytest-xdist",
        "pyyaml",
        "referencing",
    }

    install_steps: list[tuple[str, str]] = []
    for workflow_path in (REPO_ROOT / ".github" / "workflows").glob("*.yml"):
        workflow = load_workflow(workflow_path)
        for job in workflow.get("jobs", {}).values():
            for step in job.get("steps", []):
                command = step.get("run", "")
                if re.search(r"(?m)^\s*(?:python -m )?pip install\b", command):
                    install_steps.append((workflow_path.name, command))

    assert install_steps
    unmanaged = [
        (workflow, command)
        for workflow, command in install_steps
        if "requirements-ci.txt" not in command
    ]
    assert not unmanaged, f"Inline CI Python dependencies found: {unmanaged}"


def test_python_validation_jobs_use_github_hosted_linux():
    expected_jobs = {
        "check-agent-removal-impact.yml": {"check-impact"},
        "pr-review.yml": {"validate"},
        "unit-tests.yml": {"pytest"},
        "validate-everything.yml": {"validate-all-agents"},
        "validate-agent-schemas.yml": {"validate-schemas"},
        "validate-starter-kit-schema.yml": {"validate-schema"},
        "validate-starter-kits.yml": {"validate"},
        "weekly-deep-scan.yml": {
            "full-catalog-audit",
            "url-reputation-audit",
            "discover-images",
        },
    }
    slim_jobs = {
        ("check-agent-removal-impact.yml", "check-impact"),
        ("validate-agent-schemas.yml", "validate-schemas"),
        ("validate-starter-kit-schema.yml", "validate-schema"),
        ("validate-starter-kits.yml", "validate"),
        ("weekly-deep-scan.yml", "discover-images"),
    }

    for workflow_name, job_names in expected_jobs.items():
        workflow = load_workflow(REPO_ROOT / ".github" / "workflows" / workflow_name)
        for job_name in job_names:
            job = workflow["jobs"][job_name]
            expected_runner = (
                "ubuntu-slim"
                if (workflow_name, job_name) in slim_jobs
                else "ubuntu-latest"
            )
            assert job["runs-on"] == expected_runner
            assert "container" not in job
            if expected_runner == "ubuntu-slim":
                assert int(job["timeout-minutes"]) <= 15

            setup_steps = [
                step
                for step in job["steps"]
                if uses_action(step, "actions/setup-python")
            ]
            assert len(setup_steps) == 1
            assert setup_steps[0]["with"]["python-version"] == "3.12"

    workflow_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / ".github" / "workflows").glob("*.yml")
    )
    assert "mcr.microsoft.com/azurelinux" not in workflow_text
    assert "tdnf install" not in workflow_text
    assert "packagefeedproxy.microsoft.io" not in workflow_text


def test_pull_request_target_jobs_keep_pr_data_untrusted():
    for workflow_name, job_name in {
        "check-agent-removal-impact.yml": "check-impact",
        "pr-review.yml": "validate",
    }.items():
        workflow = load_workflow(REPO_ROOT / ".github" / "workflows" / workflow_name)
        steps = workflow["jobs"][job_name]["steps"]
        trusted_checkout = next(
            step for step in steps if step.get("with", {}).get("path") == "trusted"
        )
        pr_checkout = next(
            step for step in steps if step.get("with", {}).get("path") == "pr"
        )

        assert trusted_checkout["with"]["ref"] == (
            "${{ github.event.pull_request.base.sha }}"
        )
        assert trusted_checkout["with"]["persist-credentials"] == "false"
        assert pr_checkout["with"]["repository"] == (
            "${{ github.event.pull_request.head.repo.full_name }}"
        )
        assert pr_checkout["with"]["ref"] == (
            "${{ github.event.pull_request.head.sha }}"
        )
        assert pr_checkout["with"]["persist-credentials"] == "false"

    pr_review_path = REPO_ROOT / ".github" / "workflows" / "pr-review.yml"
    pr_review = load_workflow(pr_review_path)
    head_checkouts = [
        step
        for job in pr_review["jobs"].values()
        for step in job.get("steps", [])
        if uses_action(step, "actions/checkout")
        and step.get("with", {}).get("ref")
        == "${{ github.event.pull_request.head.sha }}"
    ]
    assert len(head_checkouts) == 3
    for checkout in head_checkouts:
        assert checkout["with"]["repository"] == (
            "${{ github.event.pull_request.head.repo.full_name }}"
        )
        assert checkout["with"]["persist-credentials"] == "false"
    assert "allow-unsafe-pr-checkout" not in pr_review_path.read_text(encoding="utf-8")


def test_manual_shadow_validation_is_report_only_and_fork_aware():
    workflow = load_workflow(
        REPO_ROOT / ".github" / "workflows" / "validate-everything.yml"
    )
    assert workflow["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
    }
    assert "pr_number" in workflow["on"]["workflow_dispatch"]["inputs"]

    shadow_job = workflow["jobs"]["shadow-pr"]
    assert shadow_job["if"] == "${{ inputs.pr_number != '' }}"
    steps = shadow_job["steps"]
    trusted_checkout = next(
        step for step in steps if step.get("with", {}).get("path") == "trusted"
    )
    pr_checkout = next(
        step for step in steps if step.get("with", {}).get("path") == "pr"
    )
    assert trusted_checkout["with"]["ref"] == "${{ github.sha }}"
    assert trusted_checkout["if"] == "always()"
    assert trusted_checkout["with"]["persist-credentials"] == "false"
    assert pr_checkout["with"]["repository"] == (
        "${{ steps.target.outputs.head-repository }}"
    )
    assert pr_checkout["with"]["ref"] == "${{ steps.target.outputs.head-sha }}"
    assert pr_checkout["with"]["persist-credentials"] == "false"
    setup_python = next(
        step for step in steps if uses_action(step, "actions/setup-python")
    )
    assert "cache" not in setup_python.get("with", {})

    report_only_steps = {
        "Build ephemeral integration tree",
        "Run primary catalog validator",
        "Run schema regression suite against PR data",
        "Run starter-kit validation against PR data",
        "Run removal-impact validation without write access",
    }
    assert report_only_steps <= {step.get("name") for step in steps}
    for step in steps:
        if step.get("name") in report_only_steps:
            assert step.get("continue-on-error") == "true"

    source = (
        REPO_ROOT / ".github" / "workflows" / "validate-everything.yml"
    ).read_text(encoding="utf-8")
    commands = "\n".join(step.get("run", "") for step in steps)
    assert "python trusted/.github/scripts/" in commands
    assert not re.search(r"(?m)^\s*python\s+pr/", commands)
    assert '--repo-root "$GITHUB_WORKSPACE/evaluation"' in commands
    assert "DISCOVERY_CATALOG_ROOT: ${{ github.workspace }}/evaluation" in source
    assert "--github-token" not in commands
    assert "did not change or publish a check to the target PR" in commands

    for mutation in (
        "issues.createComment",
        "issues.addLabels",
        "pulls.createReview",
        "pulls.merge",
    ):
        assert mutation not in source

    branch_job = workflow["jobs"]["validate-all-agents"]
    assert branch_job["if"] == "${{ inputs.pr_number == '' }}"
    assert any(
        "python -m pytest .github/tests/" in step.get("run", "")
        and "-n auto --dist worksteal" in step.get("run", "")
        for step in branch_job["steps"]
    )
    full_catalog_command = next(
        step["run"] for step in branch_job["steps"]
        if step.get("name") == "Build full file list and run validate_pr.py"
    )
    assert "git ls-files agents" in full_catalog_command
    assert "git ls-files starter-kits" in full_catalog_command
    assert "git ls-files docs/schemas" not in full_catalog_command


def test_dependabot_covers_all_conventional_dockerfiles():
    dockerfiles = sorted(
        [*REPO_ROOT.glob("agents/*/tools/*/Dockerfile")]
        + [*REPO_ROOT.glob("utilities/**/Dockerfile")]
    )
    patterns = dependabot_update("docker")["directories"]
    uncovered = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in dockerfiles
        if not directory_matches(
            f"/{path.parent.relative_to(REPO_ROOT).as_posix()}", patterns
        )
    ]

    assert dockerfiles, "Expected at least one conventional Dockerfile"
    assert not uncovered, f"Dockerfiles missing Dependabot coverage: {uncovered}"


def test_workflow_executables_are_immutable_and_dependency_managed():
    workflow_sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / ".github" / "workflows").glob("*.yml")
    }
    problems: list[str] = []

    for workflow_name, source in workflow_sources.items():
        if re.search(r"(?m)^\s*uses:\s*[^\s#]+@latest(?:\s|$)", source):
            problems.append(f"{workflow_name}: action uses @latest")

        for installer_match in re.finditer(
            r"https://raw\.githubusercontent\.com/[^/\s]+/[^/\s]+/"
            r"(?P<revision>[^/\s]+)/[^\s]*install\.sh",
            source,
        ):
            revision = installer_match.group("revision")
            if not re.fullmatch(r"[0-9a-f]{40}", revision):
                problems.append(
                    f"{workflow_name}: installer is not pinned to a full commit SHA"
                )

            install_command = source[installer_match.end() : installer_match.end() + 160]
            if not re.search(r"\bv\d+\.\d+\.\d+\b", install_command):
                problems.append(
                    f"{workflow_name}: installer does not select an explicit release"
                )

    if not DOTNET_TOOL_MANIFEST_PATH.is_file():
        problems.append("Application Inspector has no local .NET tool manifest")
    else:
        manifest = json.loads(DOTNET_TOOL_MANIFEST_PATH.read_text(encoding="utf-8"))
        application_inspector = manifest.get("tools", {}).get(
            "microsoft.cst.applicationinspector.cli"
        )
        if not application_inspector:
            problems.append("Application Inspector is absent from the .NET tool manifest")
        else:
            if not re.fullmatch(
                r"\d+\.\d+\.\d+", application_inspector.get("version", "")
            ):
                problems.append("Application Inspector has no exact manifest version")
            if application_inspector.get("commands") != ["appinspector"]:
                problems.append("Application Inspector manifest command changed")

    code_scan_source = workflow_sources[CODE_SCAN_PATH.name]
    if "dotnet tool restore" not in code_scan_source:
        problems.append("code-scan.yml does not restore the .NET tool manifest")
    if "dotnet tool run appinspector analyze" not in code_scan_source:
        problems.append("code-scan.yml does not invoke the manifest-pinned tool")

    nuget_updates = [
        update
        for update in load_yaml(DEPENDABOT_PATH)["updates"]
        if update["package-ecosystem"] == "nuget"
    ]
    if len(nuget_updates) != 1 or nuget_updates[0].get("directory") != "/":
        problems.append("Dependabot does not manage the root .NET tool manifest")

    assert not problems, "Unpinned workflow executables:\n- " + "\n- ".join(problems)