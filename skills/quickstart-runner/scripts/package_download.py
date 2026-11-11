"""Prepare exact-file QuickStart downloads locally; never install, extract or upload.

Python 3.10+ standard library. Exit 0: requested byte operation succeeded;
1: invalid input; 2: missing files/guide or unapproved publication mode.
The owner guides and nested archives are copied as bytes without modification.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from urllib.parse import quote
import zipfile

SCENARIOS = ("biopharma", "siphy", "cms", "bookshelf")
PRIVATE = {".git", ".discovery", ".local", "sessions", "results", "__pycache__", "node_modules", ".env"}
RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.I)
HASH = re.compile(r"[0-9a-f]{64}\Z")
GENERATED = {"readme.md", "license", "quickstart-runner.md", "package-sha256sums.txt"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def no_links(path):
    for item in (path, *path.parents):
        require(not item.is_symlink(), f"Symlink refused: {item.name}")
        if item.exists():
            require(not getattr(item.lstat(), "st_file_attributes", 0) & 0x400,
                    f"Reparse point refused: {item.name}")


def safe_path(root, value):
    require(isinstance(value, str) and value, "Nonempty relative path required")
    require(not PurePosixPath(value).is_absolute() and "\\" not in value, "Absolute/backslash path refused")
    parts = value.split("/")
    for part in parts:
        require(part not in ("", ".", "..") and not part.endswith((".", " "))
                and not RESERVED.fullmatch(part)
                and not any(c in ':*?<>|"' or ord(c) < 32 for c in part), "Unsafe path component")
        require(part.casefold() not in PRIVATE and not part.casefold().startswith(".venv"),
                "Runtime state or private environment cannot be packaged")
    root = Path(root).absolute()
    path = root.joinpath(*parts)
    no_links(path)
    require(path.resolve().is_relative_to(root.resolve()), "Path escapes root")
    return path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    no_links(path)
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs)


def load(root, scenario):
    require(scenario in SCENARIOS, "Unknown scenario")
    data = read_json(safe_path(root, "skills/quickstart-runner/references/downloads.json"))
    require(isinstance(data, dict) and data.get("formatVersion") == 1, "Unknown inventory format")
    record = data["packages"][scenario]
    require(isinstance(record, dict) and isinstance(record.get("title"), str), "Invalid package")
    require(type(record.get("publicationApproved")) is bool, "Explicit publication status required")
    require(isinstance(record.get("files"), list), "Files array required")
    guide = record.get("guide")
    require(guide is None or isinstance(guide, dict), "Invalid guide record")
    entries = ([guide] if guide else []) + record["files"]
    if record.get("paperManifest"):
        manifest = safe_path(root, record["paperManifest"])
        for paper in read_json(manifest):
            name = f"{paper['pmcid']}.{paper['version']}.pdf"
            entries.append({"path": str(PurePosixPath(record["paperManifest"]).parent / "papers" / name),
                            "name": name, "bytes": paper["bytes"], "sha256": paper["sha256"]})
    names, sources = set(GENERATED), set()
    for entry in entries:
        require(isinstance(entry, dict), "File record must be an object")
        name = entry.get("name")
        path = safe_path(root, entry.get("path"))
        safe_path(root, name)
        require("/" not in name and name.casefold() not in names, "Duplicate/reserved download filename")
        require(entry["path"].casefold() not in sources, "Duplicate source file")
        names.add(name.casefold())
        sources.add(entry["path"].casefold())
        require(type(entry.get("bytes")) is int and entry["bytes"] > 0, "Positive byte length required")
        require(isinstance(entry.get("sha256"), str) and HASH.fullmatch(entry["sha256"]), "Exact SHA256 required")
    return record, entries


def check(root, scenario):
    try:
        root = Path(root).absolute()
        record, entries = load(root, scenario)
        results = []
        for entry in entries:
            path = safe_path(root, entry["path"])
            status = "missing" if not path.is_file() else (
                "verified" if path.stat().st_size == entry["bytes"] and digest(path) == entry["sha256"] else "mismatch")
            results.append({"file": entry["name"], "status": status})
        mismatch = any(item["status"] == "mismatch" for item in results)
        missing = any(item["status"] == "missing" for item in results)
        return {"status": "failed" if mismatch else "blocked" if missing else "passed",
                "scope": "exact-local-bytes-only", "scenario": scenario, "files": results,
                "completedGuidePresent": record["guide"] is not None,
                "publicationReady": bool(record["guide"] and not mismatch and not missing and record["publicationApproved"]),
                "publicationNote": record.get("publicationReason", "Not approved"),
                "scientificExecution": "not-run"}
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
        return {"status": "failed", "errors": [str(error)], "scope": "exact-local-bytes-only"}


def prepare(root, scenario, destination, local_review=False, apply=False):
    root, dest = Path(root).absolute(), Path(destination).absolute()
    report = check(root, scenario)
    if report["status"] != "passed":
        return report
    try:
        record, entries = load(root, scenario)
        if record["guide"] is None:
            return {"status": "blocked", "errors": ["Completed owner QuickStart guide not supplied; no substitute created"]}
        if not local_review and not record["publicationApproved"]:
            return {"status": "blocked", "errors": ["Public distribution not approved; --local-review only prepares a local author copy"]}
        archive = dest.with_name(dest.name + ".zip")
        no_links(dest)
        no_links(archive)
        require(not dest.exists() and not archive.exists(), "Destination or ZIP already exists; nothing overwritten")
        require(dest != archive and dest.parent.is_dir(), "Choose a folder with an existing parent")
        require(not dest.resolve().is_relative_to(root.resolve()), "Review destination must be outside repository")
        runner = safe_path(root, "skills/quickstart-runner/SKILL.md")
        licence = safe_path(root, "LICENSE")
        require(runner.is_file() and licence.is_file(), "Runner or repository licence missing")
        if not apply:
            return {"status": "planned", "scenario": scenario, "files": [x["name"] for x in entries],
                    "destination": str(dest), "zip": str(archive), "writes": False}
        dest.mkdir()
        copied = []
        for entry in entries:
            source = safe_path(root, entry["path"])
            target = safe_path(dest, entry["name"])
            with source.open("rb") as src, target.open("xb") as out:
                shutil.copyfileobj(src, out)
            require(target.stat().st_size == entry["bytes"] and digest(target) == entry["sha256"], "Source changed during copy; preserve partial output")
            copied.append(entry["name"])
        for source, name in ((runner, "quickstart-runner.md"), (runner, ".github/skills/quickstart-runner/SKILL.md"), (licence, "LICENSE")):
            target = safe_path(dest, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as src, target.open("xb") as out:
                shutil.copyfileobj(src, out)
            require(digest(source) == digest(target), "Shared file copy mismatch")
            copied.append(name)
        guide_name = record["guide"]["name"]
        links = "\n".join(f"- [{x['name']}]({quote(x['name'])})" for x in entries)
        start = (
            f"# {record['title']} — exact-file local review download\n\n"
            "This is a local author-review package, not a public release or a scientific pass.\n\n"
            f"1. Create/open a new Discovery project in this folder.\n"
            f"2. Start a new session and use the model required by [{guide_name}]({quote(guide_name)}).\n"
            "3. Confirm the project-scoped runner is available. If not, attach [quickstart-runner.md](quickstart-runner.md) explicitly; record manual loading.\n"
            f"4. Attach the full guide and send: Use the quickstart-runner skill to follow this complete QuickStart guide from the supplied files; check prerequisites first and keep setup and computation approvals separate.\n"
            "5. Follow the guide's runtime installation, package selection, approvals, native run and output checks. pip installs packages, not Python.\n\n"
            "The full source guide, original archives and attachments below are unchanged. Do not execute a Markdown file as Python, reuse old sessions, waive checksum failures or automatically downgrade another runtime.\n\n"
            f"## Original files\n\n{links}\n\n"
            f"## Current limits\n\n{record.get('runtimeStatus', 'Runtime not validated')}\n\n"
            f"{record.get('publicationReason', 'Publication not approved')}\n\n"
            "Nested archives remain unopened. No project state, installed environment or scientific execution was created by packaging.\n"
        )
        with (dest / "README.md").open("x", encoding="utf-8", newline="\n") as out:
            out.write(start)
        copied.append("README.md")
        checksum = "".join(f"{digest(safe_path(dest, name))}  {name}\n" for name in sorted(copied))
        with (dest / "PACKAGE-SHA256SUMS.txt").open("x", encoding="utf-8", newline="\n") as out:
            out.write(checksum)
        copied.append("PACKAGE-SHA256SUMS.txt")
        # Store already-compressed payloads without altering or expanding them.
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as outer:
            for name in sorted(copied):
                outer.write(safe_path(dest, name), name)
        with zipfile.ZipFile(archive) as outer:
            require(outer.testzip() is None, "Outer download failed CRC verification")
            for entry in entries:
                hasher = hashlib.sha256()
                with outer.open(entry["name"]) as incoming:
                    for block in iter(lambda: incoming.read(1024 * 1024), b""):
                        hasher.update(block)
                require(hasher.hexdigest() == entry["sha256"], "Source bytes changed inside outer download")
        return {"status": "prepared-local-review", "scenario": scenario, "destination": str(dest),
                "zip": str(archive), "zipBytes": archive.stat().st_size, "zipSha256": digest(archive),
                "originalFilesVerified": len(entries), "scientificExecution": "not-run", "uploaded": False}
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, zipfile.BadZipFile) as error:
        return {"status": "failed", "errors": [str(error)],
                "note": "Preserve any partial new output; original sources and existing destinations are never overwritten"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "prepare"):
        command = commands.add_parser(name)
        command.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
        command.add_argument("--scenario", choices=SCENARIOS, required=True)
        if name == "prepare":
            command.add_argument("--destination", type=Path, required=True)
            command.add_argument("--local-review", action="store_true")
            command.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = check(args.repo_root, args.scenario) if args.command == "check" else prepare(
        args.repo_root, args.scenario, args.destination, args.local_review, args.apply)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 1 if result["status"] == "failed" else 2 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())