"""Cooperative file locks: persistent names, thread guards, OS-owned lifetimes.

Never unlink a lock file: a waiter may still hold its inode open. Locks are
nonrecursive; callers must use unlocked private helpers inside a transaction.
Shared locks permit readers in different processes to overlap. A local guard
also serializes threads, including on platforms with process-scoped OS locks.
"""

from __future__ import annotations

import os
import stat
import threading
import weakref
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _Overlapped(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                    ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                    ("hEvent", wintypes.HANDLE)]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _lock_file = _kernel32.LockFileEx
    _lock_file.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                           wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_Overlapped)]
    _lock_file.restype = wintypes.BOOL
    _unlock_file = _kernel32.UnlockFileEx
    _unlock_file.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                             wintypes.DWORD, ctypes.POINTER(_Overlapped)]
    _unlock_file.restype = wintypes.BOOL

    def _lock(fd: int, shared: bool) -> None:
        # A synchronous handle blocks in the kernel, with no CRT ten-retry limit.
        # LockFileEx supplies real shared locks (the CRT's _locking does not).
        flags = 0 if shared else 0x00000002  # LOCKFILE_EXCLUSIVE_LOCK
        if not _lock_file(msvcrt.get_osfhandle(fd), flags, 0, 1, 0,
                          ctypes.byref(_Overlapped())):
            raise ctypes.WinError(ctypes.get_last_error())

    def _unlock(fd: int) -> None:
        if not _unlock_file(msvcrt.get_osfhandle(fd), 0, 1, 0,
                            ctypes.byref(_Overlapped())):
            raise ctypes.WinError(ctypes.get_last_error())

else:
    import fcntl

    def _lock(fd: int, shared: bool) -> None:
        fcntl.flock(fd, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


_registry_guard = threading.Lock()
_thread_locks: weakref.WeakValueDictionary = weakref.WeakValueDictionary()


def _after_fork() -> None:
    global _registry_guard, _thread_locks
    _registry_guard = threading.Lock()
    _thread_locks = weakref.WeakValueDictionary()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)


@contextmanager
def file_lock(path: Path, *, shared: bool = False) -> Iterator[None]:
    """Lock a stable sidecar; close/exit releases ownership, not its pathname.

    All cooperating readers and writers must use the same sidecar. The parent
    directory must already exist. Symlinks/nonregular lock files are refused.
    """
    path = path.parent.resolve() / path.name
    name = os.path.normcase(str(path))
    with _registry_guard:
        guard = _thread_locks.get(name)
        if guard is None:
            guard = threading.Lock()
            _thread_locks[name] = guard
    with guard:
        try:
            before = path.lstat()
        except FileNotFoundError:
            before = None
        if before is not None and not stat.S_ISREG(before.st_mode):
            raise OSError("lock file must be a regular file, not a symlink")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags, 0o600)
        try:
            opened = os.fstat(fd)
            current = path.lstat()
            if (not stat.S_ISREG(opened.st_mode)
                    or not stat.S_ISREG(current.st_mode)
                    or not os.path.samestat(opened, current)
                    or (before is not None and not os.path.samestat(before, opened))):
                raise OSError("lock file changed while opening it")
            _lock(fd, shared)
            try:
                yield
            finally:
                _unlock(fd)
        finally:
            os.close(fd)