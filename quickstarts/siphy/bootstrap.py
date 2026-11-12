#!/usr/bin/env python3
"""Prepare SiPhy files safely; never install, build, import, or activate anything."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import unicodedata


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
RUNNER = PROJECT_ROOT / "skills" / "quickstart-runner"
if not RUNNER.is_dir():
    RUNNER = PROJECT_ROOT / ".github" / "skills" / "quickstart-runner"
ARCHIVE_SHA256 = "f06834009e5e28b0c2cb18f3b7ff5227d1cb8ee2ecbd84f41eda157f8907159c"
ARCHIVE_SIZE = 40992256
AGENTS = (
    "hardware-spec-dev",
    "chip-rtl-design",
    "chip-rtl-lint",
    "chip-functional-verification",
)
IMAGES = {
    "rtl-design:latest": "chip-rtl-design/tools/rtl-design",
    "rtl-lint:latest": "chip-rtl-lint/tools/rtl-lint",
    "functional-verification:latest": "chip-functional-verification/tools/functional-verification",
}
MANIFEST = ".siphy/provenance.json"
GUIDE = "QuickStart-Spec-to-RTL.md"
PROMPT = "PROMPT.txt"
MIN_FREE_BYTES = 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)
PROMPT_SHA256 = "43e17bdbb8d85b600b66d2b59b4a585cfccf5da2b203050f58629ac12d658696"
MICROCHIP_SERVER = "microchip-mcp-server"
MICROCHIP_ACTION = "search_microchip_product_documents"
MICROCHIP_TOOL_REFERENCE = f"sdk/{MICROCHIP_SERVER}/{MICROCHIP_ACTION}"


class BootstrapError(Exception):
    """A safe, actionable preparation or readiness failure."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()


def portable_path(name: str) -> str:
    """Reject ambiguous names on Windows as well as POSIX, before selecting files."""
    if not name or "\\" in name or name.startswith("/") or "\x00" in name:
        raise BootstrapError(f"Unsafe archive path: {name!r}")
    parts = name.split("/")
    for part in parts:
        if (
            part in ("", ".", "..")
            or part.endswith((".", " "))
            or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
            or RESERVED.match(part)
        ):
            raise BootstrapError(f"Nonportable archive path: {name!r}")
    return "/".join(unicodedata.normalize("NFC", part).casefold() for part in parts)


def read_archive(path: Path) -> tuple[dict[str, bytes], list[dict]]:
    # Hash and inspect the same bytes, avoiding a reopen between validation and use.
    with path.open("rb") as stream:
        data = stream.read(ARCHIVE_SIZE + 1)
    if len(data) != ARCHIVE_SIZE or digest(data) != ARCHIVE_SHA256:
        raise BootstrapError("ship.tar size/SHA-256 mismatch; restore the original archive.")
    files: dict[str, bytes] = {}
    inventory = []
    seen: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        members = archive.getmembers()
        if len(members) > 10000:
            raise BootstrapError("Archive member limit exceeded.")
        for member in members:
            # Tar directory names may end in one slash, not repeated slashes.
            name = member.name[:-1] if member.isdir() and member.name.endswith("/") else member.name
            key = portable_path(name)
            if name != "ship" and not name.startswith("ship/"):
                raise BootstrapError(f"Unexpected archive root: {name}")
            if key in seen:
                raise BootstrapError(f"Duplicate/case-colliding archive path: {name}")
            if not (member.isdir() or member.isreg()) or member.issparse():
                raise BootstrapError(f"Unsupported archive member type: {name}")
            if member.size < 0 or member.size > MAX_MEMBER_BYTES:
                raise BootstrapError(f"Invalid archive member size: {name}")
            if member.isdir() and member.size != 0:
                raise BootstrapError(f"Directory with payload: {name}")
            seen[key] = "directory" if member.isdir() else "file"
        for key in seen:
            for parent in PurePosixPath(key).parents:
                if seen.get(str(parent)) == "file":
                    raise BootstrapError(f"File/directory archive collision: {key}")
        for member in members:
            name = member.name.rstrip("/") if member.isdir() else member.name
            entry = {"path": name, "kind": "directory" if member.isdir() else "file",
                     "size": member.size}
            if member.isreg():
                stream = archive.extractfile(member)
                if stream is None:
                    raise BootstrapError(f"Unreadable archive member: {name}")
                content = stream.read()
                if len(content) != member.size:
                    raise BootstrapError(f"Truncated archive member: {name}")
                files[name] = content
                entry["sha256"] = digest(content)
            inventory.append(entry)
    required = [f"ship/dot-github/agents/{name}.agent.md" for name in AGENTS]
    required += [
        "ship/README.md",
        "ship/dot-github/skills/report-gen/SKILL.md",
        "ship/dot-github/skills/report-gen/scripts/render_report.py",
        "ship/dot-github/skills/report-gen/references/usage.txt",
        "ship/dot-github/skills/report-gen/templates/report.html",
    ]
    for context in IMAGES.values():
        required += [f"ship/discovery_catalog/{context}/{name}"
                     for name in ("Dockerfile", "run.py", "tool.yaml", "entrypoint.sh")]
    missing = [name for name in required if not files.get(name)]
    if missing:
        raise BootstrapError("Incomplete selected archive layout: " + ", ".join(missing))
    return files, sorted(inventory, key=lambda entry: entry["path"])


