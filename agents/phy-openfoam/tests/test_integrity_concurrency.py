"""Journal/key concurrency regressions using only fixture-owned temporary stores."""

from __future__ import annotations

import hashlib
import hmac
import json
import multiprocessing
import os
import queue
import stat
import threading
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest
from discovery_physics.core import integrity

SOURCE = Path(__file__).resolve().parents[1] / "tools/openfoam/src"
TIMEOUT = 30


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    assert Path(integrity.__file__).resolve().is_relative_to(SOURCE.resolve())
    for name, relative in (
        ("DISCOVERY_PHYSICS_HOME", "home"),
        ("DISCOVERY_PHYSICS_CONFIG", "config.json"),
        ("DISCOVERY_PHYSICS_RUNS", "runs"),
        ("DISCOVERY_PHYSICS_KEY_FILE", "keys/journal.key"),
        ("LOCALAPPDATA", "app"),
    ):
        monkeypatch.setenv(name, str(tmp_path / relative))
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    run = tmp_path / "runs/one"
    run.mkdir(parents=True)
    return run


@pytest.fixture
def processes():
    context = multiprocessing.get_context("spawn")
    children = []

    def start(target, *args):
        child = context.Process(target=target, args=args, daemon=True)
        child.start()
        children.append(child)
        return child

    yield context, start
    for child in children:
        if child.is_alive():
            child.terminate()
        child.join(TIMEOUT)
        if child.is_alive():
            child.kill()
            child.join(TIMEOUT)
        child.close()


def _existing_key(data=b"fixture-only-key-" * 4):
    path = integrity.key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
    return path


def _append_process(run, worker, count, barrier, results):
    try:
        assert Path(integrity.__file__).resolve().is_relative_to(SOURCE.resolve())
        barrier.wait(TIMEOUT)
        first_key_id = integrity.key_id()
        sequences = [integrity.append(Path(run), "concurrent", worker=worker, item=item,
                                      payload="x" * 2048)["seq"] for item in range(count)]
        results.put(("ok", first_key_id, sequences))
    except BaseException:
        results.put(("error", traceback.format_exc()))


def test_concurrent_process_first_key_and_same_journal_append(isolated_store, processes):
    context, start = processes
    workers, count = 6, 8
    barrier = context.Barrier(workers)
    results = context.Queue()
    assert not integrity.key_path().exists()
    children = [start(_append_process, str(isolated_store), worker, count, barrier, results)
                for worker in range(workers)]
    outcomes = [results.get(timeout=TIMEOUT) for _ in children]
    for child in children:
        child.join(TIMEOUT)
        assert child.exitcode == 0
    assert all(result[0] == "ok" for result in outcomes), outcomes
    assert {result[1] for result in outcomes} == {integrity.key_id()}
    records = integrity.verify_journal(isolated_store)
    assert [record["seq"] for record in records] == list(range(workers * count))
    assert sorted(seq for result in outcomes for seq in result[2]) == list(range(workers * count))
    assert {(record["worker"], record["item"]) for record in records} == {
        (worker, item) for worker in range(workers) for item in range(count)
    }
    assert {record["key_id"] for record in records} == {integrity.key_id()}
    assert len(integrity.key_path().read_bytes()) == 32


def test_concurrent_threads_keep_a_single_valid_chain(isolated_store, monkeypatch):
    _existing_key()
    workers, count = 8, 8
    barrier = threading.Barrier(workers)
    results = queue.Queue()
    real_strftime = integrity.time.strftime

    def interleave(*args):
        # Widen the old read/next-sequence/write race without a barrier inside a lock.
        threading.Event().wait(0.002)
        return real_strftime(*args)

    monkeypatch.setattr(integrity.time, "strftime", interleave)

    def work(worker):
        try:
            barrier.wait(TIMEOUT)
            for item in range(count):
                integrity.append(isolated_store, "thread", worker=worker, item=item)
            results.put(None)
        except BaseException:
            results.put(traceback.format_exc())

    children = [threading.Thread(target=work, args=(worker,), daemon=True)
                for worker in range(workers)]
    for child in children:
        child.start()
    outcomes = [results.get(timeout=TIMEOUT) for _ in children]
    for child in children:
        child.join(TIMEOUT)
        assert not child.is_alive(), "append deadlocked"
    assert outcomes == [None] * workers, outcomes
    records = integrity.verify_journal(isolated_store)
    assert [record["seq"] for record in records] == list(range(workers * count))
    assert {(record["worker"], record["item"]) for record in records} == {
        (worker, item) for worker in range(workers) for item in range(count)
    }


