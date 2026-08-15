#!/usr/bin/env python3
"""
compute_tags.py — derive the CI-computed half of the tagging system.

Authors declare *domain* tags: what an agent is about. This derives *capability*,
*provenance*, and *assurance* tags from what an agent verifiably contains, so a
researcher can filter the catalog on facts rather than claims.

That separation is the point. ``auto:has-tests`` is worth something precisely
because nobody can type it into their own metadata.yaml — TAG-002 rejects any
attempt. Everything here is recomputed from the repository on every run.

Output: ``.auto-registry/agent-tags.json``

Usage:
    python .github/scripts/compute_tags.py            # write
    python .github/scripts/compute_tags.py --check    # drift gate
    python .github/scripts/compute_tags.py --report   # human summary
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

from dockerfile_parser import external_images
from rules.base import PolicyConfig

OUTPUT_PATH = Path(".auto-registry") / "agent-tags.json"


def _load_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (yaml.YAMLError, OSError, UnicodeDecodeError):
        return {}


def _tool_dirs(agent: Path) -> list[Path]:
    tools = agent / "tools"
    if not tools.is_dir():
        return []
    return sorted(d for d in tools.iterdir() if d.is_dir() and (d / "tool.yaml").is_file())


def _requests_gpu(tool_yaml: dict) -> bool:
    for infra in tool_yaml.get("infra") or []:
        if not isinstance(infra, dict):
            continue
        compute = infra.get("compute") or {}
        for bound in ("min_resources", "max_resources"):
            resources = compute.get(bound) or {}
            try:
                if int(resources.get("gpu", 0) or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def compute_for_agent(repo: Path, agent: Path, policy: PolicyConfig) -> dict:
    """Derive every computed tag for one agent folder."""
    meta = _load_yaml(agent / "metadata.yaml")
    tools = _tool_dirs(agent)
    tags: set[str] = set()

    # ── Capability ───────────────────────────────────────────────────────
    tags.add("auto:has-tools" if tools else "auto:no-tools")

    has_tests = any(
        any(t.glob("test_*.py")) or any(t.glob("*_test.py")) for t in tools
    )
    if has_tests:
        tags.add("auto:has-tests")

    if any((t / "example-input-files").is_dir() for t in tools):
        tags.add("auto:has-example-inputs")

    if (agent / "THIRD_PARTY_NOTICES.md").is_file():
        tags.add("auto:third-party-notices")

    if any(_requests_gpu(_load_yaml(t / "tool.yaml")) for t in tools):
        tags.add("auto:gpu-required")

    # ── Base image posture ───────────────────────────────────────────────
    images = []
    for df in sorted(agent.rglob("Dockerfile*")):
        try:
            text = df.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        images.extend(
            d.image for d in external_images(text)
            if d.image and not d.image.is_deployer_placeholder
        )

    if images:
        if all(img.is_docker_official for img in images):
            tags.add("auto:official-base-image")
        pinned = all(
            img.digest
            or img.tag_is_variable
            or (img.tag and img.tag.lower() not in policy.floating_tags)
            for img in images
        )
        if pinned:
            tags.add("auto:pinned-base-image")

    # ── Provenance ───────────────────────────────────────────────────────
    publisher = meta.get("publisher") or {}
    party = publisher.get("party") if isinstance(publisher, dict) else None
    if party in ("1p", "3p"):
        tags.add(f"party:{party}")

    # ── Assurance tier ───────────────────────────────────────────────────
    # Bronze is the floor every merged agent clears. Silver and gold reward
    # the things that make an agent maintainable by someone other than its
    # author: tests, reproducible builds, and worked examples.
    tier = "bronze"
    if has_tests and "auto:pinned-base-image" in tags:
        tier = "silver"
        if "auto:third-party-notices" in tags and "auto:has-example-inputs" in tags:
            tier = "gold"
    # A prompt-only agent has no build to pin or tool to test, so it is judged
    # on documentation alone and cannot be held below bronze for missing them.
    if not tools:
        tier = "bronze"
    tags.add(f"tier:{tier}")

    return {
        "name": agent.name,
        "path": str(agent.relative_to(repo)).replace("\\", "/"),
        "declared_tags": sorted(str(t) for t in (meta.get("tags") or [])),
        "computed_tags": sorted(tags),
        "tier": tier,
    }


def compute_all(repo: Path) -> dict:
    policy = PolicyConfig.load(repo)
    agents = sorted(
        d for d in (repo / "agents").iterdir()
        if d.is_dir() and d.name != "tmp" and (d / "metadata.yaml").is_file()
    )
    entries = [compute_for_agent(repo, a, policy) for a in agents]
    return {
        "_comment": (
            "Generated by .github/scripts/compute_tags.py. Computed tags are "
            "derived from repository contents; authors cannot declare them "
            "(TAG-002). Do not edit by hand."
        ),
        "schemaVersion": "1.0.0",
        "count": len(entries),
        "agents": entries,
    }


def render(data: dict) -> str:
    return json.dumps(data, indent=2) + "\n"


def summarize(data: dict) -> str:
    tiers = Counter(a["tier"] for a in data["agents"])
    capabilities = Counter(
        t for a in data["agents"] for t in a["computed_tags"]
        if t.startswith("auto:")
    )
    lines = [f"{data['count']} agent(s) tagged.", "", "Assurance tiers:"]
    for tier in ("gold", "silver", "bronze"):
        lines.append(f"  tier:{tier}: {tiers.get(tier, 0)}")
    lines += ["", "Capabilities:"]
    for tag, count in sorted(capabilities.items()):
        lines.append(f"  {tag}: {count}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--check", action="store_true",
                        help="Fail if the committed file differs from the computed one.")
    parser.add_argument("--report", action="store_true", help="Print a summary.")
    args = parser.parse_args()

    repo = Path(args.repo_root).resolve()
    data = compute_all(repo)

    if args.report:
        print(summarize(data))
        return 0

    target = repo / OUTPUT_PATH
    content = render(data)

    if args.check:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != content:
            print(
                f"{OUTPUT_PATH} is out of date.\n"
                f"Regenerate with:\n    python .github/scripts/compute_tags.py",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT_PATH} is up to date.")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}.")
    print(summarize(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