def exact_prompt(guide: bytes) -> bytes:
    section = re.search(rb"(?m)^## 6\.[^\r\n]*\r?\n(.*?)(?=^## 7\.|\Z)", guide, re.S)
    if section is None:
        raise BootstrapError("Authoritative guide has no Section 6.")
    match = re.search(rb"\*\*Exact predefined prompt\*\*\r?\n\s*```text\r?\n(.*?)^```",
                      section[1], re.M | re.S)
    if match is None:
        raise BootstrapError("Authoritative guide has no exact Section 6 prompt.")
    prompt = match[1]
    # Permit checkout newline conversion, but never silently select an older prompt.
    if digest(prompt.replace(b"\r\n", b"\n")) != PROMPT_SHA256:
        raise BootstrapError("Section 6 prompt differs from the pinned v1.1 prompt.")
    return prompt


def overlay_agent(name: str, original: bytes) -> bytes:
    text = original.decode("utf-8").replace("\r\n", "\n")
    if name == "hardware-spec-dev":
        old_grant = 'tools:\n    - "discovery-app.discovery-app/toolCatalog"\n'
        if text.count(old_grant) != 1 or text.count("## Available Tool Catalog Sources") != 1:
            raise BootstrapError("Unexpected hardware-spec-dev source/grant layout.")
        text = text.replace(old_grant, f'tools:\n    - "{MICROCHIP_TOOL_REFERENCE}"\n', 1)
        text = text.split("## Available Tool Catalog Sources", 1)[0].rstrip() + "\n"
        text += """

## Portable setup: narrow binding requested, activation unverified

This effective overlay requests only the SDK documentation-search action
declared above. The observed SDK parser accepts this server/action reference;
that does not prove a live tool is exposed. This is an unvalidated prepared-project
candidate, not a proven activation fix.
The immutable source is under
.siphy/originals/. Do not reuse its machine-specific source identifier.
Stop with "tool unavailable; no connection attempted" until the project owner
uses the supported Discovery integration to import the accompanying plugin
with its matching server name and approve the required scoped access.
A parent-only lookup is not proof that this specialist can call it.
Do not invent source IDs, widen the selector to a wildcard, or inherit broad
catalog access. Record a successful specialist-level lookup, using the live
schema, before claiming retrieval readiness.
SDK host refresh and tool exposure require supported app handling. A plugin
file, parent-level lookup, or selector written into this definition does not
prove that this specialist has a callable tool. Do not bypass that boundary.
"""
    else:
        start = text.find("# Container image bootstrap (auto-generated by add-agent-from-catalog)")
        end = text.find("\n---\n", start)
        if start < 0 or end < 0:
            raise BootstrapError(f"Unexpected image bootstrap layout: {name}")
        text = text[:start] + """# Portable image prerequisite (effective overlay)

Use the working Linux engine and exact existing image tag recorded by the
read-only SiPhy preflight. Do not choose an engine solely because its executable
exists. If the engine or image is unavailable, stop and report the blocker.
Never install, pull, build, import, index, or sign in automatically. Dependency
provisioning is a separate owner-authorized operation, not part of this recipe.
Existing engine/image checks do not prove this agent or its tools are loaded.
Engine/image presence also does not validate container startup or resource-limit
enforcement. Keep all approved limits unchanged; stop on enforcement failures.
""" + text[end:]
    return text.encode("utf-8")


