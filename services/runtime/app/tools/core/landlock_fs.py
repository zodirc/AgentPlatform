"""Landlock FS 辅助：叠在 bwrap 里面的第二层。

系统目录只读可执行，工作根可写，不给整棵 ``/`` 授权。需 Linux ≥5.13。
内核没有 Landlock 时由调用方继续执行（bwrap 仍在）。本文件可被 bwrap
直接当作脚本运行，不依赖应用包。
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

# Read/execute roots inside the sandbox. ``/`` is intentionally absent so other
# work trees, ``/app``, and ``/home`` are not readable. Missing paths are skipped.
LANDLOCK_READ_ROOTS: tuple[str, ...] = (
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/lib32",
    "/etc",
    "/opt",
    "/proc",
)

# x86_64 numbers. The filter denies these and allows every other syscall.
DENIED_SYSCALLS: dict[str, int] = {
    "ptrace": 101,
    "mount": 165,
    "umount2": 166,
    "keyctl": 250,
    "perf_event_open": 298,
    "bpf": 321,
}

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
    """Landlock ``landlock_ruleset_attr`` 用户态镜像。"""
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _RulesetAttrNet(ctypes.Structure):
    """ABI ≥ 4 adds ``handled_access_net``. No allow rule means TCP connect is denied."""
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
    ]


_NET_CONNECT_TCP = 1 << 1


class _PathBeneathAttr(ctypes.Structure):
    """Landlock ``landlock_path_beneath_attr`` 用户态镜像。"""
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


def _libc() -> ctypes.CDLL:
    """加载 libc 并配置 ``syscall`` restype。"""
    lib = ctypes.CDLL(None, use_errno=True)
    lib.syscall.restype = ctypes.c_long
    return lib


def landlock_abi_version() -> int:
    """探测 Landlock ABI 版本；非 Linux 或不可用时抛 ``OSError``。"""
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
    """按 ABI 版本返回 ruleset 应声明的 FS 权限位掩码。"""
    handled = _FS_READ_EXEC | _FS_WRITE_BASE
    if abi >= 2:
        handled |= _FS_REFER
    if abi >= 3:
        handled |= _FS_TRUNCATE
    if abi >= 5:
        handled |= _FS_IOCTL_DEV
    return handled


def _read_exec_access(abi: int) -> int:
    """全局只读+执行权限掩码（含 ABI≥2 的 REFER）。"""
    access = _FS_READ_EXEC
    if abi >= 2:
        access |= _FS_REFER
    return access


def _rw_access(abi: int) -> int:
    """work_root 下读写权限掩码（与 handled 一致）。"""
    return _handled_access_fs(abi)


def _add_path_beneath(lib: ctypes.CDLL, ruleset_fd: int, path: str, allowed: int) -> None:
    """向 ruleset 添加 ``LANDLOCK_RULE_PATH_BENEATH`` 规则。"""
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


def apply_landlock_fs(
    *,
    work_root: str | Path,
    extra_writable: tuple[str, ...] = (),
) -> None:
    """限制当前线程：工作根可写，系统目录只读，其余路径不可读。"""
    roots: list[str] = []
    for raw in (work_root, *extra_writable):
        root = str(Path(raw).resolve())
        if Path(root).is_dir() and root not in roots:
            roots.append(root)
    if not roots:
        raise NotADirectoryError(str(work_root))

    abi = landlock_abi_version()
    handled = _handled_access_fs(abi)
    lib = _libc()

    if abi >= 4:
        attr_net = _RulesetAttrNet(
            handled_access_fs=handled,
            handled_access_net=_NET_CONNECT_TCP,
        )
        attr_ref = ctypes.byref(attr_net)
        attr_size = ctypes.sizeof(attr_net)
    else:
        attr = _RulesetAttr(handled_access_fs=handled)
        attr_ref = ctypes.byref(attr)
        attr_size = ctypes.sizeof(attr)
    ruleset_fd = lib.syscall(
        ctypes.c_long(_SYS_LANDLOCK_CREATE_RULESET),
        attr_ref,
        ctypes.c_size_t(attr_size),
        ctypes.c_uint32(0),
    )
    if ruleset_fd < 0:
        e = ctypes.get_errno()
        raise OSError(e, f"landlock_create_ruleset: {os.strerror(e)}")

    try:
        read_access = _read_exec_access(abi)
        for path in LANDLOCK_READ_ROOTS:
            if path in roots or not Path(path).is_dir():
                continue
            _add_path_beneath(lib, int(ruleset_fd), path, read_access)
        write_access = _rw_access(abi)
        for root in roots:
            _add_path_beneath(lib, int(ruleset_fd), root, write_access)
        if Path("/tmp").is_dir() and "/tmp" not in roots:
            _add_path_beneath(lib, int(ruleset_fd), "/tmp", read_access | write_access)

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


def _main(argv: list[str]) -> None:
    """``python landlock_fs.py --root /work [--root /abs] -- cmd args``."""
    roots: list[str] = []
    cmd: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--root" and i + 1 < len(argv):
            roots.append(argv[i + 1])
            i += 2
            continue
        if argv[i] == "--":
            cmd = argv[i + 1 :]
            break
        i += 1
    if not roots or not cmd:
        sys.stderr.write("landlock wrapper: expected --root ROOT -- CMD\n")
        raise SystemExit(2)
    try:
        apply_landlock_fs(work_root=roots[0], extra_writable=tuple(roots[1:]))
    except OSError as exc:
        sys.stderr.write(f"landlock skipped: {exc}\n")
    try:
        apply_seccomp_deny()
    except OSError as exc:
        sys.stderr.write(f"seccomp refused exec: {exc}\n")
        raise SystemExit(1)
    os.execvp(cmd[0], cmd)


def apply_seccomp_deny() -> None:
    """Install a filter that returns EPERM for the credential and escape syscalls."""
    import struct

    bpf_ld_w_abs = 0x00 | 0x00 | 0x20
    bpf_jmp_jeq = 0x05 | 0x10 | 0x00
    bpf_ret = 0x06 | 0x00
    kill = 0x80000000
    errno_eperm = 0x00050000 | 1
    allow = 0x7FFF0000
    inst = [
        struct.pack("HBBI", bpf_ld_w_abs, 0, 0, 4),
        struct.pack("HBBI", bpf_jmp_jeq, 1, 0, 0xC000003E),
        struct.pack("HBBI", bpf_ret, 0, 0, kill),
        struct.pack("HBBI", bpf_ld_w_abs, 0, 0, 0),
    ]
    for number in DENIED_SYSCALLS.values():
        inst.append(struct.pack("HBBI", bpf_jmp_jeq, 0, 1, number))
        inst.append(struct.pack("HBBI", bpf_ret, 0, 0, errno_eperm))
    inst.append(struct.pack("HBBI", bpf_ret, 0, 0, allow))
    blob = b"".join(inst)
    buf = ctypes.create_string_buffer(blob)

    class _Fprog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]

    prog = _Fprog(len=len(inst), filter=ctypes.addressof(buf))
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        err = ctypes.get_errno()
        raise OSError(err, "prctl(NO_NEW_PRIVS)")
    # PR_SET_SECCOMP = 22, SECCOMP_MODE_FILTER = 2
    if libc.prctl(22, 2, ctypes.byref(prog), 0, 0) != 0:
        err = ctypes.get_errno()
        raise OSError(err, "seccomp")


if __name__ == "__main__":
    _main(sys.argv[1:])