class _SplitWrite:
    def __init__(self, stream, partial, finish):
        self.stream, self.partial, self.finish = stream, partial, finish

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def write(self, text):
        middle = len(text) // 2
        self.stream.write(text[:middle])
        self.stream.flush()
        self.partial.set()
        if not self.finish.wait(TIMEOUT):
            raise TimeoutError("test did not release the split write")
        self.stream.write(text[middle:])
        return len(text)


def _partial_append_process(run, partial, finish, results):
    from unittest.mock import patch

    log = Path(run) / "journal.jsonl"
    original_open = Path.open

    def open_log(path, mode="r", *args, **kwargs):
        stream = original_open(path, mode, *args, **kwargs)
        return _SplitWrite(stream, partial, finish) if path == log and mode == "a" else stream

    try:
        with patch.object(Path, "open", open_log):
            integrity.append(Path(run), "split", payload="x" * 8192)
        results.put(("writer", "ok"))
    except BaseException:
        results.put(("writer", traceback.format_exc()))


def _verify_process(run, started, finished, results):
    started.set()
    try:
        results.put(("reader", len(integrity.verify_journal(Path(run)))))
    except BaseException:
        results.put(("reader", traceback.format_exc()))
    finally:
        finished.set()


def test_verify_waits_for_a_cross_process_partial_append(isolated_store, processes):
    integrity.append(isolated_store, "prepared")
    context, start = processes
    partial, finish = context.Event(), context.Event()
    started, finished = context.Event(), context.Event()
    results = context.Queue()
    writer = start(_partial_append_process, str(isolated_store), partial, finish, results)
    try:
        assert partial.wait(TIMEOUT)
        reader = start(_verify_process, str(isolated_store), started, finished, results)
        assert started.wait(TIMEOUT)
        assert not finished.wait(0.25), "verification observed an in-progress append"
    finally:
        finish.set()
    assert finished.wait(TIMEOUT)
    outcomes = dict(results.get(timeout=TIMEOUT) for _ in range(2))
    assert outcomes == {"writer": "ok", "reader": 2}, outcomes
    for child in (writer, reader):
        child.join(TIMEOUT)
        assert child.exitcode == 0


def _partial_key_process(partial, finish, results):
    from unittest.mock import patch

    original_fdopen = os.fdopen

    def open_key(fd, mode="r", *args, **kwargs):
        stream = original_fdopen(fd, mode, *args, **kwargs)
        return _SplitWrite(stream, partial, finish) if mode == "wb" else stream

    try:
        with patch.object(os, "fdopen", open_key):
            key_id = integrity.key_id()
        results.put(("initializer", key_id))
    except BaseException:
        results.put(("initializer", traceback.format_exc()))


def _key_reader_process(started, finished, results):
    started.set()
    try:
        results.put(("reader", integrity.key_id()))
    except BaseException:
        results.put(("reader", traceback.format_exc()))
    finally:
        finished.set()


def test_key_reader_waits_for_complete_first_initialization(processes):
    context, start = processes
    partial, finish = context.Event(), context.Event()
    started, finished = context.Event(), context.Event()
    results = context.Queue()
    writer = start(_partial_key_process, partial, finish, results)
    try:
        assert partial.wait(TIMEOUT)
        assert integrity.key_path().stat().st_size == 16
        reader = start(_key_reader_process, started, finished, results)
        assert started.wait(TIMEOUT)
        assert not finished.wait(0.25), "reader observed a partial key"
    finally:
        finish.set()
    assert finished.wait(TIMEOUT)
    outcomes = dict(results.get(timeout=TIMEOUT) for _ in range(2))
    assert outcomes == {"initializer": integrity.key_id(), "reader": integrity.key_id()}
    for child in (writer, reader):
        child.join(TIMEOUT)
        assert child.exitcode == 0


def _hold_lock(path, shared, acquired, release, abrupt=False):
    from discovery_physics.core.locking import file_lock

    with file_lock(Path(path), shared=shared):
        acquired.set()
        if not release.wait(TIMEOUT):
            raise TimeoutError("test did not release lock holder")
        if abrupt:
            os._exit(0)  # Deliberately bypass Python cleanup.


def test_os_releases_lock_after_process_exit_without_deleting_it(tmp_path, processes):
    context, start = processes
    path = tmp_path / "persistent.lock"
    acquired, exit_now = context.Event(), context.Event()
    successor, release = context.Event(), context.Event()
    first = start(_hold_lock, str(path), False, acquired, exit_now, True)
    assert acquired.wait(TIMEOUT)
    identity = path.stat()
    second = start(_hold_lock, str(path), False, successor, release)
    try:
        assert not successor.wait(0.25)
        exit_now.set()
        first.join(TIMEOUT)
        assert first.exitcode == 0
        assert successor.wait(TIMEOUT)
        assert os.path.samestat(identity, path.stat())
    finally:
        exit_now.set()
        release.set()
    second.join(TIMEOUT)
    assert second.exitcode == 0
    assert path.exists()