def activation() -> dict:
    return {
        "status": "blocked_pending_specialist_binding_and_native_execution_validation",
        "agents_loaded": "not_verified",
        "quickstart_runner_loaded": "not_verified",
        "report_gen_loaded": "not_verified",
        "catalog_connection_loaded": "not_verified",
        "hardware_spec_dev_catalog_call": "not_verified",
        "hardware_spec_dev_tool_grant": "narrow_sdk_selector_requested_activation_unverified",
        "hardware_spec_dev_tool_reference": MICROCHIP_TOOL_REFERENCE,
        "binding_candidate_validation": "parser_compatible_live_activation_unverified",
        "host_binding": "requires_supported_app_import_grant_and_exposure",
        "model_access": "not_verified",
        "model_matches_guide": "not_verified",
        "implementation_contract": "requires_user_decisions",
        "native_execution": "unverified_preflight_does_not_run_containers",
        "resource_limit_enforcement": "unverified_preflight_does_not_run_containers",
        "engineering_executed": False,
        "end_to_end_ready": False,
    }


def read_runner(root: Path) -> dict[str, bytes]:
    root = safe_destination(root, fresh=False)
    if not root.is_dir():
        raise BootstrapError("Authoritative repository skills/quickstart-runner package is missing.")
    files = {}
    seen = set()
    for path in sorted(root.rglob("*")):
        if linked(path):
            raise BootstrapError("Authoritative runner package must not contain links or junctions.")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if any(part in ("__pycache__", ".pytest_cache") for part in path.relative_to(root).parts):
            continue
        key = portable_path(relative)
        if key in seen:
            raise BootstrapError(f"Duplicate/case-colliding runner file: {relative}")
        seen.add(key)
        files[relative] = path.read_bytes()
    required = {
        "SKILL.md", "README.md", "references/README.md", "references/downloads.json",
        "scripts/package_download.py", "tests/test_package_download.py",
    }
    if not required.issubset(files) or any(not files[name] for name in required):
        raise BootstrapError("Authoritative repository quickstart-runner package is incomplete.")
    if not re.search(rb"(?m)^name: quickstart-runner\r?$", files["SKILL.md"]):
        raise BootstrapError("Authoritative shared runner has an unexpected skill identity.")
    return files


