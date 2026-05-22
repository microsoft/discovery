#!/usr/bin/env python3
"""
check_agent_removal_impact.py — PR gate for agent path removals.

Detects when a PR removes or renames an agent path from the catalog and blocks merge
if any active starter kit has a required:true reference to that removed path.

Gate options:
  Option A — Fix in PR: All affected active kits are updated in the PR, and the
             post-change kit state re-evaluated against the head-branch registry shows
             that each impacted required ref is gone, replaced by a valid agent, or the
             kit is now lifecycle:archived.
  Option B — Maintainer override: A user with write/maintain/admin permission on the
             repo applies the label "starter-kit-impact-approved" to the PR.
             Only available for non-fork PRs (label API is unavailable on forks).

Usage (called from check-agent-removal-impact.yml):
  python .github/scripts/check_agent_removal_impact.py \\
    --repo-root . \\
    --base-sha <sha> \\
    --pr-number <number> \\
    --github-token <token> \\
    --repo <owner/repo>
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


def load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def load_yaml_safe(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


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
        if not page_data:
            break
        results.extend(page_data)
        if len(page_data) < 100:
            break
        page += 1
    return results


def get_base_registry_paths(repo_root: Path, base_sha: str) -> set[str]:
    """Read .auto-registry/agent-registry.json at base_sha via git show and extract agent paths."""
    try:
        result = subprocess.run(
            ["git", "show", f"{base_sha}:.auto-registry/agent-registry.json"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        if result.returncode != 0:
            print(f"WARNING: Could not read base registry at {base_sha}: {result.stderr.strip()}")
            return set()
        registry = json.loads(result.stdout)
        return {
            e["path"]
            for e in registry.get("entries", [])
            if e.get("type") == "agent"
        }
    except Exception as e:
        print(f"WARNING: Error reading base registry: {e}")
        return set()


def get_head_registry_paths(repo_root: Path) -> set[str]:
    """Run update_registry.py on current checkout; return set of agent path strings."""
    script = repo_root / ".github" / "scripts" / "update_registry.py"
    if not script.exists():
        raise FileNotFoundError(f"update_registry.py not found: {script}")
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--repo-root", str(repo_root), "--output", tmp_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"update_registry.py failed:\n{result.stderr}")
        registry = load_json(Path(tmp_path))
        return {
            e["path"]
            for e in registry.get("entries", [])
            if e.get("type") == "agent"
        }
    finally:
        os.unlink(tmp_path)


def get_active_kits(repo_root: Path) -> list[tuple[str, dict]]:
    """Return list of (kit_rel_path, manifest) for all active kits.

    kit_rel_path is repo-root-relative, e.g. 'starter-kits/protein-structure-analysis'.
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
        try:
            manifest = load_json(plugin_path)
        except Exception:
            continue
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
        except Exception as e:
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
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    try:
        pr_data = github_get(url, token)
        return [label["name"] for label in pr_data.get("labels", [])]
    except Exception as e:
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
                event.get("event") == "labeled"
                and event.get("label", {}).get("name") == label
            ):
                return event.get("actor", {}).get("login")
        return None
    except Exception as e:
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
    except Exception as e:
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
        return False, "Fork PRs cannot use Option B (label API unavailable on forks). Use Option A."
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


