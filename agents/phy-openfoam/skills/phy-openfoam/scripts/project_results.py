"""Initialize and validate project-owned results, never contribution-source output.

This standalone stdlib module is also the shared path policy used by reporting
and source developer tools. It does not import numerical code or change global
runtime policy. Native execution, when explicitly requested with ``run``, remains
the installed CLI's responsibility and requires the normal scientific approval.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

MARKER = "results-manifest.json"
SCHEMA = "phy-openfoam-project-results/1"
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FOLDER = re.compile(r"^results-[a-z0-9]+(?:-[a-z0-9]+)*$")
SUBDIRECTORIES = ("inputs", "analysis", "logs", "exports", "runs", "studies")
READ_ONLY = {"capabilities", "schema", "tutorial", "status", "verify", "study-status"}
COMMANDS = READ_ONLY | {"lint", "prepare", "execute", "finalize", "reassess", "cancel", "recover",
                        "propose", "confirm", "geometry", "study-prepare", "study-assess",
                        "design-sample", "example", "export", "compact"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def lexical(path: Path | str, *, base: Path | None = None) -> Path:
    path = Path(path).expanduser()
    if ".." in path.parts:
        raise ValueError("Parent traversal is not a results destination")
    if not path.is_absolute():
        if base is None:
            raise ValueError("An explicit absolute project root is required; CWD is not project identity")
        path = base / path
    return Path(os.path.abspath(path))


def linked(path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0)
                                     & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def source_location(path: Path) -> bool:
    if any(part.casefold() == "agents" for part in path.parts):
        return True
    # Also protect acquired entries with a different folder name, even when
    # someone mistakenly selects the contribution itself as the project root.
    return any((parent / "agent.yaml").is_file() and (parent / "metadata.yaml").is_file()
               and (parent / "tools/openfoam").is_dir() for parent in (path, *path.parents))


def project_root(value: Path | str) -> Path:
    path = lexical(value)
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("Project root must be an existing directory")
    if source_location(path) or source_location(resolved):
        raise ValueError("The project root cannot be agents or an acquired contribution-source entry")
    return resolved


def no_links(path: Path, stop: Path) -> None:
    for candidate in (path, *path.parents):
        if linked(candidate):
            raise ValueError("Symlink/junction/reparse-point output requires an unlinked results location")
        if candidate == stop:
            break


def validate_container(project: Path | str, value: Path | str, *, require_marker: bool = True) -> Path:
    original_project = lexical(project)
    project = project_root(original_project)
    original_value = lexical(value, base=original_project)
    if source_location(original_value):
        raise ValueError("Generated results must never be written under agents or contribution source")
    path = lexical(value, base=project)
    resolved = path.resolve()
    if path.parent.resolve() != project or resolved.parent != project:
        raise ValueError("Results must be a direct child of the explicitly selected project root")
    if not FOLDER.fullmatch(path.name) or len(path.name) > 160:
        raise ValueError("Results folder must be named results-<portable-lowercase-slug>")
    if source_location(path) or source_location(resolved):
        raise ValueError("Generated results must never be written under agents or contribution source")
    no_links(path, project)
    if require_marker:
        if not path.is_dir() or linked(path / MARKER):
            raise ValueError("Select an initialized project results folder")
        marker = path / MARKER
        if not marker.is_file() or marker.stat().st_size > 65536:
            raise ValueError("The project results manifest is missing or invalid")
        data = json.loads(marker.read_text(encoding="utf-8"))
        if (data.get("schema") != SCHEMA or data.get("folder") != path.name
                or Path(data.get("project_root", "")).resolve() != project):
            raise ValueError("Results manifest does not belong to this explicit project and folder")
    return resolved


def validate_destination(project: Path | str, results: Path | str, value: Path | str,
                         *, new: bool = False, allow_root: bool = False) -> Path:
    project = project_root(project)
    results = validate_container(project, results)
    path = lexical(value, base=results)
    resolved = path.resolve()
    if not path.is_relative_to(results) or not resolved.is_relative_to(results):
        raise ValueError("Generated output must stay inside the selected project results folder")
    if resolved == results and not allow_root:
        raise ValueError("Select a file or subdirectory inside the results folder")
    if source_location(path) or source_location(resolved):
        raise ValueError("Generated output must never be written under agents or contribution source")
    no_links(path, project)
    if new and (path.exists() or path.is_symlink()):
        raise FileExistsError("Output already exists; preserve it and select a fresh results destination")
    return resolved


def initialize(project: Path | str, slug: str, *, exact: bool = False) -> dict:
    project = project_root(project)
    if not isinstance(slug, str) or not SLUG.fullmatch(slug) or len(slug) > 80:
        raise ValueError("Slug must contain 1-80 lowercase letters/digits separated by single hyphens")
    suffix = "" if exact else "-" + datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz") + "-" + uuid.uuid4().hex[:8]
    path = validate_container(project, project / ("results-" + slug + suffix), require_marker=False)
    path.mkdir(exist_ok=False)  # Atomic collision refusal, including two callers.
    data = {"schema": SCHEMA, "created_utc": now(), "project_root": str(project),
            "folder": path.name, "slug": slug, "results_root": str(path),
            "paths": {name: str(path / name) for name in SUBDIRECTORIES},
            "report": str(path / "report.html"),
            "runtime_configuration_and_signing_keys": "Remain in the original operator data root; never copied here."}
    with (path / MARKER).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
    for name in SUBDIRECTORIES:
        (path / name).mkdir()
    return data


def cli_path(explicit: str | None) -> str:
    selected = explicit or os.environ.get("DISCOVERY_PHYSICS_CLI")
    if selected:
        found = shutil.which(selected)
        if not found:
            raise FileNotFoundError("The explicitly selected installed physics CLI is unavailable")
        return found
    found = shutil.which("discovery-physics")
    if found:
        return found
    home = Path(os.environ.get("DISCOVERY_PHYSICS_HOME") or
                str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "DiscoveryPhysics"))
    candidate = home / "venv" / ("Scripts/discovery-physics.exe" if os.name == "nt" else "bin/discovery-physics")
    if not candidate.is_file():
        raise FileNotFoundError("Physics CLI is not installed; no installation or alternative route was attempted")
    return str(candidate)


def route_arguments(project: Path, results: Path, arguments: list[str]) -> list[str]:
    if not arguments or arguments[0] not in COMMANDS:
        raise ValueError("Select an installed discovery-physics command, not an arbitrary shell command")
    args = list(arguments)
    op = args[0]
    # Resolve actual positional indexes rather than assuming options follow
    # them. The native CLI accepts e.g. export --include-fields RUN DEST;
    # guarding the wrong token would leave its real destination unchecked.
    options = {
        "geometry": {"--mesh-size": 1}, "export": {"--include-fields": 0},
        "prepare": {"--parent": 1},
    }.get(op, {})
    indexes = []
    index = 1
    while index < len(args):
        token = args[index]
        if token.startswith("-"):
            key = token.split("=", 1)[0]
            if op in {"geometry", "export", "example", "prepare"}:
                if key not in options or ("=" in token and options[key] != 1):
                    raise ValueError("Unsupported file-writing option; use the documented native command arguments")
                width = options[key]
                if width and "=" not in token:
                    if index + 1 >= len(args):
                        raise ValueError("Native option requires its value")
                    index += 1
            else:
                # Other commands do not choose an external output filename;
                # their option parsing remains the installed CLI's authority.
                indexes.append(index)
        else:
            indexes.append(index)
        index += 1
    # Native read arguments must not unexpectedly depend on the caller's CWD.
    input_indexes = {"lint": [1], "study-prepare": [1], "design-sample": [1],
                     "confirm": [2], "propose": [2]}.get(op, [])
    if op in {"geometry", "export", "example"}:
        if len(indexes) != 2:
            raise ValueError("The native file-writing command requires two explicit positional arguments")
        input_indexes = [indexes[0]] if op == "geometry" else []
    elif op == "prepare":
        if len(indexes) != 1:
            raise ValueError("Prepare requires one explicit input bundle")
        input_indexes = indexes
    for index in input_indexes:
        if len(args) > index and not args[index].startswith("-"):
            args[index] = str(lexical(args[index], base=results).resolve(strict=True))
    output_index = indexes[-1] if op in {"example", "geometry", "export"} else None
    if output_index is not None:
        if len(args) <= output_index:
            raise ValueError("An explicit new results-contained output file is required")
        target = validate_destination(project, results, args[output_index], new=True)
        if target.relative_to(results).parts[0].casefold() in {"runs", "studies"}:
            raise ValueError("Generated files must not modify native run/study stores")
        if any((parent / "journal.jsonl").is_file() for parent in (target, *target.parents)):
            raise ValueError("A generated export/input must not modify a signed native record")
        target.parent.mkdir(parents=True, exist_ok=True)
        args[output_index] = str(target)
    return args


def run_native(project: Path | str, results: Path | str, arguments: list[str], cli: str | None = None) -> int:
    project = project_root(project)
    results = validate_container(project, results)
    for folder in ("runs", "studies", "logs"):
        target = validate_destination(project, results, folder)
        if not target.is_dir() or any((p / "journal.jsonl").is_file() for p in (target, *target.parents)):
            raise ValueError("Native stores and retained logs must be unlinked directories outside signed records")
    args = route_arguments(project, results, arguments)
    env = os.environ.copy()
    env["DISCOVERY_PHYSICS_RUNS"] = str(results / "runs")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [cli_path(cli), *args]
    # Forward stdout unchanged, preserving the installed CLI's JSON interface.
    # Only an explicit invocation writes this retained transcript; manual status
    # questions should inspect the recorded store directly without this wrapper.
    process = subprocess.run(command, cwd=results, env=env, capture_output=True,
                             text=True, encoding="utf-8", check=False)
    receipt = validate_destination(project, results, results / "logs" / ("cli-" + uuid.uuid4().hex + ".json"), new=True)
    with receipt.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump({"utc": now(), "argv": command, "exit_code": process.returncode,
                   "stdout": process.stdout, "stderr": process.stderr,
                   "runs_root": str(results / "runs")}, stream, indent=2)
    sys.stdout.write(process.stdout)
    sys.stderr.write(process.stderr)
    return process.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    init = actions.add_parser("init", help="Create a new marked results folder; no native CLI call")
    init.add_argument("--project-root", type=Path, required=True)
    init.add_argument("--slug", required=True)
    init.add_argument("--exact", action="store_true", help="Use the exact slug; collisions fail rather than overwrite")
    inspect = actions.add_parser("check", help="Read-only destination policy check")
    inspect.add_argument("--project-root", type=Path, required=True)
    inspect.add_argument("--results-dir", type=Path, required=True)
    inspect.add_argument("--destination", type=Path)
    run = actions.add_parser("run", help="Explicitly invoke the installed CLI using this campaign's run store")
    run.add_argument("--project-root", type=Path, required=True)
    run.add_argument("--results-dir", type=Path, required=True)
    run.add_argument("--cli")
    run.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.action == "init":
            print(json.dumps(initialize(args.project_root, args.slug, exact=args.exact), indent=2))
        elif args.action == "check":
            path = validate_container(args.project_root, args.results_dir)
            if args.destination is not None:
                path = validate_destination(args.project_root, path, args.destination, allow_root=True)
            print(json.dumps({"ok": True, "path": str(path)}))
        else:
            arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
            return run_native(args.project_root, args.results_dir, arguments, args.cli)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())