def make_payload(archive: Path, guide_path: Path, include_research: bool = False) -> tuple[dict, dict]:
    source, inventory = read_archive(archive)
    runner = read_runner(RUNNER)
    guide = guide_path.read_bytes()
    prompt = exact_prompt(guide)
    output: dict[str, bytes] = {}
    provenance: dict[str, dict] = {}

    def add(path: str, content: bytes, origin: str, kind: str) -> None:
        if path in output:
            raise BootstrapError(f"Output mapping collision: {path}")
        output[path] = content
        provenance[path] = {"sha256": digest(content), "size": len(content),
                            "origin": origin, "kind": kind}

    for path, content in sorted(source.items()):
        destination = None
        if path.startswith("ship/dot-github/agents/") and path.endswith(".agent.md"):
            if PurePosixPath(path).name.removesuffix(".agent.md") in AGENTS:
                destination = ".github/agents/" + PurePosixPath(path).name
        elif path.startswith("ship/dot-github/skills/report-gen/"):
            destination = path.replace("ship/dot-github/", ".github/", 1)
        elif path.startswith("ship/discovery_catalog/"):
            if any(path.startswith(f"ship/discovery_catalog/{name}/") for name in AGENTS[1:]):
                destination = path.removeprefix("ship/")
        elif include_research and path.startswith("ship/knowledge/bs_data/"):
            destination = path.removeprefix("ship/")
        if destination is None:
            continue
        if any(part in ("__pycache__", ".pytest_cache") for part in PurePosixPath(path).parts):
            continue
        add(".siphy/originals/" + path, content, path, "immutable_archive_original")
        if destination.startswith(".github/agents/"):
            agent = PurePosixPath(path).name.removesuffix(".agent.md")
            add(destination, overlay_agent(agent, content), path, "effective_overlay")
        else:
            add(destination, content, path, "unchanged_archive_copy")
    add(".siphy/originals/ship/README.md", source["ship/README.md"], "ship/README.md",
        "legacy_reference_only_not_runner")
    for relative, content in runner.items():
        add(".github/skills/quickstart-runner/" + relative, content,
            "repository/skills/quickstart-runner/" + relative, "unchanged_repository_copy")
    add(GUIDE, guide, "repository/" + GUIDE, "unchanged_authoritative_guide")
    add(PROMPT, prompt, "repository/" + GUIDE + "#section-6", "exact_prompt_bytes")
    archive_bytes = archive.read_bytes()
    if len(archive_bytes) != ARCHIVE_SIZE or digest(archive_bytes) != ARCHIVE_SHA256:
        raise BootstrapError("Original archive changed while preparing retained inputs.")
    source_prefix = "quickstarts/siphy/"
    add(source_prefix + "files/ship.tar", archive_bytes, "repository/quickstarts/siphy/files/ship.tar",
        "unchanged_complete_input_archive_pdfs_not_extracted")
    add(source_prefix + GUIDE, guide, "repository/quickstarts/siphy/" + GUIDE,
        "unchanged_authoritative_guide")
    scenario_files = (
        "README.md", "CUSTOMER-READINESS.md", "skill 1.md", "bootstrap.py", "probe_microchip.py",
        "tests/test_bootstrap.py", "tests/test_probe_microchip.py",
    )
    for relative in scenario_files:
        path = safe_destination(HERE.joinpath(*PurePosixPath(relative).parts), fresh=False)
        if not path.is_file():
            raise BootstrapError(f"Required scenario source file is missing: {relative}")
        add(source_prefix + relative, path.read_bytes(), "repository/" + source_prefix + relative,
            "unchanged_scenario_source_reference_not_activation")
    add("README.md", (
        "# Prepared SiPhy project\n\n"
        "Read the unchanged [scenario README](quickstarts/siphy/README.md) beside the\n"
        "[original full guide](quickstarts/siphy/QuickStart-Spec-to-RTL.md).\n"
        "The identical root [guide](QuickStart-Spec-to-RTL.md) and exact [prompt](PROMPT.txt)\n"
        "are convenient entry points; neither replaces the shared runner's approval gates.\n\n"
        "The complete unchanged [input archive](quickstarts/siphy/files/ship.tar) is retained.\n"
        "Optional research PDFs remain inside it unless explicitly selected for extraction.\n"
        "The archived older README is in `.siphy/originals/ship/README.md`; it is not the runner.\n\n"
        "From this prepared project's root, run local read-only checks:\n\n"
        "```console\n"
        "python quickstarts/siphy/bootstrap.py preflight --destination .\n"
        "python -B -m unittest discover -s quickstarts/siphy/tests -v\n"
        "```\n\n"
        "Optional endpoint diagnosis uses `quickstarts/siphy/probe_microchip.py`; it is\n"
        "not specialist acceptance. See [setup instructions](setup/NEXT-STEPS.txt) and\n"
        "[release blockers](quickstarts/siphy/CUSTOMER-READINESS.md).\n"
        "No original checkout or developer-specific path is needed for these local checks.\n"
        "Discovery activation, images, model access and contract decisions remain external\n"
        "prerequisites. Historical run artifacts remain unavailable, not silently repaired.\n"
    ).encode(), "bootstrap.py", "generated_prepared_project_entrypoint")
    add("setup/microchip.plugin.example.json", json_bytes({
        "servers": {MICROCHIP_SERVER: {
            "type": "http", "url": "https://api.microchip.com/mcp/resources"
        }}
    }), "verified_endpoint_import_example", "inert_example_not_runtime_configuration")
    add("setup/NEXT-STEPS.txt", (
        "SiPhy preparation is not activation or engineering readiness.\n"
        "Read QuickStart-Spec-to-RTL.md in full; PROMPT.txt preserves Section 6 exactly.\n"
        "The original archive, adjacent README/full guide and local CLI/tests are retained\n"
        "under quickstarts/siphy/. Commands in that README run from this project's root.\n"
        "No source checkout is required after preparation. The original tar is intact;\n"
        "optional research PDFs are not extracted unless explicitly selected.\n"
        "The legacy README under .siphy/originals is provenance, not the current runner.\n"
        "No Bookshelf setup is required by this preparation; research corpus is optional.\n"
        "No installs, image builds/pulls, imports, indexing, sign-in or containers were run.\n"
        "In Discovery, open/trust this project and start a fresh chat. Verify the four\n"
        "agents, quickstart-runner and report-gen are exposed; files alone cannot prove this.\n"
        "Use the copied authoritative shared quickstart-runner, not an older archive runner.\n"
        "Confirm model access and the guide's stated model; never silently substitute a pin.\n"
        f"hardware-spec-dev requests only {MICROCHIP_TOOL_REFERENCE}.\n"
        f"The plugin server name MUST remain {MICROCHIP_SERVER} to match this selector.\n"
        "Observed SDK parsing is not proof of live activation. Complete supported app\n"
        "import/grant setup; never reuse archived source IDs or broaden to a wildcard.\n"
        "The selector remains an unvalidated candidate, not an activation fix.\n"
        "setup/microchip.plugin.example.json is an import example, NOT auto-loaded config.\n"
        "SDK host refresh and tool exposure require supported app handling. Bootstrap\n"
        "does not patch the app or use private APIs, wildcard grants or invented selectors.\n"
        "Confirm endpoint/authentication requirements with your supported integration.\n"
        "Activation MUST be checked in a fresh chat after supported import/grant setup:\n"
        "verify named agent/skill exposure and an application-level Catalog lookup by\n"
        "hardware-spec-dev itself. A successful parent lookup is not sufficient.\n"
        "Resolve consequential CoreSPI contract gaps before implementation. Then use\n"
        "the exact PROMPT.txt. Save results in results/<unique-run-id>/, not sessions/.\n"
        "Run preflight separately to inspect existing Linux engine and all image tags.\n"
        "Image presence does not establish native startup, resource-limit enforcement,\n"
        "native gate correctness or tool compatibility. Preflight runs no containers.\n"
        "Podman rootless cgroup-v2 requires advertised cpu, memory and pids controllers.\n"
        "Missing controller metadata blocks preflight. Even a complete inventory does\n"
        "not prove enforcement: native validation requires separate authorization.\n"
        "Keep all approved limits unchanged and resolve host problems through supported\n"
        "administration. Historical host observations belong to the readiness document,\n"
        "not to this customer's current execution results.\n"
        "The under-five-minute startup objective is a target, not a measured guarantee.\n"
    ).encode(), "bootstrap.py", "generated_setup_guidance")
    manifest = {
        "schema_version": 1,
        "archive": {"sha256": ARCHIVE_SHA256, "size": ARCHIVE_SIZE,
                    "members": inventory},
        "guide_sha256": digest(guide),
        "prompt_sha256": digest(prompt),
        "selection": {"agents": list(AGENTS), "skills": ["quickstart-runner", "report-gen"],
                      "images": IMAGES, "research_included": include_research,
                      "excluded": ["discovery-add-agents", "cache files"]},
        "files": provenance,
        "activation": activation(),
        "startup_under_five_minutes": "target_only_not_measured",
    }
    output[MANIFEST] = json_bytes(manifest)
    return output, manifest


