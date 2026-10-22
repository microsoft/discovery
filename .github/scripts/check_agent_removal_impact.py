#!/usr/bin/env python3
"""
check_agent_removal_impact.py — PR gate for agent path removals.

Evaluates the exact PR head against a trusted base registry. Returns a failing
gate result when removal/rename leaves active kits requiring an absent agent.
The required workflow check, not this script or a diagnostic comment, gates merge.

Gate options:
  Option A — Fix in PR: All affected active kits are updated in the PR, and the
             post-change kit state re-evaluated against the head-branch registry shows
             that each impacted required ref is gone, replaced by a valid agent, or the
             kit is now lifecycle:archived.
  Option B — Maintainer override: A user with write/maintain/admin permission on the
             repo applies the label "starter-kit-impact-approved" and reruns the
             check. Only available for non-fork PRs, as repository policy.

The CLI performs only GET API requests and never publishes comments, even with
a token. GITHUB_TOKEN (or --github-token) is used only to verify Option B.
--report-json writes a schema-version-1 result as well as logging it. Passing
validation exits 0; blocked/error results exit 1. Workflow classification creates
not_applicable records separately, without invoking this validator.

Workflow invocation (Bash, from the workspace root):
  python trusted/.github/scripts/check_agent_removal_impact.py \\
    --repo-root pr \\
    --base-registry-root trusted \\
    --base-sha <sha> \\
    --pr-number <number> \\
    --repo <owner/repo> \\
    --report-json "$RUNNER_TEMP/agent-removal-report/agent-removal-results.json"

Add --is-fork when head and base repositories differ. Report-capable code must
already exist on the trusted base; never execute the PR copy as a fallback.
PR Review Report consumes the artifact and posts diagnostic feedback separately.
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

import update_registry
from agent_removal_report import MAX_REPORT_BYTES, MAX_STRING, catalog_path, result, validate_report


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def github_get(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "discovery-pr-ci",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def github_get_paged(url: str, token: str) -> list:
    """Fetch all pages of a GitHub API list endpoint and return the combined results."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "discovery-pr-ci",
    }
    results = []
    page = 1
    while True:
        paged_url = url + ("&" if "?" in url else "?") + f"per_page=100&page={page}"
        req = urllib.request.Request(paged_url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            page_data = json.loads(resp.read().decode())
        if not isinstance(page_data, list) or not all(isinstance(item, dict) for item in page_data):
            raise ValueError("Expected a complete page of GitHub API objects.")
        if not page_data:
            break
        results.extend(page_data)
        if len(page_data) < 100:
            break
        page += 1
    return results


def _parse_registry_agent_paths(raw: str) -> set[str]:
    registry = json.loads(raw)
    if not isinstance(registry, dict) or not isinstance(registry.get("entries"), list):
        raise ValueError("Base registry must contain an entries array.")
    paths = set()
    for entry in registry["entries"]:
        if not isinstance(entry, dict):
            raise ValueError("Base registry entries must be objects.")
        if entry.get("type") == "agent":
            if not catalog_path(entry.get("path"), "agents"):
                raise ValueError("Base registry contains an invalid agent path.")
            paths.add(entry["path"])
    return paths


def get_base_registry_paths(
    repo_root: Path,
    base_sha: str,
    base_registry_root: Path | None = None,
) -> set[str]:
    """Return agent paths recorded in the base (pre-PR) registry.

    When ``base_registry_root`` is provided — the trusted base checkout — the
    committed ``agent-registry.json`` is read directly from disk. That is the
    reliable source for fork PRs, whose checkout usually does not contain the
    upstream base commit, so ``git show <base_sha>`` would silently yield
    nothing and hide every removal. Otherwise the file is read from ``base_sha``
    via ``git show`` inside ``repo_root``.

    A base registry that exists but cannot be read or parsed is a hard error:
    returning an empty set would make removals invisible and let the gate pass a
    PR that breaks starter-kit references.
    """
    if base_registry_root is not None:
        registry_path = base_registry_root / ".auto-registry" / "agent-registry.json"
        if not registry_path.is_file():
            raise RuntimeError(
                f"Base registry not found at {registry_path}. The trusted base "
                f"checkout must contain .auto-registry/agent-registry.json so "
                f"agent removals can be detected."
            )
        try:
            return _parse_registry_agent_paths(registry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError) as e:
            raise RuntimeError(
                f"Base registry at {registry_path} could not be parsed: {e}"
            ) from e

    result = subprocess.run(
        ["git", "show", f"{base_sha}:.auto-registry/agent-registry.json"],
        capture_output=True, text=True, cwd=str(repo_root),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not read base registry at {base_sha}: {result.stderr.strip()}. "
            f"Refusing to continue, since an unreadable base registry would hide "
            f"agent removals. Supply --base-registry-root pointing at a base "
            f"checkout for fork PRs."
        )
    try:
        return _parse_registry_agent_paths(result.stdout)
    except (ValueError, KeyError) as e:
        raise RuntimeError(
            f"Base registry at {base_sha} could not be parsed: {e}"
        ) from e


def get_head_registry_paths(repo_root: Path) -> set[str]:
    """Return agent paths from the PR checkout that survive registry generation.

    The base set comes from the committed ``agent-registry.json``, which is
    produced by ``update_registry``. To compare like-for-like, the head set is
    derived through the *same* validated generation path: a directory counts as
    present only if ``update_registry.build_entry`` yields a valid entry (valid
    metadata with a name). A folder that merely contains a ``metadata.yaml`` but
    would be rejected by registry generation is therefore treated as absent, so
    a malformed or incomplete agent cannot mask a genuine removal.
    """
    paths: set[str] = set()
    agents_dir = repo_root / "agents"
    if not agents_dir.is_dir():
        return paths
    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        rel_path = f"agents/{agent_dir.name}"
        try:
            entry = update_registry.build_entry(str(agent_dir), rel_path, "agent")
        except (ValueError, TypeError, AttributeError) as exc:
            if isinstance(exc.__cause__, OSError):
                raise RuntimeError(f"Could not read {rel_path}: {exc}") from exc
            print(
                f"WARNING: {rel_path} does not produce a valid registry entry "
                f"and is treated as absent: {exc}"
            )
            continue
        if entry is not None:
            paths.add(entry["path"])
    return paths


def get_active_kits(repo_root: Path) -> list[tuple[str, dict]]:
    """Return list of (kit_rel_path, manifest) for all active kits.

    kit_rel_path is repo-root-relative, e.g. 'starter-kits/protein-structure-analysis'.
    Malformed/unreadable manifests are fatal, not silently missing kits.
    """
    result = []
    base_dir = repo_root / "starter-kits"
    if not base_dir.is_dir():
        return result
    for kit_dir in sorted(base_dir.iterdir()):
        if not kit_dir.is_dir():
            continue
        plugin_path = kit_dir / "kit.json"
        if not plugin_path.exists():
            continue
        manifest = load_json(plugin_path)
        if (
            not isinstance(manifest, dict)
            or not isinstance(manifest.get("agentRefs", []), list)
            or not all(
                isinstance(ref, dict) and isinstance(ref.get("ref"), str)
                for ref in manifest.get("agentRefs", [])
            )
        ):
            raise ValueError(f"{plugin_path}: invalid starter-kit manifest.")
        if manifest.get("lifecycle") == "active":
            result.append((f"starter-kits/{kit_dir.name}", manifest))
    return result


def find_impacted_kits(
    active_kits: list[tuple[str, dict]],
    removed_paths: set[str],
) -> list[tuple[str, list[str]]]:
    """Return list of (kit_rel_path, [impacted_required_refs]) for kits impacted by removed_paths."""
    impacted = []
    for kit_rel_path, manifest in active_kits:
        agent_refs = manifest.get("agentRefs", [])
        broken_required = [
            r["ref"] for r in agent_refs
            if r.get("required") is True and r.get("ref") in removed_paths
        ]
        if broken_required:
            impacted.append((kit_rel_path, broken_required))
    return impacted


def check_option_a_resolved(
    repo_root: Path,
    impacted: list[tuple[str, list[str]]],
    head_registry_paths: set[str],
) -> tuple[bool, list[str]]:
    """
    Check Option A: all impacted kits are fixed in this PR.
    For each impacted kit, re-load its current kit.json and verify that
    none of the originally broken refs are still required:true refs pointing to
    absent agents.
    Returns (all_resolved, list_of_unresolved_issues).
    """
    unresolved = []
    for kit_rel_path, _ in impacted:
        plugin_path = repo_root / kit_rel_path / "kit.json"
        if not plugin_path.exists():
            # Kit was deleted — that resolves the impact
            continue
        try:
            current_manifest = load_json(plugin_path)
        except (OSError, ValueError) as e:
            unresolved.append(f"{kit_rel_path}: could not read kit.json: {e}")
            continue

        manifest = current_manifest
        lifecycle = manifest.get("lifecycle", "active")

        # Archived kits are resolved
        if lifecycle == "archived":
            continue

        # Check that no required:true refs are absent from head registry
        still_broken = [
            r["ref"]
            for r in manifest.get("agentRefs", [])
            if r.get("required") is True and r.get("ref", "") not in head_registry_paths
        ]
        if still_broken:
            unresolved.append(
                f"{kit_rel_path}: still has required refs absent from head registry: {still_broken}"
            )

    return (len(unresolved) == 0), unresolved


def get_pr_labels(token: str, repo: str, pr_number: int) -> list[str]:
    """Return list of label names on the PR."""
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/labels"
    try:
        return [label["name"] for label in github_get_paged(url, token)]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"WARNING: Could not fetch PR labels: {e}")
        return []


