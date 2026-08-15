#!/usr/bin/env python3
"""
rules.registry — rule discovery, waiver handling, and the ratchet.

The registry imports every sibling ``rules.*`` module, collects each module's
``RULE``, and runs them against a prepared :class:`RuleContext`. Two policy
layers sit between a raw finding and a blocking failure:

1. **Waivers** (`.github/policy/waivers.yaml`) — a reviewed, expiring
   exception for a specific rule and path. Suppresses the finding entirely.
2. **Ratchet** (`.github/policy/baseline.json`) — pre-existing violations
   recorded at rollout. Downgraded to warnings so legacy content keeps
   building, while any *new* violation of the same rule still blocks.

The ratchet is what lets a stricter ruleset ship without breaking the 46
agents that predate it.
"""

from __future__ import annotations

import datetime as _dt
import dataclasses
import fnmatch
import importlib
import json
import os
import pkgutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from rules.base import Finding, PolicyConfig, Rule, RuleContext, Scope, Severity

#: Waivers may not be issued further out than this.
MAX_WAIVER_DAYS = 180


# ── Waivers ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Waiver:
    rule_id: str
    path: str
    reason: str
    approver: str
    expires: _dt.date

    def matches(self, rule_id: str, file: str) -> bool:
        if self.rule_id != rule_id:
            return False
        norm = file.replace("\\", "/")
        return norm == self.path or fnmatch.fnmatch(norm, self.path)

    def is_expired(self, today: _dt.date) -> bool:
        return self.expires < today


def load_waivers(repo: Path) -> tuple[list[Waiver], list[str]]:
    """Load and validate waivers. Returns (waivers, config_errors).

    A malformed or over-long waiver is reported as a config error rather than
    being silently ignored — a broken waiver file must never fail open.
    """
    path = repo / ".github" / "policy" / "waivers.yaml"
    if not path.exists():
        return [], []

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError) as e:
        return [], [f"waivers.yaml could not be parsed: {e}"]

    entries = raw.get("waivers") or []
    if not isinstance(entries, list):
        return [], ["waivers.yaml: 'waivers' must be a list."]

    waivers: list[Waiver] = []
    errors: list[str] = []
    today = _dt.date.today()

    for idx, entry in enumerate(entries):
        where = f"waivers.yaml entry #{idx + 1}"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be a mapping.")
            continue

        missing = [
            k for k in ("rule_id", "path", "reason", "approver", "expires")
            if not entry.get(k)
        ]
        if missing:
            errors.append(f"{where}: missing required field(s) {missing}.")
            continue

        reason = str(entry["reason"]).strip()
        if len(reason) < 20:
            errors.append(
                f"{where}: 'reason' must be at least 20 characters explaining "
                f"why the exception is justified."
            )
            continue

        expires_raw = entry["expires"]
        expires = expires_raw if isinstance(expires_raw, _dt.date) else None
        if expires is None:
            try:
                expires = _dt.date.fromisoformat(str(expires_raw))
            except ValueError:
                errors.append(f"{where}: 'expires' must be an ISO date (YYYY-MM-DD).")
                continue

        if expires < today:
            errors.append(
                f"{where}: waiver for {entry['rule_id']} on '{entry['path']}' "
                f"expired on {expires.isoformat()}. Fix the underlying issue or "
                f"renew the waiver with fresh CODEOWNER approval."
            )
            continue

        if (expires - today).days > MAX_WAIVER_DAYS:
            errors.append(
                f"{where}: 'expires' is more than {MAX_WAIVER_DAYS} days out. "
                f"Waivers are temporary by design."
            )
            continue

        waivers.append(Waiver(
            rule_id=str(entry["rule_id"]),
            path=str(entry["path"]).replace("\\", "/"),
            reason=reason,
            approver=str(entry["approver"]),
            expires=expires,
        ))

    return waivers, errors


# ── Ratchet baseline ─────────────────────────────────────────────────────────

def load_baseline(repo: Path) -> set[tuple[str, str]]:
    """Load recorded pre-existing violations as {(rule_id, path)}."""
    path = repo / ".github" / "policy" / "baseline.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()

    entries = data.get("violations") or []
    out: set[tuple[str, str]] = set()
    for e in entries:
        if isinstance(e, dict) and e.get("rule_id") and e.get("file"):
            out.add((str(e["rule_id"]), str(e["file"]).replace("\\", "/")))
    return out


# ── Discovery ────────────────────────────────────────────────────────────────