def test_cross_process_read_locks_are_shared(tmp_path, processes):
    context, start = processes
    path = tmp_path / "shared.lock"
    release = context.Event()
    acquired = [context.Event(), context.Event()]
    children = [start(_hold_lock, str(path), True, ready, release) for ready in acquired]
    try:
        assert all(ready.wait(TIMEOUT) for ready in acquired), "read locks were exclusive"
    finally:
        release.set()
    for child in children:
        child.join(TIMEOUT)
        assert child.exitcode == 0


def test_new_key_uses_exclusive_private_creation(monkeypatch):
    path = integrity.key_path()
    original_open = os.open
    calls = []

    def observe_open(filename, flags, mode=0o777, **kwargs):
        if Path(filename) == path:
            calls.append((flags, mode))
        return original_open(filename, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", observe_open)
    key = integrity._key()
    assert len(key) == 32
    assert any(flags & os.O_CREAT and flags & os.O_EXCL and mode == 0o600
               for flags, mode in calls), "key was not created with O_EXCL and mode 0600"
    before = path.stat()
    assert integrity._key() == key
    assert os.path.samestat(before, path.stat())
    assert path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.skipif(os.name != "posix", reason="native Unix permission semantics")
@pytest.mark.parametrize("mask", [0, 0o022])
def test_new_key_is_private_even_with_permissive_umask(mask):
    old = os.umask(mask)
    try:
        integrity._key()
    finally:
        os.umask(old)
    assert stat.S_IMODE(integrity.key_path().stat().st_mode) == 0o600


@pytest.mark.parametrize("mode", [0o600, 0o400, 0o200, 0])
def test_unix_private_modes_validation_on_every_platform(mode):
    integrity._validate_key_stat(SimpleNamespace(st_mode=stat.S_IFREG | mode), posix=True)


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o606, 0o660, 0o777])
def test_unix_unsafe_modes_validation_on_every_platform(mode):
    with pytest.raises(integrity.IntegrityError, match="permission"):
        integrity._validate_key_stat(SimpleNamespace(st_mode=stat.S_IFREG | mode), posix=True)


@pytest.mark.parametrize("kind", [stat.S_IFLNK, stat.S_IFDIR, stat.S_IFIFO, stat.S_IFSOCK])
def test_nonregular_key_stat_validation_on_every_platform(kind):
    with pytest.raises(integrity.IntegrityError, match="regular"):
        integrity._validate_key_stat(SimpleNamespace(st_mode=kind | 0o600), posix=True)


@pytest.mark.skipif(os.name != "posix", reason="native Unix permission semantics")
def test_unsafe_existing_key_is_not_chmodded_or_replaced():
    path = _existing_key()
    path.chmod(0o644)
    before = path.read_bytes(), path.stat()
    with pytest.raises(integrity.IntegrityError, match="permission"):
        integrity._key()
    assert path.read_bytes() == before[0]
    assert os.path.samestat(path.stat(), before[1])
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


@pytest.mark.parametrize("size", [0, 1, 31])
def test_short_existing_key_fails_without_reinitialization(size):
    path = _existing_key(b"k" * size)
    before = path.stat()
    with pytest.raises(integrity.IntegrityError, match="too short"):
        integrity._key()
    assert path.read_bytes() == b"k" * size
    assert os.path.samestat(before, path.stat())
    assert path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize("dangling", [False, True])
def test_symlink_key_is_rejected_without_touching_target(tmp_path, dangling):
    path = integrity.key_path()
    path.parent.mkdir(parents=True)
    target = tmp_path / "target.key"
    if not dangling:
        target.write_bytes(b"fixture-target-" * 4)
        target.chmod(0o600)
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    before = target.read_bytes() if target.exists() else None
    with pytest.raises(integrity.IntegrityError, match="regular|symlink"):
        integrity._key()
    assert path.is_symlink()
    assert (target.read_bytes() if target.exists() else None) == before


def test_nonregular_key_is_rejected():
    integrity.key_path().mkdir(parents=True)
    with pytest.raises(integrity.IntegrityError, match="regular"):
        integrity._key()


def test_legacy_record_and_long_valid_key_are_preserved(isolated_store, monkeypatch):
    key_path = _existing_key()
    key = key_path.read_bytes()
    record = {"seq": 0, "time": "2026-01-01T00:00:00Z", "event": "prepared",
              "prev": integrity.GENESIS,
              "key_id": hashlib.sha256(b"key-id:" + key).hexdigest()[:16]}
    record["hash"] = integrity.sha256_text(integrity.canonical_json(record))
    record["mac"] = hmac.new(key, record["hash"].encode("ascii"), hashlib.sha256).hexdigest()
    log = isolated_store / "journal.jsonl"
    log.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    original = log.read_bytes()
    key_stat = key_path.stat()
    monkeypatch.setattr(integrity.secrets, "token_bytes",
                        lambda *args: pytest.fail("valid key must never be regenerated"))
    assert integrity.verify_journal(isolated_store) == [record]
    integrity.append(isolated_store, "next")
    assert log.read_bytes().startswith(original)
    assert [item["seq"] for item in integrity.verify_journal(isolated_store)] == [0, 1]
    assert key_path.read_bytes() == key
    assert os.path.samestat(key_stat, key_path.stat())
    assert key_path.stat().st_mtime_ns == key_stat.st_mtime_ns


