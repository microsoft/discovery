"""Classification of a validated change for reporting and PR labels."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from image_inspector import is_image_path

from .schemas import load_json, load_yaml


@dataclass(frozen=True)
class ContributionSummary:
    has_agents: bool
    has_docs_only: bool
    has_1p: bool
    has_3p: bool
    image_files: list[str]


def _party_values(
    repo: Path,
    agent_folders: set[Path],
    kit_folders: set[Path],
) -> set[str]:
    parties: set[str] = set()
    for folder in agent_folders:
        data, _ = load_yaml(repo / folder / "metadata.yaml")
        if not isinstance(data, dict):
            continue
        publisher = data.get("publisher") or {}
        if isinstance(publisher, dict) and publisher.get("party") in {"1p", "3p"}:
            parties.add(publisher["party"])

    for folder in kit_folders:
        try:
            manifest = load_json(repo / folder / "kit.json")
        except (OSError, ValueError):
            continue
        if isinstance(manifest, dict) and manifest.get("party") in {"1p", "3p"}:
            parties.add(manifest["party"])
    return parties


def classify_contribution(
    repo: Path,
    changed_files: list[str],
    agent_folders: set[Path],
    kit_folders: set[Path],
) -> ContributionSummary:
    normalized_files = [path.replace("\\", "/") for path in changed_files]
    parties = _party_values(repo, agent_folders, kit_folders)
    image_files = sorted(
        rel
        for rel, normalized in zip(changed_files, normalized_files)
        if normalized.startswith(("agents/", "starter-kits/"))
        and is_image_path(rel)
        and (repo / rel).is_file()
    )
    return ContributionSummary(
        has_agents=any(
            path.startswith("agents/") and not path.startswith("agents/tmp/")
            for path in normalized_files
        ),
        has_docs_only=(
            bool(normalized_files)
            and all(path.startswith("docs/schemas/") for path in normalized_files)
        ),
        has_1p="1p" in parties,
        has_3p="3p" in parties,
        image_files=image_files,
    )