def discover_rules() -> list[Rule]:
    """Import every sibling module and collect its ``RULE``."""
    import rules as _pkg

    found: list[Rule] = []
    for mod_info in pkgutil.iter_modules(_pkg.__path__):
        name = mod_info.name
        if name in {"base", "registry"} or name.startswith("_"):
            continue
        module = importlib.import_module(f"rules.{name}")
        rule = getattr(module, "RULE", None)
        if rule is None:
            raise RuntimeError(
                f"rules/{name}.py does not export a module-level RULE. Every "
                f"rule module must define exactly one Rule named RULE."
            )
        if not isinstance(rule, Rule):
            raise RuntimeError(f"rules/{name}.py: RULE must be a rules.base.Rule instance.")
        found.append(rule)

    ids = [r.id for r in found]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise RuntimeError(f"Duplicate rule id(s) across rule modules: {sorted(dupes)}")

    return sorted(found, key=lambda r: r.id)


# ── Execution ────────────────────────────────────────────────────────────────

@dataclass
class RunResult:
    findings: list[Finding]
    config_errors: list[str]

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]


def _is_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true"


def build_context(
    repo: Path,
    changed_files: list[str],
    policy: PolicyConfig | None = None,
) -> RuleContext:
    """Resolve scopes once so individual rules stay simple."""
    agent_folders: set[Path] = set()
    kit_folders: set[Path] = set()

    for f in changed_files:
        parts = Path(f.replace("\\", "/")).parts
        if len(parts) >= 2 and parts[1] != "tmp":
            root = parts[0]
            if root == "agents":
                agent_folders.add(Path(parts[0], parts[1]))
            elif root == "starter-kits":
                kit_folders.add(Path(parts[0], parts[1]))

    # Only keep folders that actually exist — a fully deleted agent has no
    # folder to validate.
    agent_folders = {f for f in agent_folders if (repo / f).is_dir()}
    kit_folders = {f for f in kit_folders if (repo / f).is_dir()}

    return RuleContext(
        repo=repo,
        changed_files=[f.replace("\\", "/") for f in changed_files],
        agent_folders=agent_folders,
        kit_folders=kit_folders,
        policy=policy or PolicyConfig.load(repo),
        is_ci=_is_ci(),
    )


def run_rules(
    ctx: RuleContext,
    rules: list[Rule] | None = None,
    *,
    apply_ratchet: bool = True,
) -> RunResult:
    """Execute rules against ``ctx`` and apply waivers plus the ratchet."""
    rules = rules if rules is not None else discover_rules()
    waivers, config_errors = load_waivers(ctx.repo)
    baseline = load_baseline(ctx.repo) if apply_ratchet else set()

    raw: list[Finding] = []
    for rule in rules:
        raw.extend(_invoke(rule, ctx))

    resolved: list[Finding] = []
    for finding in raw:
        if any(w.matches(finding.rule_id, finding.file) for w in waivers):
            continue
        if (finding.rule_id, finding.file) in baseline:
            # Pre-existing at rollout: report, but do not block.
            resolved.append(
                Finding(
                    rule_id=finding.rule_id,
                    file=finding.file,
                    message=f"{finding.message} (pre-existing; tracked in the ratchet baseline)",
                    line=finding.line,
                    severity=Severity.WARNING,
                )
            )
            continue
        resolved.append(finding)

    return RunResult(findings=resolved, config_errors=config_errors)


def _invoke(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """Call a rule once per item in its declared scope.

    Severity is stamped from the rule rather than the finding, so a rule's
    blocking-ness is declared in one place and cannot drift between the
    findings it emits.
    """
    if rule.scope is Scope.CHANGED_FILES or rule.scope is Scope.REPO:
        scoped = RuleContext(**{**ctx.__dict__, "folder": None})
        return _stamp(rule, rule.check(scoped) or [])

    if rule.scope is Scope.AGENT_FOLDER:
        folders = sorted(ctx.agent_folders)
    elif rule.scope is Scope.KIT_FOLDER:
        folders = sorted(ctx.kit_folders)
    else:
        raise RuntimeError(f"Rule {rule.id} declares unknown scope {rule.scope!r}")

    out: list[Finding] = []
    for folder in folders:
        scoped = RuleContext(**{**ctx.__dict__, "folder": folder})
        out.extend(_stamp(rule, rule.check(scoped) or []))
    return out


def _stamp(rule: Rule, findings: list[Finding]) -> list[Finding]:
    return [dataclasses.replace(f, severity=rule.severity) for f in findings]