def get_label_applier(token: str, repo: str, pr_number: int, label: str) -> str | None:
    """Return the login of the user who last applied `label` to the PR, or None.
    Paginates through all events to handle PRs with long event histories.
    """
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/events"
    try:
        events = github_get_paged(url, token)
        for event in reversed(events):
            if (
                event.get("event") in {"labeled", "unlabeled"}
                and event.get("label", {}).get("name") == label
            ):
                return event.get("actor", {}).get("login") if event["event"] == "labeled" else None
        return None
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"WARNING: Could not fetch PR events: {e}")
        return None


def get_user_repo_permission(token: str, repo: str, username: str) -> str:
    """Return the user's permission level: admin/maintain/write/read/none."""
    url = f"https://api.github.com/repos/{repo}/collaborators/{username}/permission"
    try:
        data = github_get(url, token)
        return data.get("permission", "none")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "none"
        print(f"WARNING: Could not fetch permission for {username}: {e}")
        return "none"
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"WARNING: Could not fetch permission for {username}: {e}")
        return "none"


def check_option_b(
    token: str | None,
    repo: str | None,
    pr_number: int | None,
    is_fork: bool,
) -> tuple[bool, str]:
    """
    Check Option B: maintainer override via label.
    Returns (approved, reason_string).
    """
    if is_fork:
        return False, "Repository policy limits Option B to non-fork PRs. Use Option A."
    if not token or not repo or not pr_number:
        return False, "GitHub token, repo, and PR number are required for Option B check."

    label = "starter-kit-impact-approved"
    labels = get_pr_labels(token, repo, pr_number)
    if label not in labels:
        return False, f"Label '{label}' not present on PR."

    applier = get_label_applier(token, repo, pr_number, label)
    if not applier:
        return False, f"Could not determine who applied label '{label}'."

    permission = get_user_repo_permission(token, repo, applier)
    if permission not in ("admin", "maintain", "write"):
        return False, (
            f"Label '{label}' was applied by @{applier} who has permission '{permission}'. "
            f"Requires write, maintain, or admin."
        )

    return True, f"Label '{label}' applied by @{applier} (permission: {permission}). Override accepted."


