"""Landlock FS helpers for tool exec (docs/36 · C0/C1).

Applies a write-jail in the current process (intended for preexec_fn / child
probe): system paths readable+executable; RW only under ``work_root``.

Requires Linux kernel ≥ 5.13 with Landlock LSM. Probe returns False on ENOSYS
(e.g. RHEL 8 / 4.18) so callers can fall back to bwrap / off.
"""

from __future__ import annotations

import ctypes
import errno
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# x86_64 / aarch64 share these numbers for Landlock.
_SYS_LANDLOCK_CREATE_RULESET = 444
_SYS_LANDLOCK_ADD_RULE = 445
_SYS_LANDLOCK_RESTRICT_SELF = 446

_LANDLOCK_CREATE_RULESET_VERSION = 1 << 0
_LANDLOCK_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38

# landlock_access_fs (uapi)
_FS_EXECUTE = 1 << 0
_FS_WRITE_FILE = 1 << 1
_FS_READ_FILE = 1 << 2
_FS_READ_DIR = 1 << 3
_FS_REMOVE_DIR = 1 << 4
_FS_REMOVE_FILE = 1 << 5
_FS_MAKE_CHAR = 1 << 6
_FS_MAKE_DIR = 1 << 7
_FS_MAKE_REG = 1 << 8
_FS_MAKE_SOCK = 1 << 9
_FS_MAKE_FIFO = 1 << 10
_FS_MAKE_BLOCK = 1 << 11
_FS_MAKE_SYM = 1 << 12
_FS_REFER = 1 << 13  # ABI ≥ 2
_FS_TRUNCATE = 1 << 14  # ABI ≥ 3
_FS_IOCTL_DEV = 1 << 15  # ABI ≥ 5

_FS_READ_EXEC = _FS_EXECUTE | _FS_READ_FILE | _FS_READ_DIR
_FS_WRITE_BASE = (
    _FS_WRITE_FILE
    | _FS_REMOVE_DIR
    | _FS_REMOVE_FILE
    | _FS_MAKE_CHAR
    | _FS_MAKE_DIR
    | _FS_MAKE_REG
    | _FS_MAKE_SOCK
    | _FS_MAKE_FIFO
    | _FS_MAKE_BLOCK
    | _FS_MAKE_SYM
)


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


def _libc() -> ctypes.CDLL:
    lib = ctypes.CDLL(None, use_errno=True)
    lib.syscall.restype = ctypes.c_long
    return lib


def landlock_abi_version() -> int:
    """Return Landlock ABI version, or raise OSError if unavailable."""
    if not sys.platform.startswith("linux"):
        raise OSError(errno.ENOSYS, "Landlock requires Linux")
    lib = _libc()
    abi = lib.syscall(
        ctypes.c_long(_SYS_LANDLOCK_CREATE_RULESET),
        ctypes.c_void_p(None),
        ctypes.c_size_t(0),
        ctypes.c_uint32(_LANDLOCK_CREATE_RULESET_VERSION),
    )
    if abi < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    return int(abi)


def _handled_access_fs(abi: int) -> int:
    handled = _FS_READ_EXEC | _FS_WRITE_BASE
    if abi >= 2:
        handled |= _FS_REFER
    if abi >= 3:
        handled |= _FS_TRUNCATE
    if abi >= 5:
        handled |= _FS_IOCTL_DEV
    return handled


def _read_exec_access(abi: int) -> int:
    access = _FS_READ_EXEC
    if abi >= 2:
        access |= _FS_REFER
    return access


def _rw_access(abi: int) -> int:
    return _handled_access_fs(abi)


def _add_path_beneath(lib: ctypes.CDLL, ruleset_fd: int, path: str, allowed: int) -> None:
    fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    try:
        attr = _PathBeneathAttr(allowed_access=allowed, parent_fd=fd)
        err = lib.syscall(
            ctypes.c_long(_SYS_LANDLOCK_ADD_RULE),
            ctypes.c_int(ruleset_fd),
            ctypes.c_uint(_LANDLOCK_RULE_PATH_BENEATH),
            ctypes.byref(attr),
            ctypes.c_uint32(0),
        )
        if err < 0:
            e = ctypes.get_errno()
            raise OSError(e, f"landlock_add_rule({path}): {os.strerror(e)}")
    finally:
        os.close(fd)


def apply_landlock_fs(*, work_root: str | Path) -> None:
    """Restrict the current thread: RW under work_root; RO+exec elsewhere via ``/``."""
    root = str(Path(work_root).resolve())
    if not Path(root).is_dir():
        raise NotADirectoryError(root)

    abi = landlock_abi_version()
    handled = _handled_access_fs(abi)
    lib = _libc()

    attr = _RulesetAttr(handled_access_fs=handled)
    ruleset_fd = lib.syscall(
        ctypes.c_long(_SYS_LANDLOCK_CREATE_RULESET),
        ctypes.byref(attr),
        ctypes.c_size_t(ctypes.sizeof(attr)),
        ctypes.c_uint32(0),
    )
    if ruleset_fd < 0:
        e = ctypes.get_errno()
        raise OSError(e, f"landlock_create_ruleset: {os.strerror(e)}")

    try:
        # Deny-by-default for handled rights; allow read/exec on whole tree.
        _add_path_beneath(lib, int(ruleset_fd), "/", _read_exec_access(abi))
        # Writable jail = current work root only (matches bwrap RW surface).
        _add_path_beneath(lib, int(ruleset_fd), root, _rw_access(abi))

        if lib.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0:
            e = ctypes.get_errno()
            raise OSError(e, f"prctl(NO_NEW_PRIVS): {os.strerror(e)}")

        err = lib.syscall(
            ctypes.c_long(_SYS_LANDLOCK_RESTRICT_SELF),
            ctypes.c_int(int(ruleset_fd)),
            ctypes.c_uint32(0),
        )
        if err < 0:
            e = ctypes.get_errno()
            raise OSError(e, f"landlock_restrict_self: {os.strerror(e)}")
    finally:
        os.close(int(ruleset_fd))
