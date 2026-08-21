"""Orchestration for all PR validation check families."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rules.registry import build_context, discover_rules, run_rules

from .contribution import ContributionSummary, classify_contribution
from .contributor_scope import check_contributor_scope
from .documentation import check_documentation
from .findings import Failure
from .policy_checks import check_policy
from .schema_checks import check_schema
from .schemas import CatalogSchemas
from .structural import check_structural


@dataclass(frozen=True)
class ValidationRun:
    blocking: list[Failure]
    warnings: list[Failure]
    contribution: ContributionSummary
    setup_warnings: list[str]

    @property
    def passed(self) -> bool:
        return not self.blocking

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "failure_count": len(self.blocking),
            "warning_count": len(self.warnings),
            "has_agents": self.contribution.has_agents,
            "has_docs_only": self.contribution.has_docs_only,
            "has_1p": self.contribution.has_1p,
            "has_3p": self.contribution.has_3p,
            "has_images": bool(self.contribution.image_files),
            "image_files": self.contribution.image_files,
            "failures": [failure.to_dict() for failure in self.blocking],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


def run_validation(
    repo: Path,
    changed_files: list[str],
    *,
    author_permission: str | None = None,
    author: str = "",
    head_ref: str = "",
) -> ValidationRun:
    context = build_context(repo, changed_files)
    schemas = CatalogSchemas.load(repo)

    failures: list[Failure] = []
    failures.extend(check_contributor_scope(
        changed_files,
        author_permission,
        author,
        head_ref,
    ))
    failures.extend(check_structural(repo, context.agent_folders, changed_files))
    failures.extend(check_schema(
        repo,
        context.agent_folders,
        schemas.agent,
        schemas.tool,
        schemas.metadata,
        schemas.registry,
    ))
    failures.extend(check_policy(
        repo,
        context.agent_folders,
        changed_files,
        author=author,
        head_ref=head_ref,
    ))
    failures.extend(check_documentation(repo, context.agent_folders))

    rules = discover_rules()
    guidance = {rule.id: rule for rule in rules}
    engine = run_rules(context, rules)
    failures.extend(
        Failure("CFG-001", ".github/policy/waivers.yaml", error)
        for error in engine.config_errors
    )
    failures.extend(
        Failure(
            finding.rule_id,
            finding.file,
            finding.message,
            finding.line,
            severity=finding.severity.value,
            remediation=guidance[finding.rule_id].remediation,
            docs=guidance[finding.rule_id].docs,
        )
        for finding in engine.findings
    )

    return ValidationRun(
        blocking=[failure for failure in failures if failure.severity == "error"],
        warnings=[failure for failure in failures if failure.severity != "error"],
        contribution=classify_contribution(
            repo,
            changed_files,
            context.agent_folders,
            context.kit_folders,
        ),
        setup_warnings=schemas.warnings(),
    )