def linked(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except FileNotFoundError:
        return False


def filesystem_path(path: Path) -> Path:
    """Support Windows long paths without changing machine-wide policy."""
    absolute = os.path.abspath(path)
    if os.name == "nt" and not absolute.startswith("\\\\?\\"):
        absolute = ("\\\\?\\UNC\\" + absolute[2:] if absolute.startswith("\\\\")
                    else "\\\\?\\" + absolute)
    return Path(absolute)


def safe_destination(path: Path, fresh: bool) -> Path:
    if fresh and path.name:
        portable_path(path.name)
    path = filesystem_path(path)
    for ancestor in (path, *path.parents):
        if linked(ancestor):
            raise BootstrapError(f"Destination/ancestor is a link or junction: {ancestor}")
    if fresh:
        if os.path.lexists(path):
            raise BootstrapError(f"Destination already exists; never merged or overwritten: {path}")
        if not path.parent.is_dir():
            raise BootstrapError(f"Destination parent must already exist: {path.parent}")
    return path


def disk_evidence(path: Path, required: int) -> dict:
    probe = path
    while not probe.exists():
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    return {"path": str(probe), "free_bytes": free, "required_bytes": required,
            "sufficient": free >= required,
            "headroom_policy_bytes": MIN_FREE_BYTES,
            "minimum_engineering_storage": "not_validated",
            "scope": "host filesystem only; engine VM and future run output space not verified"}


def prepare(destination: Path, payload: dict[str, bytes]) -> None:
    destination = safe_destination(destination, fresh=True)
    seen = set()
    for relative in payload:
        key = portable_path(relative)
        if key in seen:
            raise BootstrapError(f"Duplicate/case-colliding output mapping: {relative}")
        seen.add(key)
    for key in seen:
        if any(str(parent) in seen for parent in PurePosixPath(key).parents):
            raise BootstrapError(f"Output file/directory collision: {key}")
    # No extract/extractall: archive permissions, links and ownership are never applied.
    destination.mkdir()
    try:
        for relative, content in sorted(payload.items()):
            target = destination.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(content)
            if target.suffix == ".sh" and os.name != "nt":
                target.chmod(0o755)
    except BaseException:
        # This tree was exclusively created by this invocation, never an existing project.
        shutil.rmtree(destination)
        raise


def verify_prepared(destination: Path) -> dict:
    destination = safe_destination(destination, fresh=False)
    manifest_path = destination / MANIFEST
    if not manifest_path.is_file():
        return {"verified": False, "errors": ["Prepared provenance manifest missing."]}
    if linked(destination / ".siphy") or linked(manifest_path):
        raise BootstrapError("Prepared provenance must not be a link.")
    try:
        manifest = json.loads(manifest_path.read_bytes())
        if manifest["archive"]["sha256"] != ARCHIVE_SHA256 or manifest["archive"]["size"] != ARCHIVE_SIZE:
            raise BootstrapError("Prepared archive identity differs from the pinned archive.")
        expected = manifest["files"]
        required = {GUIDE, PROMPT, ".github/skills/report-gen/SKILL.md",
                    ".github/skills/quickstart-runner/SKILL.md", "README.md",
                    "quickstarts/siphy/files/ship.tar", "quickstarts/siphy/README.md",
                    "quickstarts/siphy/" + GUIDE, "quickstarts/siphy/bootstrap.py"}
        required.update(f".github/agents/{name}.agent.md" for name in AGENTS)
        required.update(f"discovery_catalog/{context}/Dockerfile" for context in IMAGES.values())
        if not required.issubset(expected):
            raise BootstrapError("Prepared manifest omits required recipe files.")
        errors = []
        for name, metadata in expected.items():
            portable_path(name)
            target = destination.joinpath(*PurePosixPath(name).parts)
            if any(linked(path) for path in (target, *target.parents) if path != destination.parent):
                errors.append(f"Linked prepared file/ancestor: {name}")
            elif not target.is_file() or digest(target.read_bytes()) != metadata["sha256"]:
                errors.append(f"Missing/changed prepared file: {name}")
        if not errors:
            if (destination / PROMPT).read_bytes() != exact_prompt((destination / GUIDE).read_bytes()):
                errors.append("Prepared prompt is not the exact guide prompt.")
        return {"verified": not errors, "errors": errors,
                "scope": "file integrity only; provenance is not a signed activation attestation"}
    except (KeyError, TypeError, ValueError) as exc:
        raise BootstrapError(f"Invalid prepared provenance: {exc}") from exc


def command(args: list[str], timeout: float) -> dict:
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, encoding="utf-8", errors="replace",
                                timeout=timeout, check=False, shell=False)
        return {"command": args, "returncode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr[-2000:]}
    except subprocess.TimeoutExpired:
        return {"command": args, "returncode": None, "stdout": "", "stderr": "Command timed out."}
    except OSError as exc:
        return {"command": args, "returncode": None, "stdout": "", "stderr": str(exc)}


def parsed_command(args: list[str], timeout: float) -> tuple[object, dict]:
    evidence = command(args, timeout)
    raw = evidence.pop("stdout")
    if evidence["returncode"] != 0:
        return None, evidence
    try:
        return json.loads(raw), evidence
    except (ValueError, TypeError):
        evidence["error"] = "Engine returned malformed JSON."
        return None, evidence


def architecture(value: object) -> str:
    return {"x86_64": "amd64", "aarch64": "arm64"}.get(str(value).lower(), str(value).lower())


def podman_cgroup_evidence(host: dict) -> dict:
    version = host.get("cgroupVersion", host.get("CgroupVersion"))
    manager = host.get("cgroupManager", host.get("CgroupManager"))
    controllers = host.get("cgroupControllers", host.get("CgroupControllers"))
    security = host.get("security", host.get("Security", {}))
    if not isinstance(security, dict):
        security = {}
    rootless = security.get("rootless", security.get("Rootless"))
    required = ["cpu", "memory", "pids"]
    result = {
        "version": version,
        "manager": manager,
        "rootless": rootless,
        "reported_controllers": controllers,
        "required_rootless_v2_controllers": required,
        "resource_limit_enforcement": "unverified_no_containers_executed",
        "ready": False,
    }
    if not isinstance(rootless, bool) or str(version).lower() not in ("v1", "1", "v2", "2"):
        result["status"] = "blocked_unknown_cgroup_metadata"
        result["error"] = "Podman did not report a recognized cgroup version and rootless state."
        return result
    if rootless and str(version).lower() in ("v2", "2"):
        if not isinstance(controllers, list) or not all(isinstance(item, str) for item in controllers):
            available = set()
        else:
            available = set(controllers)
        missing = sorted(set(required) - available)
        result["missing_controllers"] = missing
        if missing:
            result["status"] = "blocked_missing_rootless_v2_controllers"
            result["error"] = (
                "Rootless Podman cgroup-v2 does not report required controllers: "
                + ", ".join(missing)
                + ". Resolve host delegation through supported administration; do not weaken limits."
            )
            return result
        result["status"] = "required_controllers_reported_enforcement_unverified"
    else:
        result["status"] = "rootless_v2_inventory_check_not_applicable_enforcement_unverified"
    result["ready"] = True
    return result


def runtime_evidence(runtime: str = "auto", timeout: float = 10) -> dict:
    candidates = []
    for name in (("docker", "podman") if runtime == "auto" else (runtime,)):
        executable = shutil.which(name)
        if not executable:
            candidates.append({"runtime": name, "ready": False, "error": "Executable not found."})
            continue
        info, check = parsed_command([executable, "info", "--format", "{{json .}}"], timeout)
        item = {"runtime": name, "executable": executable, "info_check": check,
                "ready": False, "images": {}}
        candidates.append(item)
        if not isinstance(info, dict):
            item["error"] = "Engine unavailable or invalid info response."
            continue
        host = info.get("host", info.get("Host", {}))
        if not isinstance(host, dict):
            host = {}
        engine_os = info.get("OSType", host.get("os", host.get("OS", "")))
        arch = architecture(info.get("Architecture", host.get("arch", host.get("Arch", ""))))
        item["os"] = engine_os
        item["architecture"] = arch
        if str(engine_os).lower() != "linux" or not arch:
            item["error"] = "A working Linux engine with known architecture is required."
            continue
        cgroup_ready = True
        if name == "podman":
            item["cgroup_check"] = podman_cgroup_evidence(host)
            cgroup_ready = item["cgroup_check"]["ready"]
            if not cgroup_ready:
                item["error"] = item["cgroup_check"]["error"]
        for tag in IMAGES:
            image, check = parsed_command(
                [executable, "image", "inspect", "--format", "{{json .}}", tag], timeout)
            if isinstance(image, list) and len(image) == 1:
                image = image[0]
            image = image if isinstance(image, dict) else {}
            image_os = image.get("Os", image.get("OS", ""))
            image_arch = architecture(image.get("Architecture", ""))
            image_id = image.get("Id", image.get("ID"))
            compatible = str(image_os).lower() == "linux" and image_arch == arch
            item["images"][tag] = {
                "check": check, "id": image_id, "os": image_os, "architecture": image_arch,
                "ready": check["returncode"] == 0 and bool(image_id) and compatible,
                "note": "Exact tag must exist on this engine; cross-architecture emulation is not assumed.",
            }
        item["ready"] = cgroup_ready and all(image["ready"] for image in item["images"].values())
    selected = next((item["runtime"] for item in candidates if item["ready"]), None)
    return {
        "ready": selected is not None,
        "readiness_scope": "engine_info_existing_images_and_reported_podman_cgroup_prerequisites_only",
        "native_execution": "unverified_no_containers_executed",
        "resource_limit_enforcement": "unverified_no_containers_executed",
        "selected": selected,
        "candidates": candidates,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "prepare", "preflight"))
    parser.add_argument("--destination", required=True, type=Path,
                        help="Fresh project path (plan/prepare); existing prepared project (preflight).")
    parser.add_argument("--include-research", action="store_true",
                        help="Explicitly copy optional research corpus; never index it.")
    parser.add_argument("--runtime", choices=("auto", "docker", "podman"), default="auto")
    parser.add_argument("--timeout", type=float, default=10,
                        help="Per read-only runtime command timeout in seconds (0 < value <= 60).")
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        if sys.version_info < (3, 10):
            raise BootstrapError("Python >= 3.10 is required.")
        if not 0 < args.timeout <= 60:
            raise BootstrapError("--timeout must be greater than zero and at most 60.")
        if args.mode == "preflight" and args.include_research:
            raise BootstrapError("--include-research is a preparation option, not a preflight action.")
        destination = safe_destination(args.destination, fresh=args.mode != "preflight")
        result = {"mode": args.mode, "destination": str(destination), "activation": activation(),
                  "python": {"executable": sys.executable, "version": sys.version.split()[0],
                             "supported": sys.version_info >= (3, 10)}}
        if args.mode == "preflight":
            result["files"] = verify_prepared(destination)
            result["disk"] = disk_evidence(destination, MIN_FREE_BYTES)
            result["runtime"] = runtime_evidence(args.runtime, args.timeout)
            ready = result["files"]["verified"] and result["disk"]["sufficient"] and result["runtime"]["ready"]
            result["local_prerequisites_ready"] = ready
            result["status"] = "local-prerequisites-ready-activation-unverified" if ready else "blocked"
            exit_code = 0 if ready else 2
        else:
            payload, manifest = make_payload(HERE / "files" / "ship.tar", HERE / GUIDE, args.include_research)
            required = sum(len(content) for content in payload.values())
            result.update({
                "archive": {"sha256": ARCHIVE_SHA256, "size": ARCHIVE_SIZE,
                            "validated_members": len(manifest["archive"]["members"])},
                "selection": manifest["selection"],
                "output_files": len(payload),
                "output_bytes": required,
                "disk": disk_evidence(destination.parent, required + MIN_FREE_BYTES),
                "runtime": {"checked": False, "reason": "Run the separate read-only preflight."},
            })
            if not result["disk"]["sufficient"]:
                raise BootstrapError("Insufficient host disk space for selected files plus 1 GiB headroom.")
            if args.mode == "prepare":
                prepare(destination, payload)
                result["files"] = verify_prepared(destination)
                if not result["files"]["verified"]:
                    raise BootstrapError("Post-write verification failed; see prepared files before retrying.")
            result["status"] = "prepared-not-activated" if args.mode == "prepare" else "planned-no-files-written"
            exit_code = 0
        result["elapsed_seconds"] = round(time.monotonic() - started, 6)
        result["timing_scope"] = "this command only; not end-to-end startup or engineering"
        print(json.dumps(result, indent=2, sort_keys=True))
        return exit_code
    except (BootstrapError, OSError, tarfile.TarError, UnicodeError) as exc:
        print(json.dumps({"mode": args.mode, "status": "error", "error": str(exc),
                          "activation": activation()}, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