def evaluate(
    repo_root: Path, base_sha: str, base_registry_root: Path | None = None,
    *, token: str | None = None, repo: str | None = None,
    pr_number: int | None = None, is_fork: bool = False,
) -> dict:
    if not repo_root.is_dir():
        raise RuntimeError(f"PR checkout not found: {repo_root}")
    base_paths = get_base_registry_paths(repo_root, base_sha, base_registry_root)
    head_paths = get_head_registry_paths(repo_root)
    removed = base_paths - head_paths
    print(f"Base registry: {len(base_paths)} agent(s); head registry: {len(head_paths)} agent(s)")
    print(f"Removed agent paths: {sorted(removed)}")
    if not removed:
        return result("success")
    impacted = find_impacted_kits(get_active_kits(repo_root), removed)
    details = [{"path": path, "required_refs": sorted(set(refs))} for path, refs in impacted]
    if not impacted:
        return result("success", removed_paths=sorted(removed))
    resolved, issues = check_option_a_resolved(repo_root, impacted, head_paths)
    if resolved:
        return result("success", removed_paths=sorted(removed))
    approved, reason = check_option_b(token, repo, pr_number, is_fork)
    return result(
        "success" if approved else "blocked", removed_paths=sorted(removed),
        impacted_kits=details, issues=[] if approved else issues,
        approved=approved, reason=reason,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Check agent removal impact on starter kits.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument(
        "--base-registry-root",
        help="Path to a trusted base checkout; its committed "
             ".auto-registry/agent-registry.json is used as the base registry. "
             "Preferred over --base-sha for fork PRs, whose checkout may not "
             "contain the base commit.",
    )
    parser.add_argument("--base-sha", required=True, help="Base commit SHA (PR base branch tip)")
    parser.add_argument("--pr-number", type=int, help="PR number (for Option B)")
    parser.add_argument(
        "--github-token", default=os.environ.get("GITHUB_TOKEN"),
        help="Read-only token for Option B GET requests (default: GITHUB_TOKEN); never posts comments",
    )
    parser.add_argument("--repo", help="Owner/repo slug, e.g. owner/repo")
    parser.add_argument("--is-fork", action="store_true", help="Set if PR is from a fork")
    parser.add_argument("--report-json", type=Path, help="Also write the schema-version-1 diagnostic result as JSON")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    base_registry_root = (
        Path(args.base_registry_root).resolve() if args.base_registry_root else None
    )

    try:
        report = evaluate(
            repo_root, args.base_sha, base_registry_root, token=args.github_token,
            repo=args.repo, pr_number=args.pr_number, is_fork=args.is_fork,
        )
        validate_report(report)
        if len(json.dumps(report, indent=2).encode("utf-8")) > MAX_REPORT_BYTES:
            raise ValueError("Removal report exceeds the size limit.")
    except (RuntimeError, OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        report = result("error", issues=[str(e)[:MAX_STRING] or type(e).__name__])
    print(json.dumps(report, indent=2))
    if args.report_json:
        try:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            args.report_json.write_bytes(json.dumps(report, indent=2).encode("utf-8"))
        except OSError as e:
            print(f"ERROR: Could not write removal report: {e}", file=sys.stderr)
            sys.exit(1)
    sys.exit(report["exit_code"])


if __name__ == "__main__":
    main()
