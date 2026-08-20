"""Legacy policy checks that are not yet modular rules."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from model_weights_sniffer import MODEL_WEIGHT_EXTENSIONS, sniff

from .contributor_scope import is_trusted_registry_refresh
from .findings import Failure
from .schemas import load_yaml


MODEL_WEIGHT_MAX_BYTES = 5 * 1024 ** 3
PICKLE_ALLOWLIST = frozenset({
    "torch", "torch._utils", "torch.nn", "torch.nn.modules",
    "torch.nn.parameter", "torch.storage", "torch._tensor",
    "collections", "collections.abc",
    "numpy", "numpy.core.multiarray", "numpy.core.numeric",
})

_BLOCKED_FILENAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
_BLOCKED_BASENAME_SUFFIXES = (".swp", ".swo", ".bak", "~")
_BLOCKED_PREFIXES = (".idea/", ".vs/", ".vscode/.cache/")


def _is_env_artefact(rel: str) -> bool:
    name = Path(rel).name
    return name == ".env" or name.startswith(".env.")


def _is_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true"


def _is_lfs_tracked(repo: Path, rel_path: str) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "check-attr", "filter", "--", rel_path],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip().endswith(": lfs")


def _is_lfs_tracked_strict(
    repo: Path,
    rel_path: str,
    extension: str,
    tracker: Callable[[Path, str], bool | None] = _is_lfs_tracked,
) -> bool:
    result = tracker(repo, rel_path)
    if result is not None:
        return result
    if _is_ci():
        print(
            f"WARNING: could not determine LFS tracking status for {rel_path} "
            f"(extension {extension}) in CI; failing closed per POL-009.",
            file=sys.stderr,
        )
        return False
    print(
        f"WARNING: could not determine LFS tracking status for {rel_path} "
        f"(extension {extension}); allowing in non-CI mode (best-effort).",
        file=sys.stderr,
    )
    return True


def _picklescan_unsafe_imports(path: Path) -> list[str]:
    try:
        from picklescan.scanner import scan_file_path  # type: ignore
    except ImportError:
        return [
            "picklescan package is not installed; POL-009 requires it to "
            "validate pickle-bearing checkpoints. Install `picklescan` in "
            "the validator environment (the CI workflow does this)."
        ]

    try:
        result = scan_file_path(str(path))
    except Exception as error:
        return [f"picklescan error: {error}"]

    unsafe: list[str] = []
    for imported_global in getattr(result, "globals", []) or []:
        module = getattr(imported_global, "module", "") or ""
        name = getattr(imported_global, "name", "") or ""
        if not module:
            continue
        root = module.split(".")[0]
        if module in PICKLE_ALLOWLIST or root in PICKLE_ALLOWLIST:
            continue
        unsafe.append(f"{module}.{name}")
    return unsafe


def check_model_weights(repo: Path, changed_files: list[str]) -> list[Failure]:
    failures: list[Failure] = []
    for rel in changed_files:
        extension = Path(rel).suffix.lower()
        if extension not in MODEL_WEIGHT_EXTENSIONS:
            continue
        path = repo / rel
        if not path.is_file():
            continue

        if not _is_lfs_tracked_strict(repo, rel, extension):
            failures.append(Failure(
                "POL-009",
                rel,
                "Model-weight files must be Git-LFS tracked. Add an entry to "
                ".gitattributes (or confirm the existing pattern matches) and "
                "re-commit with `git lfs track`.",
            ))
            continue

        try:
            size = path.stat().st_size
        except OSError as error:
            failures.append(Failure("POL-009", rel, f"Could not stat file: {error}"))
            continue
        if size > MODEL_WEIGHT_MAX_BYTES:
            failures.append(Failure(
                "POL-009",
                rel,
                f"Model-weight file is {size} bytes, exceeding the "
                f"{MODEL_WEIGHT_MAX_BYTES} byte (5 GB) cap. Host it externally "
                "and reference it from the Dockerfile instead.",
            ))
            continue

        valid, detail = sniff(path)
        if not valid:
            failures.append(Failure(
                "POL-009",
                rel,
                f"Model-weight header validation failed: {detail}",
            ))
            continue

        if extension in {".pt", ".pth", ".ckpt"}:
            unsafe = _picklescan_unsafe_imports(path)
            if unsafe:
                preview = ", ".join(unsafe[:5])
                more = "" if len(unsafe) <= 5 else f" (+{len(unsafe) - 5} more)"
                failures.append(Failure(
                    "POL-009",
                    rel,
                    f"picklescan flagged disallowed pickle imports: {preview}{more}. "
                    "Re-export the checkpoint with safetensors or remove the "
                    "unsafe globals.",
                ))
    return failures


def _check_folder_policy(repo: Path, folder: Path) -> list[Failure]:
    failures: list[Failure] = []
    abs_folder = repo / folder

    metadata_path = abs_folder / "metadata.yaml"
    if metadata_path.exists():
        data, _ = load_yaml(metadata_path)
        if isinstance(data, dict):
            description = data.get("description", "") or ""
            if not 10 <= len(str(description).strip()) <= 500:
                failures.append(Failure(
                    "POL-004",
                    str(metadata_path.relative_to(repo)),
                    "metadata.yaml: 'description' must be between 10 and 500 characters.",
                ))

    readme_path = abs_folder / "README.md"
    if readme_path.exists() and readme_path.stat().st_size < 100:
        failures.append(Failure(
            "POL-005",
            str(readme_path.relative_to(repo)),
            "README.md appears to be empty or too short. Provide a meaningful usage guide.",
        ))
    return failures


def _check_hidden_artifacts(repo: Path, changed_files: list[str]) -> list[Failure]:
    failures: list[Failure] = []
    for rel in changed_files:
        if not (repo / rel).exists():
            continue
        name = Path(rel).name
        normalized = rel.replace("\\", "/")
        blocked = (
            name in _BLOCKED_FILENAMES
            or _is_env_artefact(normalized)
            or any(name.endswith(suffix) for suffix in _BLOCKED_BASENAME_SUFFIXES)
            or any(
                normalized.startswith(prefix) or f"/{prefix}" in f"/{normalized}"
                for prefix in _BLOCKED_PREFIXES
            )
        )
        if blocked:
            failures.append(Failure(
                "POL-010",
                rel,
                f"File '{rel}' is an OS artefact / editor state file and must not "
                "be committed. Add it to .gitignore and remove it from the PR.",
            ))
    return failures


def _check_protected_paths(
    changed_files: list[str],
    author: str | None = None,
    head_ref: str | None = None,
) -> list[Failure]:
    failures: list[Failure] = []
    resolved_author = os.environ.get("PR_AUTHOR", "") if author is None else author
    resolved_head_ref = os.environ.get("PR_HEAD_REF", "") if head_ref is None else head_ref
    if not is_trusted_registry_refresh(resolved_author, resolved_head_ref):
        for rel in changed_files:
            if rel.replace("\\", "/").startswith(".auto-registry/"):
                failures.append(Failure(
                    "POL-011",
                    rel,
                    "Files under .auto-registry/ are auto-generated by the "
                    "update-registry.yml workflow. Remove your changes to "
                    f"'{rel}'; the registry will be rebuilt automatically after merge.",
                ))

    for rel in changed_files:
        normalized = rel.replace("\\", "/")
        if normalized.startswith("agents/tmp/") or normalized.startswith("starter-kits/tmp/"):
            failures.append(Failure(
                "POL-012",
                rel,
                "Files under agents/tmp/ and starter-kits/tmp/ are local deployer "
                "scratch artifacts and must never be committed. Remove them from "
                "the PR; these paths are covered by .gitignore.",
            ))
    return failures


def check_policy(
    repo: Path,
    folders: set[Path],
    changed_files: list[str],
    *,
    author: str | None = None,
    head_ref: str | None = None,
) -> list[Failure]:
    failures = [
        failure
        for folder in folders
        for failure in _check_folder_policy(repo, folder)
    ]
    failures.extend(check_model_weights(repo, changed_files))
    failures.extend(_check_hidden_artifacts(repo, changed_files))
    failures.extend(_check_protected_paths(changed_files, author, head_ref))
    return failures