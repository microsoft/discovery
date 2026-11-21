"""Install commit- and SHA256-pinned upstream sources without a package index."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


def checked_archive(spec, cache, offline=False):
    commit, digest = spec["commit"], spec["sha256"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("a full upstream commit and SHA256 are required")
    url = f"https://codeload.github.com/{spec['repository']}/tar.gz/{commit}"
    path = cache / f"{spec['name']}-{commit}.tar.gz"
    if not path.exists():
        if offline:
            raise FileNotFoundError(f"offline source archive missing: {path.name}")
        print("Fetching pinned upstream source: " + spec["name"], flush=True)
        request = urllib.request.Request(url, headers={"User-Agent": "discovery-source-build"})
        with urllib.request.urlopen(request, timeout=120) as response:
            if not response.url.startswith("https://codeload.github.com/"):
                raise ValueError("unexpected upstream source redirect")
            data = response.read(150 * 1024 * 1024 + 1)
        if len(data) > 150 * 1024 * 1024:
            raise ValueError("upstream source exceeds bounded download size")
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("upstream archive SHA256 mismatch: " + spec["name"])
        path.write_bytes(data)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("cached archive SHA256 mismatch: " + spec["name"])
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--archives", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    args.archives.mkdir(parents=True, exist_ok=True)
    specs = json.loads(args.lock.read_text(encoding="utf-8"))["sources"]
    env = dict(os.environ, PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_CONFIG_FILE=os.devnull)
    env.pop("PIP_EXTRA_INDEX_URL", None)
    env.pop("PIP_INDEX_URL", None)
    for spec in specs:
        archive = checked_archive(spec, args.archives, args.offline)
        with tempfile.TemporaryDirectory(prefix="python-source-") as temporary:
            root = Path(temporary)
            with tarfile.open(archive, "r:gz") as stream:
                stream.extractall(root, filter="data")
            directories = [path for path in root.iterdir() if path.is_dir()]
            if len(directories) != 1:
                raise ValueError("upstream archive must have exactly one source root")
            subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-deps",
                            "--no-build-isolation", "--no-cache-dir", str(directories[0])],
                           env=env, check=True)
        actual = importlib.metadata.version(spec["name"])
        if actual != spec["version"]:
            raise ValueError(f"installed {spec['name']} version {actual}, expected {spec['version']}")
    subprocess.run([sys.executable, "-m", "pip", "check"], env=env, check=True)
    receipt = {"package_index_used": False, "certificate_verification": True, "sources": specs}
    (Path(sys.prefix) / "source-dependencies.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()