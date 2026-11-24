"""Machine-wide concurrency cap: N lock files, one held per executing solve."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator

if os.name == "nt":
    import msvcrt

    def _try_lock(fh: IO) -> bool:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
else:
    import fcntl

    def _try_lock(fh: IO) -> bool:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False


class QueueTimeout(RuntimeError):
    pass


@contextmanager
def slot(directory: Path, capacity: int, timeout_s: float, on_wait=None, poll_s: float = 2.0) -> Iterator[int]:
    """Hold one of ``capacity`` slots; the OS releases it if the process dies."""
    directory.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    waited = False
    while True:
        for i in range(capacity):
            fh = open(directory / f"slot-{i}.lock", "a+b")
            if _try_lock(fh):
                try:
                    yield i
                finally:
                    fh.close()
                return
            fh.close()
        if not waited and on_wait:
            on_wait()
        waited = True
        if time.monotonic() > deadline:
            raise QueueTimeout(f"no execution slot free within {timeout_s:.0f} s (capacity {capacity})")
        time.sleep(poll_s)
