"""README and authored-document validation for agent folders."""

from __future__ import annotations

import re
from pathlib import Path

from .findings import Failure


def _has_section(content: str, *headings: str) -> bool:
    return any(
        re.search(
            rf"^##\s+{re.escape(heading)}",
            content,
            re.MULTILINE | re.IGNORECASE,
        )
        for heading in headings
    )


def check_documentation(repo: Path, folders: set[Path]) -> list[Failure]:
    failures: list[Failure] = []

    for folder in folders:
        abs_folder = repo / folder
        is_agent = len(folder.parts) >= 2 and folder.parts[0] == "agents"
        readme_path = abs_folder / "README.md"
        if not readme_path.exists():
            continue

        try:
            content = readme_path.read_text(encoding="utf-8")
        except OSError:
            continue

        readme_rel = str(readme_path.relative_to(repo))
        if len(content.strip()) < 50:
            failures.append(Failure(
                "DOC-001",
                readme_rel,
                "README.md is missing or empty. Every agent must include a README.md.",
            ))
            continue

        if not re.search(r"^#\s+\S", content, re.MULTILINE):
            failures.append(Failure(
                "DOC-002",
                readme_rel,
                "README.md must begin with a top-level heading (# Agent Name).",
            ))
        if not _has_section(content, "Overview", "Description"):
            failures.append(Failure(
                "DOC-003",
                readme_rel,
                "README.md must include a '## Overview' or '## Description' "
                "section explaining what the agent does.",
            ))
        if not _has_section(content, "Usage", "Getting Started"):
            failures.append(Failure(
                "DOC-004",
                readme_rel,
                "README.md must include a '## Usage' or '## Getting Started' section.",
            ))
        if not _has_section(content, "Prerequisites"):
            failures.append(Failure(
                "DOC-005",
                readme_rel,
                "README.md must include a '## Prerequisites' section listing any "
                "required permissions, services, or credentials.",
            ))

        if is_agent:
            if not _has_section(content, "Architecture", "How it works"):
                failures.append(Failure(
                    "DOC-101",
                    readme_rel,
                    "README.md must include an '## Architecture' or '## How it "
                    "works' section.",
                ))
            if (abs_folder / "tools").is_dir() and not _has_section(content, "Tools"):
                failures.append(Failure(
                    "DOC-102",
                    readme_rel,
                    "README.md must include a '## Tools' section describing each "
                    "tool when a tools/ directory is present.",
                ))
            if not _has_section(content, "Configuration", "Parameters"):
                failures.append(Failure(
                    "DOC-103",
                    readme_rel,
                    "README.md must include a '## Configuration' or '## Parameters' "
                    "section documenting agent inputs.",
                ))
            if not _has_section(content, "Known Limitations", "Limitations"):
                failures.append(Failure(
                    "DOC-104",
                    readme_rel,
                    "README.md must include a '## Known Limitations' section.",
                ))
            if not _has_section(content, "Contributing") and "CONTRIBUTING.md" not in content:
                failures.append(Failure(
                    "DOC-105",
                    readme_rel,
                    "README.md must include a '## Contributing' section or a link "
                    "to CONTRIBUTING.md.",
                ))

        document_paths = [readme_path]
        for filename in ("metadata.yaml", "agent.yaml"):
            document_path = abs_folder / filename
            if document_path.exists():
                document_paths.append(document_path)
        for document_path in document_paths:
            try:
                text = document_path.read_text(encoding="utf-8")
            except OSError:
                continue
            text_without_fences = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
            for marker in ("TODO", "FIXME", "XXX"):
                match = re.search(rf"\b{marker}\b", text_without_fences)
                if match:
                    line = text_without_fences[:match.start()].count("\n") + 1
                    failures.append(Failure(
                        "DOC-006",
                        str(document_path.relative_to(repo)),
                        f"Placeholder marker '{marker}' found at line {line}. Resolve "
                        f"or remove '{marker}' references before merging.",
                        line=line,
                    ))
                    break

    return failures