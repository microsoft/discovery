"""Tamper evidence for run records.

Every run keeps an append-only journal whose records are hash-chained and
HMAC-signed with a key held outside the run directory. Decisions (propose,
finalize, continuation) are recomputed from journal-pinned artifacts; editable
JSON copies such as ``assessment.json`` are conveniences and are never trusted.

Threat model: the key protects against edits by anything that cannot read the
key file. On a single-user workstation an agent running as the same OS user can
read it, so local signing proves accidental/naive edits only; production
deployments must place the key with a different principal (cloud runner
identity or a key vault), see docs/architecture.md.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from . import config
from .hashing import canonical_json, sha256_text

GENESIS = "0" * 64


class IntegrityError(RuntimeError):
    """A run record no longer matches what the deterministic tools wrote."""


def key_path() -> Path:
    env = os.environ.get("DISCOVERY_PHYSICS_KEY_FILE")
    if env:
        return Path(env)
    return config.home() / "keys" / "journal.key"


def _key() -> bytes:
    path = key_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(secrets.token_bytes(32))
        try:
            os.replace(tmp, path)
        except PermissionError:
            if not path.exists():
                raise
    data = path.read_bytes()
    if len(data) < 32:
        raise IntegrityError("signing key is too short")
    return data


def key_id() -> str:
    return hashlib.sha256(b"key-id:" + _key()).hexdigest()[:16]


def _mac(digest: str) -> str:
    return hmac.new(_key(), digest.encode("ascii"), hashlib.sha256).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_sha256(root: Path) -> str:
    """Digest of every file (relative path and bytes) under ``root``."""
    entries = {p.relative_to(root).as_posix(): file_sha256(p) for p in sorted(root.rglob("*")) if p.is_file()}
    return sha256_text(canonical_json(entries))


def append(run: Path, event: str, **data: Any) -> dict:
    log = run / "journal.jsonl"
    records = verify_journal(run) if log.exists() else []
    prev = records[-1]["hash"] if records else GENESIS
    record = {"seq": len(records), "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "event": event, "prev": prev, "key_id": key_id(), **data}
    record["hash"] = sha256_text(canonical_json(record))
    record["mac"] = _mac(record["hash"])
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
    return record


def verify_journal(run: Path) -> list[dict]:
    log = run / "journal.jsonl"
    if not log.exists():
        raise IntegrityError("run journal is missing")
    records: list[dict] = []
    prev = GENESIS
    for n, line in enumerate(log.read_text(encoding="utf-8").splitlines()):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IntegrityError(f"journal line {n} is not JSON") from exc
        body = {k: v for k, v in rec.items() if k not in ("hash", "mac")}
        if rec.get("seq") != n or rec.get("prev") != prev:
            raise IntegrityError(f"journal chain broken at record {n}")
        if sha256_text(canonical_json(body)) != rec.get("hash"):
            raise IntegrityError(f"journal record {n} was modified")
        if not hmac.compare_digest(_mac(rec["hash"]), str(rec.get("mac", ""))):
            raise IntegrityError(f"journal record {n} has an invalid signature")
        records.append(rec)
        prev = rec["hash"]
    if not records:
        raise IntegrityError("run journal is empty")
    return records


def last(records: list[dict], *events: str) -> dict | None:
    for rec in reversed(records):
        if rec["event"] in events:
            return rec
    return None


def require_file(path: Path, expected: str | None, what: str) -> None:
    if expected is None:
        raise IntegrityError(f"{what} has no journaled digest")
    if not path.exists() or file_sha256(path) != expected:
        raise IntegrityError(f"{what} changed after it was journaled")
