"""Prepare exact CDK inputs from a checkout and the approved public release.

Python 3.10+ standard library only. No installation, extraction or computation.
The release may not exist yet: missing or incorrect bytes block preparation.
"""
import argparse
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "package_download", ROOT / "skills" / "quickstart-runner" / "scripts" / "package_download.py"
)
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)

SNAPSHOT = "cdk_non_md_deliverables.zip"
SNAPSHOT_BYTES = 168396900
SNAPSHOT_SHA256 = "bfc939735a574ccc2375ae9808e9242fb79efc545d5b3f314cc38e5d0cefa076"
RELEASE_URL = (
    "https://github.com/microsoft/discovery/releases/download/"
    "cdk-frozen-reference-v0.11/" + SNAPSHOT
)


class HTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise ValueError("Refusing non-HTTPS release redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def verify(path, entry):
    package.require(
        path.stat().st_size == entry["bytes"] and package.digest(path) == entry["sha256"],
        f"Size/SHA256 mismatch: {entry['name']}",
    )


def fetch_snapshot(target, entry):
    try:
        response = build_opener(HTTPSRedirects()).open(RELEASE_URL, timeout=60)
    except HTTPError as error:
        if error.code == 404:
            raise ValueError(
                "Public snapshot unavailable. A maintainer must publish the exact asset "
                "in microsoft/discovery release cdk-frozen-reference-v0.11; do not start setup."
            ) from error
        raise
    with response, target.open("xb") as output:
        package.require(response.status == 200, "Release download did not return HTTP 200")
        total = 0
        while block := response.read(1024 * 1024):
            total += len(block)
            package.require(total <= entry["bytes"], "Release download exceeds expected size")
            output.write(block)
    verify(target, entry)


def prepare(root, destination):
    root, destination = Path(root).absolute(), Path(destination).absolute()
    package.no_links(destination)
    package.require(not destination.exists(), "Destination already exists; nothing overwritten")
    package.require(destination.parent.is_dir(), "Destination parent must exist")
    package.require(
        not destination.resolve().is_relative_to(root.resolve()),
        "Choose a fresh destination outside the repository",
    )
    record, entries = package.load(root, "biopharma")
    package.require(record["guide"] is not None, "Completed guide is required")
    snapshots = [entry for entry in entries if entry["name"] == SNAPSHOT]
    package.require(len(entries) == 7 and len(snapshots) == 1, "Expected guide and six required inputs")
    snapshot = snapshots[0]
    package.require(
        (snapshot["bytes"], snapshot["sha256"]) == (SNAPSHOT_BYTES, SNAPSHOT_SHA256),
        "Inventory does not match the authorized frozen snapshot",
    )
    for entry in entries:
        if entry["name"] != SNAPSHOT:
            verify(package.safe_path(root, entry["path"]), entry)
    runner = package.safe_path(root, "skills/quickstart-runner/SKILL.md")
    licence = package.safe_path(root, "LICENSE")
    package.require(runner.is_file() and licence.is_file(), "Shared runner and licence are required")

    with tempfile.TemporaryDirectory(prefix="cdk-download-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "inputs"
        stage.mkdir()
        # Always prove public availability; a private local ZIP is not a fallback.
        fetch_snapshot(stage / SNAPSHOT, snapshot)
        for entry in entries:
            if entry["name"] != SNAPSHOT:
                shutil.copyfile(package.safe_path(root, entry["path"]), stage / entry["name"])
            verify(stage / entry["name"], entry)
        for source, name in ((runner, "quickstart-runner.md"), (licence, "LICENSE")):
            shutil.copyfile(source, stage / name)
            package.require(package.digest(source) == package.digest(stage / name), "Copy changed bytes")
        package.require(not destination.exists(), "Destination appeared during download; refusing overwrite")
        stage.rename(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True, help="New short folder outside the checkout")
    args = parser.parse_args()
    try:
        destination = prepare(ROOT, args.destination)
    except (OSError, ValueError, KeyError, TypeError, URLError) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 2
    print(f"Prepared guide, six exact inputs, runner and licence in: {destination}")
    print("Attach the guide and quickstart-runner.md in a new Discovery session.")
    print("No archives extracted, dependencies installed or scientific computation performed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