@pytest.mark.parametrize("fault", ["body", "signature", "sequence", "json", "truncated",
                                   "empty", "not-object", "nonfinite", "no-newline", "utf8"])
def test_tampered_append_leaves_journal_bytes_unchanged(isolated_store, fault):
    integrity.append(isolated_store, "prepared")
    record = integrity.append(isolated_store, "next")
    log = isolated_store / "journal.jsonl"
    if fault in {"body", "signature", "sequence"}:
        field, value = {"body": ("event", "forged"), "signature": ("mac", "0" * 64),
                        "sequence": ("seq", 99)}[fault]
        record[field] = value
        lines = log.read_text(encoding="utf-8").splitlines()
        lines[-1] = json.dumps(record)
        damaged = ("\n".join(lines) + "\n").encode()
    else:
        damaged = {"json": b"not json\n", "truncated": log.read_bytes()[:-12],
                   "empty": b"", "not-object": b"[]\n", "utf8": b"\xff\n",
                   "no-newline": log.read_bytes().rstrip(b"\r\n"),
                   "nonfinite": b'{"seq":0,"prev":"' + integrity.GENESIS.encode()
                   + b'","value":NaN}\n'}[fault]
    log.write_bytes(damaged)
    key = integrity.key_path().read_bytes()
    with pytest.raises(integrity.IntegrityError):
        integrity.append(isolated_store, "must-not-append")
    assert log.read_bytes() == damaged
    assert integrity.key_path().read_bytes() == key


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object(), {1, 2}])
def test_serialization_failure_does_not_change_journal(isolated_store, value):
    integrity.append(isolated_store, "prepared")
    log = isolated_store / "journal.jsonl"
    before = log.read_bytes()
    with pytest.raises((TypeError, ValueError)):
        integrity.append(isolated_store, "bad-value", value=value)
    assert log.read_bytes() == before
    assert len(integrity.verify_journal(isolated_store)) == 1


@pytest.mark.parametrize("field", ["seq", "time", "prev", "key_id", "hash", "mac"])
def test_reserved_metadata_cannot_corrupt_a_journal(isolated_store, field):
    integrity.append(isolated_store, "prepared")
    log = isolated_store / "journal.jsonl"
    before = log.read_bytes()
    with pytest.raises(ValueError, match="metadata"):
        integrity.append(isolated_store, "override", **{field: "not-allowed"})
    assert log.read_bytes() == before
    assert len(integrity.verify_journal(isolated_store)) == 1


def test_failed_key_write_is_not_retried_or_replaced(monkeypatch):
    original_fdopen = os.fdopen

    class FailedWrite:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def write(self, data):
            self.stream.write(data[:12])
            self.stream.flush()
            raise OSError("fixture key write failure")

    def open_key(fd, mode="r", *args, **kwargs):
        stream = original_fdopen(fd, mode, *args, **kwargs)
        return FailedWrite(stream) if mode == "wb" else stream

    monkeypatch.setattr(os, "fdopen", open_key)
    with pytest.raises(OSError, match="fixture"):
        integrity._key()
    path = integrity.key_path()
    before = path.read_bytes(), path.stat()
    assert len(before[0]) == 12
    with pytest.raises(integrity.IntegrityError, match="too short"):
        integrity._key()
    assert path.read_bytes() == before[0]
    assert os.path.samestat(path.stat(), before[1])
    assert path.stat().st_mtime_ns == before[1].st_mtime_ns


def test_existing_journal_with_missing_key_does_not_initialize_another(
        isolated_store, tmp_path, monkeypatch):
    integrity.append(isolated_store, "prepared")
    log = isolated_store / "journal.jsonl"
    before = log.read_bytes()
    missing = tmp_path / "other-keys/journal.key"
    monkeypatch.setenv("DISCOVERY_PHYSICS_KEY_FILE", str(missing))
    with pytest.raises(integrity.IntegrityError, match="key.*missing"):
        integrity.verify_journal(isolated_store)
    with pytest.raises(integrity.IntegrityError, match="key.*missing"):
        integrity.append(isolated_store, "must-not-reset-key")
    assert not missing.exists()
    assert log.read_bytes() == before