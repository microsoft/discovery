"""Read-only source-contribution checks; never export private state or make a release.

Run from the entry with ``python scripts/check_release.py``. This bounded scan is
not a secret-scanning service, license approval, public signature, or catalog CI.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import tomllib
from pathlib import Path
from urllib.parse import unquote

import yaml

EXCLUDED = {
    ".git", ".discovery", ".venv", "local-evidence", "__pycache__", ".pytest_cache",
    ".ruff_cache", "build", "dist", "runs", "htmlcov",
}
PRIVATE_EXTENSIONS = {".key", ".pem", ".pfx", ".p12", ".exe", ".dll", ".whl", ".zip"}
PATTERNS = {
    "absolute_user_path": re.compile(r"(?i)[a-z]:[/\\]+Users[/\\]+"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "storage_key": re.compile(r"(?i)AccountKey\s*=\s*[A-Za-z0-9+/]{40,}={0,2}"),
    "credential_url": re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.I),
}


def source_files(root: Path):
    """Never traverse the explicitly private archive, caches, or installed assets."""
    for base, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in EXCLUDED
                                and not d.endswith(".egg-info"))
        for name in sorted(filenames):
            path = Path(base) / name
            if name.endswith((".log", ".pyc", ".local.json")) or name in {".env", ".coverage"}:
                continue
            yield path


def check(root: Path) -> dict:
    root = root.resolve()
    findings, counts = [], {"files": 0, "bytes": 0, "python": 0, "json": 0, "toml": 0}
    required = [
        "agent.yaml", "metadata.yaml", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
        "skills/phy-openfoam/SKILL.md", "integrations/phy-openfoam.agent.md",
        "skills/phy-openfoam/scripts/project_results.py",
        "skills/phy-openfoam/scripts/render_report.py",
        "scripts/install-runtime.ps1", "scripts/install-workspace.ps1",
        "config/operator.example.json", "config/deployment.example.json",
        "tools/openfoam/Dockerfile", "tools/openfoam/LICENSE",
        "tools/openfoam/LICENSES/GPL-3.0-or-later.txt",
        "tools/openfoam/LICENSES/Gmsh-4.13-LICENSE.txt",
    ]
    for name in required:
        if not (root / name).is_file():
            findings.append({"path": name, "issue": "required_asset_missing"})
    # Do not silently hide a misplaced investigation using ignore/exclusion
    # rules. Curated benchmark/example inputs remain source; marked results,
    # report receipts and old workstation archives do not.
    for base, directories, filenames in os.walk(root, followlinks=False):
        directory = Path(base)
        for name in directories:
            if name == "local-evidence" or name.startswith("results-"):
                findings.append({"path": (directory / name).relative_to(root).as_posix(),
                                 "issue": "generated_results_inside_contribution"})
        for name in ("results-manifest.json", "report-receipt.json", "evidence-snapshot.json"):
            if name in filenames:
                findings.append({"path": (directory / name).relative_to(root).as_posix(),
                                 "issue": "generated_results_inside_contribution"})
        directories[:] = sorted(d for d in directories if d not in EXCLUDED
                                and not d.startswith("results-") and not d.endswith(".egg-info"))
    for path in source_files(root):
        relative = path.relative_to(root).as_posix()
        counts["files"] += 1
        if path.is_symlink():
            findings.append({"path": relative, "issue": "symlink_requires_review"})
            continue
        data = path.read_bytes()
        counts["bytes"] += len(data)
        if path.suffix.lower() in PRIVATE_EXTENSIONS:
            findings.append({"path": relative, "issue": "binary_or_private_asset"})
            continue
        try:
            text = data.decode("utf-8")
            if "\0" in text:
                raise ValueError("NUL is not permitted in source text")
            if path.suffix == ".py":
                ast.parse(text, filename=relative)
                counts["python"] += 1
            elif path.suffix == ".json":
                json.loads(text)
                counts["json"] += 1
            elif path.suffix in {".yaml", ".yml"}:
                yaml.safe_load(text)
            elif path.suffix == ".toml":
                tomllib.loads(text)
                counts["toml"] += 1
        except (UnicodeError, ValueError, SyntaxError, yaml.YAMLError) as exc:
            findings.append({"path": relative, "issue": "syntax_or_encoding", "detail": type(exc).__name__})
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for kind, pattern in PATTERNS.items():
                if pattern.search(line):
                    # Do not echo matched values, even in a failure.
                    findings.append({"path": relative, "line": number, "issue": kind})
        if path.suffix == ".md":
            prose = re.sub(r"```[^\n]*\n.*?```", "", text, flags=re.S)
            for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^\s)]+)\)", prose):
                if target.startswith(("https:", "http:", "mailto:", "#")):
                    continue
                resolved = (path.parent / unquote(target.split("#", 1)[0])).resolve()
                if (not resolved.is_relative_to(root)
                        or "local-evidence" in resolved.relative_to(root).parts):
                    findings.append({"path": relative, "issue": "link_outside_public_entry"})
                elif not resolved.exists():
                    findings.append({"path": relative, "issue": "missing_link", "target": target})
    return {"scope": "bounded_source_check_not_publication_approval", "counts": counts,
            "findings": findings, "ok": not findings}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    result = check(args.entry)
    print(json.dumps(result, indent=1))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())