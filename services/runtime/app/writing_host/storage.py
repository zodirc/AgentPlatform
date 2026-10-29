"""作品目录的台账、锁、对账和回收。

作品锁是本机的写屏障：拿到锁就没有别的进程还在写这个作品。
同一任务重入不再对账，避免把本回合自己的 ``running`` 当成崩溃。
标记阶段扫不全则本轮零删除。
"""

from __future__ import annotations

import contextvars
import fcntl
import hashlib
import json
import os
import shutil
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

from app.writing_host.errors import (
    ResumeIncompatible,
    SnapshotCorrupt,
    StorageLow,
    TurnNotRevertable,
)
from app.writing_host.schema import (
    EVENT_KEEP_TURNS,
    LEDGER_SCHEMA,
    SCHEMA_VERSIONS,
    SNAPSHOT_SCHEMA,
)

MIN_FREE_BYTES = 64 * 1024 * 1024
DEFAULT_GC_BUDGET_MS = 1000

_SKIP_PREFIXES = (
    ".agent/checkpoints/",
    ".agent/events/",
    ".agent/snapshots/",
)
_MANUSCRIPT_SKIP = _SKIP_PREFIXES + (
    ".agent/evaluations/",
    ".agent/turns.json",
    ".agent/lock",
)
_TERMINAL = {"completed", "failed", "cancelled"}
_HELD: contextvars.ContextVar[str] = contextvars.ContextVar("work_lock", default="")
_STATUS: contextvars.ContextVar[str] = contextvars.ContextVar("reconcile_status", default="")

crash_at: str | None = None


class Crash(BaseException):
    """测试在落盘边界终止。用 BaseException，避免被回合的 ``except Exception`` 吃掉。"""


@dataclass
class GcReport:
    candidates: int
    deleted: int
    aborted: str = ""
    bytes_reclaimed: int = 0


