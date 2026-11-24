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
import stat
import time
from pathlib import Path
from typing import Any

from . import config
from .hashing import canonical_json, sha256_text
from .locking import file_lock

GENESIS = "0" * 64


class IntegrityError(RuntimeError):
    """A run record no longer matches what the deterministic tools wrote."""


def key_path() -> Path:
    env = os.environ.get("DISCOVERY_PHYSICS_KEY_FILE")
    if env:
        return Path(env)
    return config.home() / "keys" / "journal.key"


def _validate_key_stat(info: os.stat_result, *, posix: bool) -> None:
    if not stat.S_ISREG(info.st_mode):
        raise IntegrityError("signing key must be a regular file, not a symlink")
    if posix and stat.S_IMODE(info.st_mode) & 0o077:
        raise IntegrityError("signing key permissions allow group/other access; "
                             "operator action is required (expected mode 0600 or stricter)")


def _read_key(path: Path) -> bytes:
    try:
        before = path.lstat()
    except FileNotFoundError as exc:
        raise IntegrityError("signing key is missing; refusing to initialize a replacement") from exc
    _validate_key_stat(before, posix=os.name == "posix")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        _validate_key_stat(opened, posix=os.name == "posix")
        current = path.lstat()
        _validate_key_stat(current, posix=os.name == "posix")
        if not os.path.samestat(before, opened) or not os.path.samestat(opened, current):
            raise IntegrityError("signing key changed while opening it")
        data = stream.read()
    if len(data) < 32:
        raise IntegrityError("signing key is too short")
    return data


def _key(*, create: bool = True) -> bytes:
    path = key_path()
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.parent.is_dir():
        raise IntegrityError("signing key is missing; refusing to initialize a replacement")
    # Journal transactions acquire journal -> key, never the opposite order.
    # Keep this sidecar forever so waiters cannot lock a replaced inode.
    with file_lock(path.with_name(path.name + ".lock")):
        try:
            path.lstat()
        except FileNotFoundError:
            if not create:
                raise IntegrityError("signing key is missing; refusing to initialize a replacement") from None
            data = secrets.token_bytes(32)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(path, flags, 0o600)
            except FileExistsError:
                # Even a noncooperating initializer must never be overwritten.
                pass
            else:
                # Private from the first byte, even with a permissive Unix umask.
                # A failed write is left for operator inspection, never reset.
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
        return _read_key(path)


def _key_id(key: bytes) -> str:
    return hashlib.sha256(b"key-id:" + key).hexdigest()[:16]


def key_id() -> str:
    return _key_id(_key())


def _mac(digest: str, *, key: bytes | None = None) -> str:
    return hmac.new(_key() if key is None else key, digest.encode("ascii"), hashlib.sha256).hexdigest()


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
    if {"seq", "time", "prev", "key_id", "hash", "mac"}.intersection(data):
        raise ValueError("journal metadata cannot be supplied as event data")
    log = run / "journal.jsonl"
    with file_lock(run / "journal.lock"):
        exists = log.exists()
        key = _key(create=not exists)
        records = _verify_journal_unlocked(run, key) if exists else []
        prev = records[-1]["hash"] if records else GENESIS
        record = {"seq": len(records), "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "event": event, "prev": prev, "key_id": _key_id(key), **data}
        record["hash"] = sha256_text(canonical_json(record))
        record["mac"] = _mac(record["hash"], key=key)
        line = json.dumps(record, sort_keys=True, allow_nan=False) + "\n"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        return record


def verify_journal(run: Path) -> list[dict]:
    if not run.is_dir():
        raise IntegrityError("run journal is missing")
    with file_lock(run / "journal.lock", shared=True):
        return _verify_journal_unlocked(run)


def _verify_journal_unlocked(run: Path, key: bytes | None = None) -> list[dict]:
    """Read/verify under a journal lock; never reacquire that lock recursively."""
    log = run / "journal.jsonl"
    try:
        text = log.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise IntegrityError("run journal is missing") from exc
    except UnicodeDecodeError as exc:
        raise IntegrityError("run journal is not UTF-8") from exc
    if not text:
        raise IntegrityError("run journal is empty")
    if not text.endswith("\n"):
        raise IntegrityError("run journal has an incomplete final line")
    if key is None:
        key = _key(create=False)
    records: list[dict] = []
    prev = GENESIS
    for n, line in enumerate(text.splitlines()):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IntegrityError(f"journal line {n} is not JSON") from exc
        if not isinstance(rec, dict):
            raise IntegrityError(f"journal line {n} is not a JSON object")
        body = {k: v for k, v in rec.items() if k not in ("hash", "mac")}
        if rec.get("seq") != n or rec.get("prev") != prev:
            raise IntegrityError(f"journal chain broken at record {n}")
        try:
            digest = sha256_text(canonical_json(body))
        except (TypeError, ValueError) as exc:
            raise IntegrityError(f"journal record {n} has invalid JSON values") from exc
        if digest != rec.get("hash"):
            raise IntegrityError(f"journal record {n} was modified")
        mac = rec.get("mac")
        if (not isinstance(mac, str) or not mac.isascii()
                or not hmac.compare_digest(_mac(rec["hash"], key=key), mac)):
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
