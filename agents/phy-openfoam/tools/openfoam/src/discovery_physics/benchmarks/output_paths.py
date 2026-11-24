"""Developer-output routing; the standalone skill guard owns the path policy.

An installed benchmark loads the guard from the explicitly selected project's
installed skill. A source checkout can use its canonical skill copy instead.
Missing helpers fail closed: package installation does not install a skill, and
editing this source does not update an already installed benchmark package.
"""

from __future__ import annotations

import argparse
import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType


def _source_guard() -> Path | None:
    parents = Path(__file__).resolve().parents
    if len(parents) < 6:
        return None
    entry = parents[5]
    candidate = entry / "skills/phy-openfoam/scripts/project_results.py"
    if ((entry / "agent.yaml").is_file() and (entry / "metadata.yaml").is_file()
            and (entry / "tools/openfoam").is_dir() and candidate.is_file()):
        return candidate
    return None


def load_guard(project: Path | str) -> ModuleType:
    """Load policy without a package dependency or source-tree bytecode writes."""
    root = Path(project).expanduser()
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("An explicit absolute project root is required; CWD is not project identity")
    if not root.resolve(strict=True).is_dir():
        raise ValueError("Project root must be an existing directory")
    source = _source_guard()
    candidate = source or root / ".github/skills/phy-openfoam/scripts/project_results.py"
    if not candidate.is_file():
        raise FileNotFoundError(
            "Project results guard is missing. Supply the complete phy-openfoam skill at "
            "--project-root/.github/skills/phy-openfoam/; no fallback output is permitted."
        )
    module = ModuleType("phy_openfoam_project_results_guard")
    module.__file__ = str(candidate)
    exec(compile(candidate.read_text(encoding="utf-8"), str(candidate), "exec"), module.__dict__)
    if not all(callable(getattr(module, name, None)) for name in (
        "project_root", "initialize", "validate_container", "validate_destination",
    )):
        raise ValueError("The installed project results guard has an incompatible interface")
    module.project_root(project)  # Keep the original lexical path for policy validation.
    return module


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-root", type=Path, required=True,
                        help="Explicit absolute existing user project, never contribution source")
    parser.add_argument("--results-dir", type=Path, required=True,
                        help="Existing marked results-<slug> direct child of that project")


class ResultPaths:
    def __init__(self, project: Path | str, results: Path | str):
        self.guard = load_guard(project)
        self.project = self.guard.project_root(project)
        self.results = self.guard.validate_container(project, results)

    def destination(self, value: Path | str, *, new: bool = False,
                    allow_root: bool = False) -> Path:
        return self.guard.validate_destination(
            self.project, self.results, value, new=new, allow_root=allow_root,
        )

    def output(self, value: Path | str, *, new: bool = True) -> Path:
        path = self.destination(value, new=new)
        if path.relative_to(self.results).parts[0].casefold() in {"runs", "studies"}:
            raise ValueError("Developer outputs must not modify native run/study stores")
        if any((parent / "journal.jsonl").is_file() for parent in (path, *path.parents)):
            raise ValueError("Developer outputs must not modify a signed native record")
        return path

    def input(self, value: Path | str) -> Path:
        """Explicit read inputs can be historical/external; relative inputs use the project."""
        path = Path(value).expanduser()
        return (path if path.is_absolute() else self.project / path).resolve(strict=True)

    def directory(self, value: Path | str) -> Path:
        path = self.output(value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path = self.output(path)
        path.mkdir(exist_ok=False)
        return path

    def write_text(self, value: Path | str, text: str) -> Path:
        path = self.output(value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path = self.output(path)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        return path

    def run_root(self, value: Path | str | None = None) -> Path:
        root = self.destination("runs" if value is None else value)
        base = self.destination("runs")
        if not root.is_relative_to(base):
            raise ValueError("Native developer stores must stay under the selected results/runs")
        studies = self.destination(root.parent / "studies")
        for path in (root, studies):
            if path.exists() and not path.is_dir():
                raise ValueError("Native run/study stores must be directories")
            if any((parent / "journal.jsonl").is_file() for parent in (path, *path.parents)):
                raise ValueError("A native store cannot be nested inside a signed native record")
        return root

    def child_env(self, runs: Path | str | None = None) -> dict[str, str]:
        env = os.environ.copy()
        env["DISCOVERY_PHYSICS_RUNS"] = str(self.run_root(runs))
        return env

    @contextmanager
    def native_store(self):
        """Scope an in-process developer solve; never change HOME, keys or operator caps."""
        root = self.run_root()
        previous = os.environ.get("DISCOVERY_PHYSICS_RUNS")
        os.environ["DISCOVERY_PHYSICS_RUNS"] = str(root)
        try:
            yield root
        finally:
            if previous is None:
                os.environ.pop("DISCOVERY_PHYSICS_RUNS", None)
            else:
                os.environ["DISCOVERY_PHYSICS_RUNS"] = previous


def write_bundle(parser: argparse.ArgumentParser, argv: list[str] | None, bundle: dict) -> Path:
    add_arguments(parser)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        paths = ResultPaths(args.project_root, args.results_dir)
        return paths.write_text(args.output, json.dumps(bundle, indent=1) + "\n")
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))


def main(argv: list[str] | None = None) -> int:
    """Read-only output check used by the Node builder before its exclusive write."""
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        path = ResultPaths(args.project_root, args.results_dir).output(args.output)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"output": str(path)}))
    return 0