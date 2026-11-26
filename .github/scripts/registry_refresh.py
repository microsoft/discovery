"""Suppress cosmetic registry changes and duplicate publication PRs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from catalog_validation.policy_checks import is_trusted_registry_refresh


REGISTRY_COLLECTIONS = {
    ".auto-registry/agent-registry.json": "entries",
    ".auto-registry/starter-kit-registry.json": "kits",
    ".auto-registry/agent-tags.json": "agents",
}


def semantic_payload(relative: str, data: object) -> dict:
    collection = REGISTRY_COLLECTIONS[relative]
    if (
        not isinstance(data, dict)
        or not isinstance(data.get(collection), list)
        or any(not isinstance(item, dict) for item in data[collection])
    ):
        raise ValueError(f"{relative} must contain a '{collection}' array of objects")

    payload = dict(data)
    if relative.endswith("/agent-registry.json"):
        payload.pop("generated_at", None)
    elif relative.endswith("/starter-kit-registry.json"):
        payload.pop("generatedAt", None)
        payload.pop("commitSha", None)
        payload["kits"] = [
            {key: value for key, value in kit.items() if key != "computedAt"}
            for kit in data["kits"]
        ]
    return payload


def prepare_changes(repo: Path) -> list[str]:
    changed = []
    unchanged = []
    for relative in REGISTRY_COLLECTIONS:
        tracked = subprocess.run(
            ["git", "ls-tree", "--name-only", "HEAD", "--", relative],
            cwd=repo, check=True, capture_output=True,
        ).stdout
        previous = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=repo, check=True, capture_output=True,
        ).stdout if tracked else None
        path = repo / relative
        if not path.is_file():
            if previous is not None or not relative.endswith("/starter-kit-registry.json"):
                raise FileNotFoundError(f"Generated registry is missing: {relative}")
            continue

        current = path.read_bytes()
        payload = semantic_payload(relative, json.loads(current))
        if previous is not None and payload == semantic_payload(relative, json.loads(previous)):
            unchanged.append((path, previous))
        else:
            changed.append(relative)

    for path, previous in unchanged:
        path.write_bytes(previous)
    return changed


def existing_refresh_prs(repository: str) -> list[int]:
    result = subprocess.run(
        [
            "gh", "api",
            f"repos/{repository}/pulls?state=open&base=main&per_page=100",
            "--paginate", "--slurp",
        ],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    pages = json.loads(result.stdout)
    if not isinstance(pages, list) or not pages or any(not isinstance(page, list) for page in pages):
        raise ValueError("GitHub returned an invalid paginated PR list")
    numbers = []
    for page in pages:
        for pr in page:
            head = pr["head"]
            if (
                pr["state"] == "open"
                and pr["base"]["ref"] == "main"
                and (head["repo"] or {}).get("full_name") == repository
                and is_trusted_registry_refresh(pr["user"]["login"], head["ref"])
            ):
                if type(pr["number"]) is not int or pr["number"] < 1:
                    raise ValueError("GitHub returned an invalid PR number")
                numbers.append(pr["number"])
    return numbers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--repository", required=True, help="GitHub owner/repository")
    args = parser.parse_args()
    try:
        changed = prepare_changes(args.repo_root)
        existing = existing_refresh_prs(args.repository) if changed else []
        publish = bool(changed) and not existing
        if existing:
            links = ", ".join(
                f"https://github.com/{args.repository}/pull/{number}"
                for number in existing
            )
            message = (
                f"Registry changes remain queued behind the existing refresh PR: {links}. "
                "Its reviewed snapshot will not be rewritten."
            )
        elif changed:
            message = "Registry payload changed: " + ", ".join(changed)
        else:
            message = "No registry payload changes; existing snapshot metadata preserved."
        print(message)
        if output := os.environ.get("GITHUB_OUTPUT"):
            with open(output, "a", encoding="utf-8") as stream:
                stream.write(f"publish={str(publish).lower()}\n")
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(summary, "a", encoding="utf-8") as stream:
                stream.write(f"## Registry publication\n\n{message}\n")
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"ERROR: registry publication check failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