def gc_report_payload(report: GcReport) -> dict[str, int | str]:
    """命令行打印的字段与服务器指标同名。放弃时 ``gc_deleted`` 为 0。"""
    return {
        "gc_marked": report.candidates,
        "gc_candidates": report.candidates,
        "gc_deleted": 0 if report.aborted else report.deleted,
        "gc_aborted": report.aborted,
        "gc_bytes_reclaimed": 0 if report.aborted else report.bytes_reclaimed,
    }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _maybe_crash(point: str) -> None:
    if crash_at == point:
        raise Crash(point)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes, *, sync_dir: bool = True, crash_point: str | None = None) -> None:
    """临时文件 fsync 后 rename。crash_point 在 rename 之前触发，目标名上不会留下半截内容。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f"tmp-{uuid4().hex}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    if crash_point:
        _maybe_crash(crash_point)
    os.replace(tmp, path)
    if sync_dir:
        _fsync_dir(path.parent)


def _ledger_path(root: Path) -> Path:
    return root / ".agent" / "turns.json"


def _empty_ledger() -> dict[str, Any]:
    return {"schema_version": LEDGER_SCHEMA, "next_seq": 1, "turns": []}


def load_ledger(root: Path) -> tuple[dict[str, Any] | None, str]:
    path = _ledger_path(root)
    if not path.is_file():
        return None, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "ledger_corrupt"
    if not isinstance(data, dict) or not isinstance(data.get("turns"), list):
        return None, "ledger_corrupt"
    try:
        version = int(data.get("schema_version") or 0)
    except (TypeError, ValueError):
        return None, "ledger_corrupt"
    if version > LEDGER_SCHEMA:
        return None, "ledger_corrupt"
    return data, ""


def save_ledger(root: Path, data: dict[str, Any]) -> None:
    data["schema_version"] = LEDGER_SCHEMA
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    atomic_write(_ledger_path(root), payload, crash_point="before-ledger-rename")


def _checkpoint(root: Path, turn_id: str) -> Path:
    return root / ".agent" / "checkpoints" / f"{turn_id}.json"


def _manifest_path(root: Path, turn_id: str) -> Path:
    return root / ".agent" / "snapshots" / "turns" / f"{turn_id}.json"


def _read_manifest(path: Path) -> tuple[dict[str, Any] | None, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "manifest_corrupt"
    if not isinstance(data, dict):
        return None, "manifest_corrupt"
    try:
        version = int(data.get("schema_version") or 0)
    except (TypeError, ValueError):
        return None, "manifest_corrupt"
    if version > SNAPSHOT_SCHEMA:
        return None, "manifest_schema"
    return data, ""


def _manifests(root: Path) -> list[Path]:
    directory = root / ".agent" / "snapshots" / "turns"
    if not directory.is_dir():
        return []
    return [path for path in directory.glob("*.json") if not path.name.startswith("tmp-")]


def reconcile(root: Path) -> str:
    """按打开时对账表对齐台账。返回放弃原因；空串表示可以回收。

    台账无法解析时不覆盖原文件。``running`` 能在这里被改写，是因为调用方已经拿到作品锁。
    """
    root = Path(root)
    data, err = load_ledger(root)
    if err:
        return err
    status = ""
    if data is None:
        data = _migrate(root)
        save_ledger(root, data)
    else:
        changed = False
        for turn in data["turns"]:
            if turn.get("state") != "running":
                continue
            turn["state"] = "interrupted" if _checkpoint(root, str(turn["turn_id"])).is_file() else "failed"
            changed = True
        known = {str(turn.get("turn_id")) for turn in data["turns"]}
        for path in _manifests(root):
            parsed, reason = _read_manifest(path)
            if reason:
                status = _worse(status, reason)
                continue
            if parsed is None:
                continue
            turn_id = str(parsed.get("turn_id") or path.stem)
            if turn_id not in known:
                data["turns"].append(
                    {
                        "turn_id": turn_id,
                        "seq": int(data["next_seq"]),
                        "created_at": str(parsed.get("created_at") or _now()),
                        "state": "completed",
                        "snapshot": True,
                        "recovered": True,
                    }
                )
                data["next_seq"] = int(data["next_seq"]) + 1
                known.add(turn_id)
                changed = True
                continue
            for turn in data["turns"]:
                if str(turn.get("turn_id")) == turn_id and not turn.get("snapshot"):
                    turn["snapshot"] = True
                    changed = True
        roots = _root_ids(data)
        for turn in data["turns"]:
            if not turn.get("snapshot"):
                continue
            # 非根回合的清单缺失是上一轮清扫写到一半，接着删，不当成损坏。
            if str(turn.get("turn_id")) not in roots:
                continue
            path = _manifest_path(root, str(turn["turn_id"]))
            if not path.is_file():
                status = _worse(status, "manifest_corrupt")
                continue
            _parsed, reason = _read_manifest(path)
            if reason:
                status = _worse(status, reason)
        if changed:
            save_ledger(root, data)
    for path in _manifests(root):
        _parsed, reason = _read_manifest(path)
        if reason:
            status = _worse(status, reason)
    return status


def _worse(current: str, reason: str) -> str:
    rank = {"": 0, "manifest_corrupt": 1, "manifest_schema": 2, "ledger_corrupt": 3}
    return reason if rank.get(reason, 1) > rank.get(current, 0) else current


def _migrate(root: Path) -> dict[str, Any]:
    rows: list[tuple[str, str, bool]] = []
    used_mtime = False
    for path in _manifests(root):
        parsed, reason = _read_manifest(path)
        if parsed is None or reason:
            continue
        created = str(parsed.get("created_at") or "")
        if not created:
            created = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            used_mtime = True
        rows.append((created, str(parsed.get("turn_id") or path.stem), True))
    rows.sort()
    data = _empty_ledger()
    if used_mtime:
        data["migrated_from_mtime"] = True
    for created, turn_id, snapshot in rows:
        data["turns"].append(
            {
                "turn_id": turn_id,
                "seq": int(data["next_seq"]),
                "created_at": created,
                "state": "completed",
                "snapshot": snapshot,
            }
        )
        data["next_seq"] = int(data["next_seq"]) + 1
    return data


@contextmanager
def work_lock(root: Path) -> Iterator[None]:
    root = Path(root).resolve()
    key = str(root)
    if _HELD.get() == key:
        yield
        return
    agent = root / ".agent"
    agent.mkdir(parents=True, exist_ok=True)
    fd = os.open(agent / "lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        held = _HELD.set(key)
        status = _STATUS.set(reconcile(root))
        try:
            yield
        finally:
            _STATUS.reset(status)
            _HELD.reset(held)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def open_work(root: Path) -> dict[str, Any]:
    with work_lock(root):
        data, err = load_ledger(root)
        if err:
            return {"aborted": err}
        aborted = _STATUS.get()
        if aborted:
            data = data or _empty_ledger()
            data = dict(data)
            data["aborted"] = aborted
        return data or _empty_ledger()


def begin_turn(root: Path, turn_id: str) -> int:
    """回合第一次写盘之前落下 ``running`` 条目。已有同 id 的条目则把它改回 ``running``。"""
    root = Path(root)
    data, err = load_ledger(root)
    if err:
        raise ResumeIncompatible(detail="ledger")
    if data is None:
        data = _empty_ledger()
    for turn in data["turns"]:
        if str(turn.get("turn_id")) == turn_id:
            turn["state"] = "running"
            save_ledger(root, data)
            return int(turn["seq"])
    seq = int(data["next_seq"])
    data["turns"].append(
        {
            "turn_id": turn_id,
            "seq": seq,
            "created_at": _now(),
            "state": "running",
            "snapshot": False,
        }
    )
    data["next_seq"] = seq + 1
    save_ledger(root, data)
    return seq


def mark_running(root: Path, turn_id: str) -> None:
    data, err = load_ledger(root)
    if err or data is None:
        return
    for turn in data["turns"]:
        if str(turn.get("turn_id")) == turn_id:
            turn["state"] = "running"
            save_ledger(root, data)
            return


def _set_state(root: Path, turn_id: str, state: str) -> None:
    data, err = load_ledger(root)
    if err or data is None:
        return
    for turn in data["turns"]:
        if str(turn.get("turn_id")) == turn_id:
            turn["state"] = state
            save_ledger(root, data)
            return


def mark_snapshot(root: Path, turn_id: str) -> None:
    data, err = load_ledger(root)
    if err or data is None:
        return
    for turn in data["turns"]:
        if str(turn.get("turn_id")) == turn_id:
            turn["snapshot"] = True
            save_ledger(root, data)
            return


def _root_ids(data: dict[str, Any]) -> set[str]:
    turns = [turn for turn in data["turns"] if isinstance(turn, dict) and turn.get("turn_id")]
    ordered = sorted(turns, key=lambda turn: int(turn.get("seq") or 0))
    kept = {str(turn["turn_id"]) for turn in ordered[-EVENT_KEEP_TURNS:]}
    for turn in ordered:
        if turn.get("state") in {"running", "interrupted"}:
            kept.add(str(turn["turn_id"]))
    return kept


def _turn_files(root: Path, turn_id: str) -> list[Path]:
    return [
        _manifest_path(root, turn_id),
        root / ".agent" / "events" / f"{turn_id}.jsonl",
        _checkpoint(root, turn_id),
        root / ".agent" / "evaluations" / f"{turn_id}.jsonl",
    ]


def _tmp_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for directory in (
        root / ".agent",
        root / ".agent" / "snapshots" / "objects",
        root / ".agent" / "snapshots" / "turns",
    ):
        if not directory.is_dir():
            continue
        found.extend(path for path in directory.glob("tmp-*") if path.is_file())
    return found


def _referenced(root: Path, roots: set[str]) -> set[str]:
    used: set[str] = set()
    for turn_id in roots:
        path = _manifest_path(root, turn_id)
        if not path.is_file():
            continue
        parsed, reason = _read_manifest(path)
        if parsed is None or reason:
            continue
        for item in parsed.get("files") or []:
            if isinstance(item, dict) and item.get("sha256"):
                used.add(str(item["sha256"]))
    return used


def _victims(root: Path, data: dict[str, Any]) -> list[Path]:
    roots = _root_ids(data)
    victims: list[Path] = []
    for turn in data["turns"]:
        turn_id = str(turn.get("turn_id") or "")
        if not turn_id or turn_id in roots:
            continue
        victims.extend(path for path in _turn_files(root, turn_id) if path.is_file())
    objects = root / ".agent" / "snapshots" / "objects"
    used = _referenced(root, roots)
    if objects.is_dir():
        for path in objects.iterdir():
            if path.is_file() and not path.name.startswith("tmp-") and path.name not in used:
                victims.append(path)
    victims.extend(_tmp_files(root))
    return victims


def _gc_locked(
    root: Path,
    budget_ms: int,
    on_progress: Callable[[int, int], None] | None,
) -> GcReport:
    """扫不全就整轮放弃，一个文件都不删。候选数在删除前定死。"""
    status = _STATUS.get()
    if status:
        return GcReport(0, 0, aborted=status)
    for path in _manifests(root):
        _parsed, reason = _read_manifest(path)
        if reason:
            return GcReport(0, 0, aborted=reason)
    data, err = load_ledger(root)
    if err:
        return GcReport(0, 0, aborted=err)
    if data is None:
        return GcReport(0, 0, aborted="")
    roots = _root_ids(data)
    for turn in data["turns"]:
        if not turn.get("snapshot") or str(turn.get("turn_id")) not in roots:
            continue
        path = _manifest_path(root, str(turn.get("turn_id")))
        if not path.is_file():
            return GcReport(0, 0, aborted="manifest_corrupt")
    victims = _victims(root, data)
    candidates = len(victims)
    if on_progress is not None:
        on_progress(0, candidates)
    deadline = time.monotonic() + max(0, budget_ms) / 1000
    deleted = 0
    reclaimed = 0
    for path in victims:
        if time.monotonic() >= deadline:
            break
        try:
            reclaimed += path.stat().st_size
        except OSError:
            pass
        path.unlink(missing_ok=True)
        deleted += 1
        if on_progress is not None:
            on_progress(deleted, candidates)
        if crash_at == "after-first-delete" and deleted == 1:
            raise Crash("after-first-delete")
    if deleted == len(victims):
        roots = _root_ids(data)
        data["turns"] = [turn for turn in data["turns"] if str(turn.get("turn_id")) in roots]
        save_ledger(root, data)
    return GcReport(candidates, deleted, aborted="", bytes_reclaimed=reclaimed)


def gc_work(
    root: Path,
    budget_ms: int = DEFAULT_GC_BUDGET_MS,
    on_progress: Callable[[int, int], None] | None = None,
) -> GcReport:
    with work_lock(root):
        return _gc_locked(Path(root), budget_ms, on_progress)


def finish_turn(
    root: Path,
    turn_id: str,
    state: str,
    *,
    budget_ms: int = DEFAULT_GC_BUDGET_MS,
    on_progress: Callable[[int, int], None] | None = None,
) -> GcReport:
    if state not in _TERMINAL:
        raise ValueError(state)
    _set_state(root, turn_id, state)
    return _gc_locked(Path(root), budget_ms, on_progress)


def write_snapshot(root: Path, turn_id: str) -> None:
    """对象、目录、清单、台账按这个顺序落盘。清单写完才把台账的 snapshot 置上。"""
    root = Path(root)
    with work_lock(root):
        objects = root / ".agent" / "snapshots" / "objects"
        objects.mkdir(parents=True, exist_ok=True)
        files: list[dict[str, str]] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel.startswith(_SKIP_PREFIXES) or rel in {".agent/host.json", ".agent/turns.json", ".agent/lock"}:
                continue
            files.append({"path": rel, "sha256": store_object(objects, path.read_bytes())})
        _fsync_dir(objects)
        _maybe_crash("after-objects-before-manifest")
        manifest = {
            "schema_version": SNAPSHOT_SCHEMA,
            "turn_id": turn_id,
            "created_at": _now(),
            "files": files,
        }
        atomic_write(
            root / ".agent" / "snapshots" / "turns" / f"{turn_id}.json",
            json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
            crash_point="before-manifest-rename",
        )
        mark_snapshot(root, turn_id)


def store_object(objects: Path, data: bytes) -> str:
    """同名对象先校验内容。一致才跳过，不一致就覆盖，不把坏文件留在哈希名上。"""
    digest = _sha(data)
    target = objects / digest
    if target.is_file() and _sha(target.read_bytes()) == digest:
        return digest
    atomic_write(target, data, sync_dir=False, crash_point="before-object-rename")
    return digest


def resumable(root: Path) -> list[dict[str, Any]]:
    from app.writing_host.files import FileCheckpointStore

    with work_lock(root):
        data, err = load_ledger(root)
        if err or data is None:
            return []
        checkpoints = {row["turn_id"]: row for row in FileCheckpointStore(root).list_turns()}
        rows = []
        for turn in sorted(data["turns"], key=lambda item: int(item.get("seq") or 0)):
            if turn.get("state") != "interrupted":
                continue
            found = checkpoints.get(str(turn.get("turn_id")))
            if found is None:
                continue
            rows.append(found)
        return rows


def history(root: Path) -> list[dict[str, Any]]:
    with work_lock(root):
        data, err = load_ledger(root)
        if err or data is None:
            return []
        rows = [turn for turn in data["turns"] if turn.get("snapshot")]
        rows.sort(key=lambda turn: int(turn.get("seq") or 0))
        return rows


def revert_turn(root: Path, turn_id: str) -> None:
    root = Path(root)
    with work_lock(root):
        data, err = load_ledger(root)
        if err or data is None:
            raise TurnNotRevertable()
        roots = _root_ids(data)
        entry = next((turn for turn in data["turns"] if str(turn.get("turn_id")) == turn_id), None)
        in_window = entry is not None and bool(entry.get("snapshot")) and turn_id in roots
        if not in_window:
            snapshots = [turn for turn in data["turns"] if turn.get("snapshot")]
            if entry is not None and entry.get("snapshot") and turn_id not in roots:
                raise TurnNotRevertable()
            if len(snapshots) >= EVENT_KEEP_TURNS:
                raise TurnNotRevertable()
            raise FileNotFoundError(turn_id)
        assert entry is not None
        manifest, reason = _read_manifest(_manifest_path(root, turn_id))
        if manifest is None or reason:
            raise SnapshotCorrupt()
        objects = root / ".agent" / "snapshots" / "objects"
        wanted: dict[str, str] = {}
        payloads: list[tuple[Path, bytes]] = []
        for item in manifest.get("files") or []:
            if not isinstance(item, dict):
                continue
            rel = str(item.get("path") or "")
            digest = str(item.get("sha256") or "")
            target = (root / rel).resolve()
            try:
                target.relative_to(root.resolve())
            except ValueError:
                raise SnapshotCorrupt() from None
            blob_path = objects / digest
            if not blob_path.is_file():
                raise SnapshotCorrupt()
            blob = blob_path.read_bytes()
            if _sha(blob) != digest:
                raise SnapshotCorrupt()
            wanted[rel] = digest
            payloads.append((target, blob))
        for target, blob in payloads:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
        for path in list(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel.startswith(_SKIP_PREFIXES) or rel in wanted:
                continue
            if rel.startswith(".agent/") and not rel.startswith(".agent/work/"):
                continue
            path.unlink(missing_ok=True)
        boundary = int(entry["seq"])
        drop = {str(turn["turn_id"]) for turn in data["turns"] if int(turn.get("seq") or 0) >= boundary}
        for dropped in drop:
            for path in _turn_files(root, dropped):
                path.unlink(missing_ok=True)
        data["turns"] = [turn for turn in data["turns"] if str(turn.get("turn_id")) not in drop]
        save_ledger(root, data)
        _gc_locked(root, DEFAULT_GC_BUDGET_MS, None)


def free_bytes(path: Path) -> int:
    target = path if path.exists() else path.parent
    return int(shutil.disk_usage(target).free)


def ensure_space(root: Path, min_free_bytes: int | None = None) -> None:
    need = MIN_FREE_BYTES if min_free_bytes is None else int(min_free_bytes)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if free_bytes(root) >= need:
        return
    gc_work(root)
    if free_bytes(root) < need:
        raise StorageLow()


def import_staging_root(work_root: Path) -> Path:
    """暂存目录在作品目录的上两级，不落在作品列表里面。"""
    return Path(work_root).resolve().parent.parent / "import-staging"


def cleanup_import_staging(work_root: Path) -> None:
    staging = import_staging_root(work_root)
    if not staging.is_dir():
        return
    for child in staging.iterdir():
        shutil.rmtree(child, ignore_errors=True)


def _zip_name(info: zipfile.ZipInfo, seen: set[str]) -> str:
    name = info.filename.replace("\\", "/")
    if name.endswith("/"):
        return ""
    mode = (info.external_attr >> 16) & 0o170000
    if mode == 0o120000:
        raise ValueError("symlink")
    parts = name.split("/")
    if name.startswith("/") or (len(name) >= 2 and name[1] == ":"):
        raise ValueError("path")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("path")
    if name in seen:
        raise ValueError("duplicate")
    seen.add(name)
    return name


def _extract_zip(src: Path, staging: Path) -> None:
    seen: set[str] = set()
    with zipfile.ZipFile(src) as archive:
        members = [(info, _zip_name(info, seen)) for info in archive.infolist()]
        for info, name in members:
            if not name:
                continue
            dest = (staging / name).resolve()
            try:
                dest.relative_to(staging.resolve())
            except ValueError:
                raise ValueError("path") from None
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as incoming, dest.open("wb") as handle:
                shutil.copyfileobj(incoming, handle)


def _validate_import(staging: Path) -> None:
    meta_path = staging / "export.json"
    if not meta_path.is_file():
        raise ValueError("export.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    incoming = meta.get("schema_versions") or {}
    for name, version in incoming.items():
        current = int(SCHEMA_VERSIONS.get(name) or 0)
        if int(version) > current:
            raise ResumeIncompatible(detail=f"{name} schema {version}")
    data, err = load_ledger(staging)
    if err:
        raise ResumeIncompatible(detail="ledger")
    if data is not None:
        kept = []
        for turn in data["turns"]:
            if turn.get("snapshot") and not _manifest_path(staging, str(turn.get("turn_id"))).is_file():
                continue
            turn["created_at"] = _now()
            turn.pop("recovered", None)
            turn.pop("migrated_from_mtime", None)
            kept.append(turn)
        data["turns"] = kept
        data.pop("migrated_from_mtime", None)
        save_ledger(staging, data)
    for path in _manifests(staging):
        parsed, reason = _read_manifest(path)
        if reason == "manifest_schema":
            raise ResumeIncompatible(detail="snapshot schema")
        if parsed is None or reason:
            raise ValueError("manifest")
    objects = staging / ".agent" / "snapshots" / "objects"
    if objects.is_dir():
        for path in objects.iterdir():
            if not path.is_file() or path.name.startswith("tmp-"):
                continue
            if _sha(path.read_bytes()) != path.name:
                raise ValueError("hash")
    exported = staging / "export.json"
    if exported.is_file():
        exported.unlink()


def _fsync_tree(root: Path) -> None:
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            fd = os.open(Path(dirpath) / name, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        _fsync_dir(Path(dirpath))


def import_work(src: Path, work_root: Path):
    from app.writing_host.works import work_view

    root = Path(work_root)
    if root.exists():
        raise FileExistsError(root)
    cleanup_import_staging(root)
    staging = import_staging_root(root) / uuid4().hex
    committed = False
    try:
        staging.mkdir(parents=True)
        with work_lock(staging):
            _extract_zip(Path(src), staging)
            _validate_import(staging)
            reconcile(staging)
            _fsync_tree(staging)
            root.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, root)
            committed = True
        return work_view(root)
    finally:
        if not committed:
            shutil.rmtree(staging, ignore_errors=True)