def post_pr_comment(token: str, repo: str, pr_number: int, body: str) -> None:
    """Post a comment to the PR."""
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    data = json.dumps({"body": body}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "discovery-pr-ci",
        },
    )
    try:
        with urllib.request.urlopen(req):
            pass
    except Exception as e:
        print(f"WARNING: Could not post PR comment: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check agent removal impact on starter kits.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--base-sha", required=True, help="Base commit SHA (PR base branch tip)")
    parser.add_argument("--pr-number", type=int, help="PR number (for Option B and comment posting)")
    parser.add_argument("--github-token", help="GitHub token (for API calls)")
    parser.add_argument("--repo", help="Owner/repo slug, e.g. owner/repo")
    parser.add_argument("--is-fork", action="store_true", help="Set if PR is from a fork")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()

    print(f"Base SHA: {args.base_sha}")
    print("Loading base registry...")
    base_paths = get_base_registry_paths(repo_root, args.base_sha)
    print(f"  Base registry: {len(base_paths)} agent(s)")

    print("Building head registry from current checkout...")
    try:
        head_paths = get_head_registry_paths(repo_root)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"  Head registry: {len(head_paths)} agent(s)")

    removed_paths = base_paths - head_paths
    if not removed_paths:
        print("\n✓ No agent paths removed. No starter kit impact.")
        sys.exit(0)

    print(f"\nRemoved agent paths: {sorted(removed_paths)}")

    # Find active kits impacted by removals
    active_kits = get_active_kits(repo_root)
    impacted = find_impacted_kits(active_kits, removed_paths)

    if not impacted:
        print("\n✓ No active starter kits have required refs to removed agents.")
        # Informational: check archived/optional refs
        for kit_name, manifest in active_kits:
            optional_impacted = [
                r["ref"] for r in manifest.get("agentRefs", [])
                if r.get("required") is False and r.get("ref") in removed_paths
            ]
            if optional_impacted:
                print(
                    f"  INFO: [{kit_name}] optional refs affected (no block): {optional_impacted}"
                )
        sys.exit(0)

    print(f"\n⚠ {len(impacted)} active kit(s) have required refs to removed agents:")
    for kit_name, broken_refs in impacted:
        print(f"  [{kit_name}]: {broken_refs}")

    # Option A: check if all affected kits are fixed in this PR
    print("\nChecking Option A (fix in PR)...")
    option_a_ok, a_issues = check_option_a_resolved(repo_root, impacted, head_paths)
    if option_a_ok:
        print("✓ Option A satisfied: all impacted kits are resolved in this PR.")
        sys.exit(0)
    print(f"  Option A not satisfied: {len(a_issues)} unresolved issue(s):")
    for issue in a_issues:
        print(f"    - {issue}")

    # Option B: maintainer override label
    print("\nChecking Option B (maintainer override)...")
    option_b_ok, b_reason = check_option_b(
        args.github_token, args.repo, args.pr_number, args.is_fork
    )
    if option_b_ok:
        print(f"✓ Option B satisfied: {b_reason}")
        sys.exit(0)
    print(f"  Option B not satisfied: {b_reason}")

    # Build failure message
    impact_lines = []
    for kit_rel_path, broken_refs in impacted:
        impact_lines.append(f"- **{kit_rel_path}**: required agents removed: `{', '.join(broken_refs)}`")

    failure_message = (
        "## ❌ Starter Kit Impact: Agent Removal Blocked\n\n"
        "This PR removes agent(s) that are referenced as `required: true` by active starter kits:\n\n"
        + "\n".join(impact_lines)
        + "\n\n**To unblock this PR, choose one of:**\n\n"
        "### Option A — Fix in PR\n"
        "Update each affected starter kit in this PR:\n"
        "- Replace the removed agent ref with a valid one, **or**\n"
        "- Set `lifecycle: \"archived\"` on the kit, **or**\n"
        "- Remove the `required: true` flag from the affected ref\n\n"
        "The CI script will re-evaluate the kit state against the head-branch registry.\n\n"
        "### Option B — Maintainer Override (non-fork PRs only)\n"
        f"A user with **write, maintain, or admin** permission on `{args.repo or 'this repository'}` "
        "must apply the label `starter-kit-impact-approved` to this PR.\n\n"
        "> ⚠️ Fork PRs must use Option A (label API is unavailable on forks).\n"
    )

    print(f"\n{'='*60}")
    print("GATE FAILED — merge blocked")
    print(f"{'='*60}")

    if args.github_token and args.repo and args.pr_number:
        post_pr_comment(args.github_token, args.repo, args.pr_number, failure_message)
        print("Posted failure comment to PR.")

    print("\n" + failure_message)
    sys.exit(1)


if __name__ == "__main__":
    main()
