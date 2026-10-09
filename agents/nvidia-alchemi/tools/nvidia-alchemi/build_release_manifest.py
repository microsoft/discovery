"""Record build provenance: base image, package/checkpoint inventory, source hashes.

Also preserves each installed distribution's license/notice files under
/app/licenses/<distribution>/. Release and base image come from the build
environment (ALCHEMI_AGENT_RELEASE, ALCHEMI_BASE_IMAGE); both are required.
"""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import yaml

LICENSE_NAME = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE|AUTHORS)[^/]*$", re.IGNORECASE)


def preserve_licenses(destination):
    copied = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        if not name:
            continue
        for entry in dist.files or ():
            text = str(entry).replace("\\", "/")
            if ".dist-info/" not in text or not LICENSE_NAME.search(text):
                continue
            source = Path(dist.locate_file(entry))
            if source.is_file():
                target = destination / name / text.split(".dist-info/", 1)[1]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied[name] = copied.get(name, 0) + 1
    return copied


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    root = Path("/app")
    release = os.environ["ALCHEMI_AGENT_RELEASE"]
    base_image = os.environ["ALCHEMI_BASE_IMAGE"]
    if "@sha256:" not in base_image:
        raise SystemExit("ALCHEMI_BASE_IMAGE must be pinned by digest")
    # Sources must match the repository byte for byte (LF), or the recorded hashes
    # cannot be reproduced from a clone. Windows checkouts with autocrlf break this.
    text_inputs = [*root.glob("*.py"), *(root / "tests").glob("*.py"), *(root / "build").iterdir(),
                   root / "agent-source.yaml", root / "tool-definition.yaml", root / "THIRD_PARTY_NOTICES.md"]
    crlf = sorted(str(p) for p in text_inputs if p.is_file() and b"\r\n" in p.read_bytes())
    if crlf:
        raise SystemExit(f"Windows line endings in build inputs; build from a clean git checkout: {crlf}")
    agent = yaml.safe_load((root / "agent-source.yaml").read_text())
    tool = yaml.safe_load((root / "tool-definition.yaml").read_text())
    if tool["version"] != release or not tool["infra"][0]["image"]["acr"].endswith(":" + release):
        raise SystemExit("Tool definition version/tag does not match ALCHEMI_AGENT_RELEASE")
    (root / "agent-instructions.txt").write_text(agent["instructions"], encoding="utf-8")
    packages = {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions() if dist.metadata["Name"]}
    files = {p.name: sha256(p) for p in root.glob("*.py")}
    files["agent-instructions.txt"] = sha256(root / "agent-instructions.txt")
    files["tool-definition.yaml"] = sha256(root / "tool-definition.yaml")
    files["requirements-build.txt"] = sha256(root / "build" / "requirements-build.txt")
    files["checkpoints.json"] = sha256(root / "build" / "checkpoints.json")
    files["download_checkpoints.py"] = sha256(root / "build" / "download_checkpoints.py")
    licenses = preserve_licenses(root / "licenses")
    checkpoints = {}
    for folder in (Path("/opt/cache/mace"), Path("/root/.cache/aimnet")):
        if folder.exists():
            for p in sorted(folder.rglob("*")):
                if p.is_file() and p.stat().st_size > 1_000_000:
                    checkpoints[str(p)] = {"size": p.stat().st_size, "sha256": sha256(p)}
    expected = json.loads((root / "build" / "checkpoints.json").read_text())["checkpoints"]
    for entry in expected:
        if checkpoints.get(entry["path"]) != {"size": entry["size"], "sha256": entry["sha256"]}:
            raise SystemExit(f"Checkpoint mismatch: {entry['path']}")
        # Name each file so consumers can look up a model without guessing from filenames.
        checkpoints[entry["path"]].update(loader=entry["loader"], name=entry["name"])
    unnamed = [p for p, v in checkpoints.items() if "name" not in v]
    if unnamed:
        raise SystemExit(f"Cached checkpoint(s) not listed in checkpoints.json: {unnamed}")
    manifest = {"release": release, "base_image": base_image,
                "python": platform.python_version(), "packages": dict(sorted(packages.items())),
                "source_sha256": dict(sorted(files.items())), "checkpoints": checkpoints,
                "license_files": dict(sorted(licenses.items())),
                "dependency_policy": "Exact versions from requirements-build.txt installed "
                                     "with --no-deps from public indexes; pip check passed"}
    (root / "release-manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    (root / "requirements.lock.txt").write_text("\n".join(f"{n}=={v}" for n,v in sorted(packages.items())) + "\n")
    print(json.dumps({"release": release, "packages": len(packages), "checkpoints": len(checkpoints),
                      "license_distributions": len(licenses)}))