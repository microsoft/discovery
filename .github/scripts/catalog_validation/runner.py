"""Orchestration for all PR validation check families.

Two engines run side by side, and this module is the single place that fans a
PR out to both. To keep their responsibilities unambiguous, each rule family
has exactly one authoritative owner:

Legacy check families (``catalog_validation.*``) — authoritative for:
  * contributor scope   (``contributor_scope``) — who may touch what
  * repository structure (``structural``)        — required files/folders
  * schema conformance   (``schema_checks``)     — agent/tool/metadata schemas
  * documentation        (``documentation``)     — required docs/sections
  * waiver-gated policy  (``policy_checks``)     — contribution-scope policy
    that needs author/permission context the pure rules do not receive.

Modular rule engine (``rules.*``, discovered by the registry) — authoritative
for the ratcheted, waiverable content rules addressed by rule id:
  * binary / model-weight content   (POL-008, POL-014 …)
  * base-image provenance            (base-image and tag policies …)
  * large/committed artifacts        (POL-015, POL-016, POL-020)
  * publisher contact reachability   (POL-018, POL-019)
  * tag taxonomy                     (TAG-001, TAG-002)

The two sets do not overlap: a given rule id is produced by exactly one engine,
so a PR can never receive duplicate findings for the same violation. New
content rules should be added to the modular engine (one file per rule); the
legacy families remain because they need orchestration context (permissions,
schema objects) that the per-rule contract intentionally omits.

Multiple findings for one file are intentional, not deduplicated. Distinct rule
ids (for example an image-integrity rule, a committed-artifact rule, and a
source-allowlist rule) can each flag the same file, because each reports an
independent defect with its own remediation. Collapsing them by file+category
would hide separately-actionable problems and could let a real violation ride
in behind an unrelated one, so the orchestrator deliberately preserves every
finding and relies on the single-owner rule-id contract above to prevent true
duplicates (the same violation reported twice).
"""

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
            "has_markdown_only": self.contribution.has_markdown_only,
            "has_dockerfile": self.contribution.has_dockerfile,
            "has_code": self.contribution.has_code,
            "has_1p": self.contribution.has_1p,
            "has_3p": self.contribution.has_3p,
            "has_images": bool(self.contribution.image_files),
            "image_files": self.contribution.image_files,
            "failures": [failure.to_dict() for failure in self.blocking],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


def _config_error_path(message: str) -> str:
    """Attribute a run-engine config error to the policy file it names.

    Waiver and baseline errors are both surfaced as CFG-001; the message always
    begins with the offending file name so we can point the failure at the right
    file instead of a hard-coded default.
    """
    leading = message.split(":", 1)[0].split()[0] if message.strip() else ""
    if leading in {"waivers.yaml", "baseline.json"}:
        return f".github/policy/{leading}"
    return ".github/policy/waivers.yaml"


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

    # A policy file that could not be loaded as a mapping is a blocking config
    # error, not an empty policy: a malformed source-allowlist / base-images /
    # tag-taxonomy must never silently disable the checks that depend on it.
    failures.extend(
        Failure("CFG-002", rel_path, message)
        for rel_path, message in context.policy.config_errors
    )

    # A missing or corrupt catalog schema is part of the validation boundary:
    # it must block, not merely warn, so schema-backed checks can never be
    # silently skipped while the validator still passes.
    failures.extend(
        Failure("CFG-003", rel_path, message)
        for rel_path, message in schemas.config_errors()
    )

    rules = discover_rules()
    guidance = {rule.id: rule for rule in rules}
    engine = run_rules(context, rules)
    failures.extend(
        Failure("CFG-001", _config_error_path(error), error)
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
        setup_warnings=[],
    )