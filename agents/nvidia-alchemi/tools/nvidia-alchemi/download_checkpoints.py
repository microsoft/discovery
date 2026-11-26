#!/usr/bin/env python3
"""Cache the advertised MLIP checkpoints at build time and verify every one.

Runtime jobs must work offline, so the build fails unless ALL checkpoints listed
in checkpoints.json are present with the expected size and SHA-256 and load.
UMA is intentionally excluded (gated weights; conflicting optional extras).
"""
import hashlib
import json
from pathlib import Path
import sys


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve(entry):
    """Download a named checkpoint without deserializing it."""
    if entry["loader"] == "mace":
        from mace.calculators.foundations_models import download_mace_mp_checkpoint
        return Path(download_mace_mp_checkpoint(entry["name"]))
    if entry["loader"] == "aimnet2":
        from aimnet.calculators.model_registry import get_registry_model_path
        return Path(get_registry_model_path(entry["name"]))
    raise ValueError(f"Unknown loader {entry['loader']!r}")


def load(entry, path):
    # Build hosts have no GPU: load on CPU without cuEquivariance.
    if entry["loader"] == "mace":
        from nvalchemi.models.mace import MACEWrapper
        MACEWrapper.from_checkpoint(path, device="cpu", enable_cueq=False)
    elif entry["loader"] == "aimnet2":
        from nvalchemi.models.aimnet2 import AIMNet2Wrapper
        AIMNet2Wrapper.from_checkpoint(path, device="cpu")
    else:
        raise ValueError(f"Unknown loader {entry['loader']!r}")


def main(spec):
    entries = json.loads(Path(spec).read_text(encoding="utf-8"))["checkpoints"]
    failures = []
    for entry in entries:
        label = f"{entry['loader']}:{entry['name']}"
        try:
            resolved = resolve(entry)
            path = Path(entry["path"])
            if resolved.resolve() != path.resolve():
                raise ValueError(
                    f"resolver returned {resolved}; expected cache path {path}"
                )
            if not path.is_file():
                raise FileNotFoundError(f"expected cache file {path} not created")
            size, digest = path.stat().st_size, sha256(path)
            if size != entry["size"] or digest != entry["sha256"]:
                raise ValueError(f"{path}: size {size}, sha256 {digest}; expected "
                                 f"{entry['size']}, {entry['sha256']}")
            load(entry, path)
            print(f"[ok] {label} {digest}", flush=True)
        except Exception as exc:  # report every failure, then fail the build
            failures.append(f"{label}: {exc}")
            print(f"[failed] {label}: {exc}", flush=True)
    if failures:
        print("Checkpoint caching failed:\n  " + "\n  ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/app/build/checkpoints.json"))
