"""Offline QuickStart Scenarios packaging, not installation or scientific execution.

Python 3.10+ standard library only. No network, subprocesses, archive extraction,
pickle/model loading or Discovery calls. Exit 0: offline operation succeeded;
1: invalid/error; 2: blocked/draft release. A package pass is NOT a science pass.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from urllib.parse import unquote, urlsplit

SCENARIOS = ("siphy", "biopharma", "cms", "bookshelf")
SHARED_FILES = (
    "LICENSE",
    "quickstarts/README.md", "quickstarts/GETTING-STARTED.md",
    "quickstarts/PACKAGE-CONTRACT.md", "quickstarts/SOURCE-INVENTORY.md",
    "quickstarts/AUTHORING.md", "quickstarts/templates/SCENARIO.md",
    "skills/quickstart-runner/SKILL.md", "skills/quickstart-runner/README.md",
    "skills/quickstart-runner/references/execution.md",
    "skills/quickstart-runner/scripts/package_scenario.py",
)
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
ALLOWED_SUFFIXES = {".md", ".txt", ".json", ".csv", ".sha256", ".py", ".ps1"}
MAX_TEXT_BYTES = 2 * 1024 * 1024
RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z", re.I)
PRIVATE_STATE_NAMES = {".git", ".discovery", ".local", "sessions", "results", "__pycache__", "node_modules"}


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def prompt_digest(path):
    # Windows checkouts may use CRLF. Normalize only the declared text encoding
    # and line ending; asset and staged-file hashes remain exact raw-byte hashes.
    text = path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def no_links(path):
    """Reject symlinks/reparse points in the complete existing path chain."""
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise ValueError(f"Symbolic link is not permitted: {candidate.name}")
        if candidate.exists() and getattr(candidate.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Reparse point is not permitted: {candidate.name}")


def safe_path(root, value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Expected a nonempty forward-slash relative path")
    parts = value.split("/")
    if any(part.casefold() in PRIVATE_STATE_NAMES or part.casefold().startswith(".venv") for part in parts):
        raise ValueError("Runtime state, caches and environments cannot be packaged")
    if PurePosixPath(value).is_absolute() or any(
        part in ("", ".", "..") or ":" in part or part.endswith((".", " "))
        or RESERVED.fullmatch(part) or any(ord(char) < 32 for char in part)
        for part in parts
    ):
        raise ValueError(f"Unsafe relative path: {value!r}")
    root = Path(root).absolute()
    target = root.joinpath(*parts)
    no_links(target)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes its source root")
    return target


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    no_links(path)
    return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_pairs)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text_file(path):
    no_links(path)
    require(path.is_file(), f"Missing regular file: {path.name}")
    allowed_type = path.name == "LICENSE" or path.suffix.lower() in ALLOWED_SUFFIXES
    require(allowed_type, f"Unapproved file type: {path.name}")
    require(0 < path.stat().st_size <= MAX_TEXT_BYTES, f"Empty/oversized text file: {path.name}")
    text = path.read_text(encoding="utf-8-sig")
    require("\x00" not in text, f"Binary content: {path.name}")
    return text


def public_url(value):
    require(isinstance(value, str), "Expected a public HTTPS URL")
    parsed = urlsplit(value)
    require(parsed.scheme == "https" and parsed.hostname and not parsed.username
            and not parsed.password and not parsed.query and not parsed.fragment,
            "Asset URL must be HTTPS without credentials/query/fragment")
    host = parsed.hostname.lower()
    require(not host.endswith((".sharepoint.com", ".local", ".internal"))
            and host not in ("localhost", "127.0.0.1", "::1"),
            "Internal asset URL is not a public release reference")


def load_assets(folder):
    data = read_json(folder / "assets.json")
    require(isinstance(data, list), "assets.json must be an array")
    seen = set()
    paths = set()
    for asset in data:
        require(isinstance(asset, dict), "Asset must be an object")
        for key in ("id", "role", "path", "license", "note"):
            require(isinstance(asset.get(key), str) and asset[key].strip(), f"Asset missing {key}")
        require(asset["id"] not in seen, "Duplicate asset id")
        seen.add(asset["id"])
        require(asset["path"].casefold() not in paths, "Duplicate asset path")
        paths.add(asset["path"].casefold())
        safe_path(folder, asset["path"])
        require(type(asset.get("required")) is bool, "Asset required must be boolean")
        require(asset.get("delivery") in ("included", "download", "unpublished"), "Unknown asset delivery")
        require(asset.get("redistribution") in ("documented", "pending"), "Unknown redistribution status")
        if asset["delivery"] == "download":
            public_url(asset.get("url"))
        else:
            require(asset.get("url") is None, "Only download assets may have a URL")
        for key, valid in (("bytes", lambda x: type(x) is int and x > 0),
                           ("sha256", lambda x: isinstance(x, str) and SHA256.fullmatch(x))):
            value = asset.get(key)
            require(value is None and asset["delivery"] == "unpublished" or valid(value), f"Invalid asset {key}")
        if asset["delivery"] == "included":
            path = safe_path(folder, asset["path"])
            require(path.is_file(), f"Included asset missing: {asset['path']}")
            require(path.stat().st_size == asset["bytes"] and digest(path) == asset["sha256"],
                    f"Included asset integrity mismatch: {asset['path']}")
    return data


def check_links(root, file):
    """Check local Markdown file targets; anchors and remote URLs are not fetched."""
    text = file.read_text(encoding="utf-8-sig")
    text = re.sub(r"^\s*(```|~~~).*?^\s*\1\s*$", "", text, flags=re.M | re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    for match in re.finditer(r"\[[^\]\n]+\]\(([^)\n]+)\)", text):
        target = match.group(1).strip().split(' "')[0].strip("<>")
        if not target or target.startswith("#") or urlsplit(target).scheme:
            continue
        target = unquote(target.split("#", 1)[0])
        location = root / target.lstrip("/") if target.startswith("/") else file.parent / target
        require(location.resolve().is_relative_to(root.resolve()), f"Link escapes package: {target}")
        no_links(location)
        require(location.exists(), f"Broken Markdown link in {file.name}: {target}")


def inspect_scenario(root, name):
    folder = safe_path(root, f"quickstarts/{name}")
    manifest = read_json(folder / "scenario.json")
    require(isinstance(manifest, dict), "scenario.json must be an object")
    require(type(manifest.get("schemaVersion")) is int and manifest["schemaVersion"] == 1, "Unsupported schemaVersion")
    require(manifest.get("id") == name, "Scenario id must match its folder")
    for key in ("title", "vertical", "version"):
        require(isinstance(manifest.get(key), str) and manifest[key].strip(), f"Missing {key}")
    require(re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"]), "Version must use x.y.z form")
    require(manifest.get("status") in ("draft", "ready"), "Unknown scenario status")
    for key, value in (("guide", "README.md"), ("profile", "profile.md"), ("assetManifest", "assets.json")):
        require(manifest.get(key) == value, f"Expected {key}={value}")
    files = manifest.get("files")
    require(isinstance(files, list) and files and all(isinstance(x, str) for x in files), "Missing file inventory")
    require(len({x.casefold() for x in files}) == len(files), "Duplicate inventory file")
    require({"README.md", "profile.md", "scenario.json", "assets.json"}.issubset(files), "Missing required inventory entries")
    for value in files:
        path = safe_path(folder, value)
        text_file(path)
        if path.suffix == ".md":
            check_links(root, path)
    actual = set()
    for path in folder.rglob("*"):
        if "__pycache__" in path.parts:
            continue
        no_links(path)
        if path.is_file():
            actual.add(path.relative_to(folder).as_posix())
    require(set(files) == actual, f"Unlisted or missing files: {sorted(set(files) ^ actual)}")
    prompt = manifest.get("prompt")
    require(isinstance(prompt, dict), "Missing prompt")
    require(prompt.get("path") in files, "Prompt not inventoried")
    require(prompt.get("status") in ("owner-supplied", "proposed"), "Unknown prompt status")
    require(isinstance(prompt.get("source"), str) and prompt["source"].strip(), "Missing prompt provenance")
    require(isinstance(prompt.get("sha256"), str) and SHA256.fullmatch(prompt["sha256"]), "Invalid prompt hash")
    require(prompt_digest(safe_path(folder, prompt["path"])) == prompt["sha256"], "Prompt hash mismatch")
    components = manifest.get("components")
    require(isinstance(components, list), "Missing components inventory")
    component_ids = set()
    for item in components:
        require(isinstance(item, dict), "Component must be an object")
        for key in ("id", "kind", "note"):
            require(isinstance(item.get(key), str) and item[key].strip(), f"Missing component {key}")
        require(item["id"] not in component_ids, "Duplicate component id")
        component_ids.add(item["id"])
        require(item.get("status") in ("repository", "host", "unpublished"), "Unknown component status")
        if item["status"] == "repository":
            require(item.get("repository") == "microsoft/discovery", "Unknown component repository")
            require(isinstance(item.get("revision"), str) and COMMIT.fullmatch(item["revision"]), "Missing immutable component revision")
            require(safe_path(root, item.get("path")).is_file(), f"Missing repository component: {item['id']}")
        else:
            require(item.get("path") is None and item.get("revision") is None, "Unresolved/host components cannot invent paths/revisions")
    blockers = manifest.get("blockers")
    require(isinstance(blockers, list), "Missing blockers array")
    require(all(isinstance(x, dict) and isinstance(x.get("id"), str) and x["id"]
                and isinstance(x.get("detail"), str) and x["detail"] for x in blockers), "Invalid blocker")
    require(len({x["id"] for x in blockers}) == len(blockers), "Duplicate blocker id")
    validation = manifest.get("validation")
    require(isinstance(validation, dict), "Missing validation record")
    for key in ("package", "workflow", "scientific"):
        require(validation.get(key) in ("not-run", "passed", "failed", "blocked"), f"Invalid {key} validation status")
    evidence = validation.get("evidence")
    if evidence is not None:
        require(evidence in files, "Evidence must be an inventoried file")
    assets = load_assets(folder)
    reasons = [x["id"] for x in blockers]
    if manifest["status"] == "draft":
        require(blockers, "A draft must disclose at least one blocker")
        reasons.append("draft")
    if prompt["status"] != "owner-supplied":
        reasons.append("prompt-not-approved")
    reasons.extend("unpublished:" + x["id"] for x in components if x["status"] == "unpublished")
    reasons.extend("asset:" + x["id"] for x in assets if x["required"] and
                   (x["delivery"] == "unpublished" or x["redistribution"] != "documented"))
    if any(validation[x] != "passed" for x in ("package", "workflow", "scientific")) or evidence is None:
        reasons.append("validation-evidence-incomplete")
    if manifest["status"] == "ready":
        require(not reasons, "Ready scenario has unresolved release gates")
    return manifest, {"id": name, "status": manifest["status"], "releaseBlockers": reasons}


def validate(repo_root, release=False):
    root = Path(repo_root).absolute()
    errors, results = [], []
    for relative in SHARED_FILES:
        try:
            path = safe_path(root, relative)
            text_file(path)
            if path.suffix == ".md":
                check_links(root, path)
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append(f"{relative}: {exc}")
    for name in SCENARIOS:
        try:
            _, result = inspect_scenario(root, name)
            results.append(result)
        except (OSError, ValueError, UnicodeError, TypeError, KeyError) as exc:
            errors.append(f"{name}: {exc}")
    ready = not errors and len(results) == len(SCENARIOS) and all(not x["releaseBlockers"] for x in results)
    return {"status": "failed" if errors else "blocked" if release and not ready else "passed",
            "scope": "offline-package-only", "releaseReady": ready, "errors": errors, "scenarios": results,
            "notTested": ["remote-url-reachability", "component-bytes-at-pinned-revision",
                          "app-skill-activation", "installation", "indexing", "workflow", "scientific-acceptance"]}


def stage(repo_root, scenario, destination, allow_draft=False, apply=False):
    root, target = Path(repo_root).absolute(), Path(destination).absolute()
    report = validate(root)
    if report["status"] != "passed":
        return report
    try:
        require(scenario in SCENARIOS, "Unknown scenario")
        no_links(target)
        require(not target.exists(), "Destination already exists; choose a fresh folder")
        require(not target.resolve().is_relative_to(root.resolve()), "Destination must be outside the repository")
        require(target.parent.is_dir(), "Destination parent must exist")
        selected = next(x for x in report["scenarios"] if x["id"] == scenario)
        if selected["releaseBlockers"] and not allow_draft:
            return {"status": "blocked", "scope": "offline-staging", "errors": ["Draft requires --allow-draft for author inspection"], "scenario": selected}
        paths = list(SHARED_FILES)
        for name in SCENARIOS:
            manifest = read_json(root / "quickstarts" / name / "scenario.json")
            paths.extend(f"quickstarts/{name}/{item}" for item in manifest["files"])
        paths = sorted(set(paths))
        # Preflight all sources before writing anything, even for dry-run.
        for value in paths:
            text_file(safe_path(root, value))
        if not apply:
            return {"status": "planned", "scenario": scenario, "files": paths,
                    "destination": str(target), "releaseReady": not selected["releaseBlockers"]}
        target.mkdir()
        for value in paths:
            source = safe_path(root, value)
            dest = safe_path(target, value)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as incoming, dest.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
        generated = {
            ".github/skills/quickstart-runner/SKILL.md": (
                "---\nname: quickstart-runner\ndescription: 'Run the selected QuickStart Scenario: "
                "read the bundled canonical runner and scenario selection before any setup or execution.'\n---\n\n"
                "# QuickStart Scenarios project entry\n\n"
                "Read [the canonical runner](../../../skills/quickstart-runner/SKILL.md) and "
                "[the selection record](../../../quickstart-selection.json).\n"
                "This shim grants no permissions. Draft blockers remain blockers. "
                "Do not infer installation, indexing or computation consent.\n"),
            ".gitignore": ".discovery/\nsessions/\n.local/\nresults/\n.venv*/\n__pycache__/\n*.pyc\n",
            "quickstart-selection.json": json.dumps({"schemaVersion": 1, "scenario": scenario,
                "manifest": f"quickstarts/{scenario}/scenario.json", "draft": bool(selected["releaseBlockers"]),
                "approvals": {}, "note": "Staging only; no installation, activation or scientific execution"}, indent=2) + "\n",
        }
        for relative, content in generated.items():
            path = safe_path(target, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
        records = [{"path": relative, "sha256": digest(safe_path(target, relative))}
                   for relative in sorted(paths + list(generated))]
        with (target / "staged-files.json").open("x", encoding="utf-8") as stream:
            json.dump({"scope": "offline-copy", "files": records}, stream, indent=2)
            stream.write("\n")
        return {"status": "staged-draft" if selected["releaseBlockers"] else "staged",
                "scenario": scenario, "destination": str(target), "files": len(records),
                "releaseReady": not selected["releaseBlockers"], "approvals": {},
                "note": "Verify runtime skill activation separately; no scientific work was run"}
    except (OSError, ValueError, UnicodeError) as exc:
        return {"status": "failed", "scope": "offline-staging", "errors": [str(exc)],
                "note": "If an I/O failure left a partial destination, preserve it and use a new destination"}


def verify_assets(repo_root, scenario, source):
    results = []
    try:
        require(scenario in SCENARIOS, "Unknown scenario")
        folder = safe_path(Path(repo_root), f"quickstarts/{scenario}")
        for asset in load_assets(folder):
            path = safe_path(folder if asset["delivery"] == "included" else Path(source), asset["path"])
            if not path.is_file():
                status = "missing-required" if asset["required"] else "missing-optional"
            elif asset["sha256"] is None or asset["bytes"] is None:
                status = "unverified"
            elif path.stat().st_size != asset["bytes"] or digest(path) != asset["sha256"]:
                status = "mismatch"
            else:
                status = "verified"
            results.append({"id": asset["id"], "path": asset["path"], "status": status})
        failed = any(x["status"] == "mismatch" for x in results)
        blocked = any(x["status"] in ("missing-required", "unverified") for x in results)
        return {"status": "failed" if failed else "blocked" if blocked else "passed",
                "scope": "local-bytes-only", "assets": results,
                "note": "No publication, extraction, ingestion, model loading or execution authorized"}
    except (OSError, ValueError, UnicodeError, TypeError, KeyError) as exc:
        return {"status": "failed", "scope": "local-bytes-only", "errors": [str(exc)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    default_root = Path(__file__).resolve().parents[3]
    for name in ("validate", "stage", "verify-assets"):
        command = actions.add_parser(name)
        command.add_argument("--repo-root", type=Path, default=default_root)
        if name == "validate":
            command.add_argument("--release", action="store_true")
        else:
            command.add_argument("--scenario", choices=SCENARIOS, required=True)
        if name == "stage":
            command.add_argument("--destination", type=Path, required=True)
            command.add_argument("--allow-draft", action="store_true")
            command.add_argument("--apply", action="store_true")
        elif name == "verify-assets":
            command.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "validate":
        report = validate(args.repo_root, args.release)
    elif args.action == "stage":
        report = stage(args.repo_root, args.scenario, args.destination, args.allow_draft, args.apply)
    else:
        report = verify_assets(args.repo_root, args.scenario, args.source)
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 1 if report["status"] == "failed" else 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())