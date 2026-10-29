"""Work 回收：先列盘再读库，然后按正向条件清扫。

拿不到排他锁则跳过。列举或查询失败则本轮零删除。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CLAIM_SQL = """
SELECT id, payload, attempts, max_attempts
FROM outbox_jobs
WHERE job_type = 'work_gc'
  AND status IN ('pending', 'retry')
  AND available_at <= now()
ORDER BY created_at
FOR UPDATE SKIP LOCKED
LIMIT $1
"""

_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_GRACE = timedelta(hours=1)


@dataclass(frozen=True)
class MarkReport:
    skipped: bool
    candidates: int
    aborted: str | None = None
    deleted: int = 0


def list_turn_tags(work_root: Path) -> dict[str, str] | None:
    """列举当时的 ``refs/tags/turn/``。失败返回 None，调用方本轮零删除。"""
    from app.policy.shadow_git import _git

    try:
        proc = _git(
            work_root,
            "for-each-ref",
            "--format=%(refname) %(objectname)",
            "refs/tags/turn/",
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    found: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[0].startswith("refs/tags/turn/"):
            continue
        found[parts[0].removeprefix("refs/tags/turn/")] = parts[1]
    return found


def candidates_from_snapshot(listed: dict[str, str], live_turn_ids: set[str]) -> list[str]:
    """候选在列举时固定。列举之后新建的标签不在这份字典里，也就不是候选。"""
    return sorted(turn_id for turn_id in listed if turn_id not in live_turn_ids)


def tag_is_candidate(
    *,
    exists: bool,
    terminal: bool,
    in_window: bool,
    updated_at: datetime | None,
    now: datetime,
) -> bool:
    """删除条件成立才算候选。非终态、窗口内、宽限内都不是。"""
    if not exists:
        return True
    if not terminal or in_window:
        return False
    if updated_at is None:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    moment = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return updated_at < moment - _GRACE


def list_side_names(work_root: Path) -> str | None:
    """旁路目录列举失败时返回原因。目录不存在当作空，不算失败。"""
    from app.policy.shadow_git import shadow_dir
    from app.settings import settings

    git_dir = shadow_dir(work_root)
    paths = (
        git_dir / "recorded",
        git_dir / "absent",
        work_root / ".agent" / "thinking",
        Path(settings.data_dir) / "quarantine",
    )
    for path in paths:
        if not path.exists():
            continue
        try:
            list(path.iterdir())
        except OSError:
            return "side_list_failed"
    return None


async def mark_work(
    conn: Any,
    *,
    work_id: str,
    work_root: Path,
    live_turn_ids: set[str],
    window_ids: set[str] | None = None,
    load_roots: bool = False,
    quarantine_root: Path | None = None,
) -> MarkReport:
    """先列盘，再读库。拿不到排他锁就跳过。失败则零删除。

    锁内没有非终态 run 时改存量提交，并压缩。有非终态 run 时标签清扫照常，压缩跳过。
    """
    try:
        locked = await conn.fetchval(
            "SELECT pg_try_advisory_lock(hashtextextended($1::text, 0))",
            work_id,
        )
    except Exception:
        return MarkReport(skipped=False, candidates=0, aborted="db")
    if not locked:
        return MarkReport(skipped=True, candidates=0, aborted=None)
    try:
        listed, report = _list_for_mark(work_root, live_turn_ids)
        facts = None
        if report.aborted is None and load_roots:
            facts = await _read_roots(conn, work_id)
            if facts is None:
                report = MarkReport(skipped=False, candidates=0, aborted="db")
            else:
                window, keep = roots_from_rows(
                    facts["rows"],
                    now=facts["now"],
                    keep_turns=facts["keep_turns"],
                    keep_days=facts["keep_days"],
                )
                window_ids = window
                names = [
                    turn_id
                    for turn_id in listed
                    if tag_is_candidate(
                        exists=turn_id in facts["present"],
                        terminal=turn_id not in facts["busy_ids"],
                        in_window=turn_id in window,
                        updated_at=facts["updated"].get(turn_id),
                        now=facts["now"],
                    )
                ]
                report = MarkReport(skipped=False, candidates=len(names), aborted=None)
                live_turn_ids = keep
        compress_note = None
        if report.aborted is None:
            try:
                busy = await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM runs r
                        JOIN turns t ON t.id = r.turn_id
                        JOIN sessions s ON s.id = t.session_id
                        WHERE s.work_id = $1::uuid
                          AND r.status NOT IN ('completed', 'failed', 'cancelled')
                    )
                    """,
                    work_id,
                )
            except Exception:
                report = MarkReport(skipped=False, candidates=0, aborted="db")
            else:
                if not busy:
                    migrated = migrate_legacy_shadow(
                        work_root,
                        in_window=set(live_turn_ids if window_ids is None else window_ids),
                    )
                    if migrated == "disk_low":
                        compress_note = "disk_low"
                    elif migrated is not None:
                        report = MarkReport(skipped=False, candidates=0, aborted=migrated)
        deleted = 0
        if report.aborted is None:
            now = facts["now"] if facts else datetime.now(timezone.utc)
            present = facts["present"] if facts else set(live_turn_ids)
            deleted = 0
            if quarantine_root is not None:
                found = await _quarantine_targets(conn, quarantine_root, now)
                if found is None:
                    report = MarkReport(skipped=False, candidates=0, aborted="db")
                else:
                    extra = _unlink_files(found, now)
                    deleted += extra
            if report.aborted is None:
                deleted += sweep_snapshot(
                    work_root,
                    listed,
                    keep=set(live_turn_ids),
                    present=present,
                    now=now,
                )
                if not busy and compress_note is None:
                    compressed = _compress(work_root)
                    if compressed is not None:
                        compress_note = compressed
                if compress_note:
                    report = MarkReport(
                        skipped=False,
                        candidates=report.candidates,
                        aborted=compress_note,
                        deleted=deleted,
                    )
                if facts is not None:
                    fate = directory_fate(
                        work_exists=bool(facts["work_exists"]),
                        deleted_at=facts["deleted_at"],
                        now=now,
                    )
                    if fate == "delete":
                        remove_reclaimed_work(work_root)
                        try:
                            await conn.execute(
                                "DELETE FROM work_tombstones WHERE work_id = $1::uuid",
                                work_id,
                            )
                        except Exception:
                            report = MarkReport(skipped=False, candidates=0, aborted="db", deleted=deleted)
                    elif fate == "alert":
                        logger.warning("work directory has no tombstone and no works row work_id=%s", work_id)
                        from app.observability.metrics import metrics

                        metrics.inc("gc_candidates", layer="2")
                    try:
                        await conn.execute(
                            """
                            DELETE FROM work_memories
                            WHERE session_id IS NOT NULL
                              AND NOT EXISTS (
                                  SELECT 1 FROM sessions s WHERE s.id = work_memories.session_id
                              )
                            """
                        )
                    except Exception:
                        report = MarkReport(
                            skipped=False,
                            candidates=report.candidates,
                            aborted="db",
                            deleted=deleted,
                        )
        if report.aborted is None:
            report = MarkReport(
                skipped=False,
                candidates=report.candidates,
                aborted=None,
                deleted=deleted,
            )
        _emit_gc(report)
        recorded = await _insert_gc_run(conn, work_id, report)
        if not recorded:
            report = MarkReport(skipped=False, candidates=0, aborted="db", deleted=0)
        return report
    finally:
        try:
            await conn.execute(
                "SELECT pg_advisory_unlock(hashtextextended($1::text, 0))",
                work_id,
            )
        except Exception:
            return MarkReport(skipped=False, candidates=0, aborted="db", deleted=0)


def _list_for_mark(work_root: Path, live_turn_ids: set[str]) -> tuple[dict[str, str], MarkReport]:
    if not work_root.exists() or not os.access(work_root, os.R_OK):
        return {}, MarkReport(skipped=False, candidates=0, aborted="work_unreadable")
    listed = list_turn_tags(work_root)
    if listed is None:
        return {}, MarkReport(skipped=False, candidates=0, aborted="git_list_failed")
    side = list_side_names(work_root)
    if side is not None:
        return listed, MarkReport(skipped=False, candidates=0, aborted=side)
    names = candidates_from_snapshot(listed, live_turn_ids)
    return listed, MarkReport(skipped=False, candidates=len(names), aborted=None)


def _mark_locked(work_root: Path, live_turn_ids: set[str]) -> MarkReport:
    return _list_for_mark(work_root, live_turn_ids)[1]


def directory_fate(*, work_exists: bool, deleted_at: datetime | None, now: datetime) -> str:
    """有墓碑且已过宽限才删目录。没有墓碑也没有 Work 行则告警，不删。"""
    if work_exists:
        return "keep"
    if deleted_at is None:
        return "alert"
    moment = deleted_at if deleted_at.tzinfo else deleted_at.replace(tzinfo=timezone.utc)
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    if moment < current - _GRACE:
        return "delete"
    return "keep"


def _mtime_too_new(path: Path, now: datetime) -> bool:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return True
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return mtime > current - _GRACE


def cas_delete_tag(work_root: Path, turn_id: str, sha: str) -> bool:
    """比较并交换删除。失败说明标签在列举之后被移动过，本标签本轮不删文件。"""
    from app.policy.shadow_git import _git, _tag_ref

    proc = _git(work_root, "update-ref", "-d", _tag_ref(turn_id), sha)
    return proc.returncode == 0


def sweep_snapshot(
    work_root: Path,
    listed: dict[str, str],
    *,
    keep: set[str],
    present: set[str],
    now: datetime,
) -> int:
    """只删列举时的候选。列举之后新建的标签不在 ``listed`` 里。"""
    from app.policy.shadow_git import _safe, shadow_dir

    deleted = 0
    git_dir = shadow_dir(work_root)
    for turn_id, sha in listed.items():
        if turn_id in keep:
            continue
        if not cas_delete_tag(work_root, turn_id, sha):
            continue
        deleted += 1
        for folder in ("recorded", "absent"):
            path = git_dir / folder / _safe(turn_id)
            if path.is_file() and not _mtime_too_new(path, now):
                path.unlink(missing_ok=True)
        if turn_id not in present:
            thinking = work_root / ".agent" / "thinking" / f"{turn_id}.jsonl"
            if thinking.is_file() and not _mtime_too_new(thinking, now):
                thinking.unlink(missing_ok=True)
    return deleted


def _unlink_files(paths: list[Path], now: datetime) -> int:
    deleted = 0
    for path in paths:
        if path.is_file() and not _mtime_too_new(path, now):
            path.unlink(missing_ok=True)
            deleted += 1
    return deleted


async def _quarantine_targets(conn: Any, root: Path, now: datetime) -> list[Path] | None:
    """TTL 已过，或 owner Turn 已经不存在，才进入删除集。查询失败则本轮零删除。"""
    if not root.exists():
        return []
    try:
        names = list(root.iterdir())
    except OSError:
        return None
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    targets: list[Path] = []
    stems: set[str] = set()
    for path in names:
        stem = path.name.split(".", 1)[0]
        if not stem or stem in stems:
            continue
        stems.add(stem)
        meta_path = root / f"{stem}.json"
        sample = meta_path if meta_path.is_file() else path
        if _mtime_too_new(sample, current):
            continue
        turn_id = ""
        expired = False
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            turn_id = str(meta.get("turn_id") or "")
            expires = meta.get("expires_at")
            if isinstance(expires, (int, float)) and expires < current.timestamp():
                expired = True
        if not expired:
            if not turn_id:
                continue
            try:
                exists = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM turns WHERE id::text = $1)",
                    turn_id,
                )
            except Exception:
                return None
            if exists:
                continue
        targets.extend(item for item in root.glob(f"{stem}.*") if item.is_file())
    return targets


def remove_reclaimed_work(work_root: Path) -> None:
    """墓碑过宽限后删工作目录和影子目录。拒绝删文件系统根。"""
    from app.policy.shadow_git import shadow_dir

    for path in (work_root, shadow_dir(work_root)):
        resolved = path.resolve()
        if resolved == Path(resolved.anchor) or len(resolved.parts) < 3:
            continue
        if resolved.exists():
            shutil.rmtree(resolved, ignore_errors=True)


def _emit_gc(report: MarkReport) -> None:
    from app.observability.metrics import metrics

    metrics.inc("gc_marked", layer="2")
    if report.candidates:
        metrics.inc("gc_candidates", report.candidates, layer="2")
    if report.deleted:
        metrics.inc("gc_deleted", report.deleted, layer="2")
    if report.aborted:
        metrics.inc("gc_aborted", layer="2", reason=report.aborted)


async def _read_roots(conn: Any, work_id: str) -> dict[str, Any] | None:
    """列举之后再读。同一只读快照里读 Turn、Work 和墓碑。失败则本轮零删除。"""
    from app.settings import settings

    try:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            now = await conn.fetchval("SELECT now()")
            rows = await conn.fetch(ROOTS_SQL, work_id)
            work_exists = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM works WHERE id = $1::uuid)",
                work_id,
            )
            tombstone = await conn.fetchrow(
                "SELECT deleted_at FROM work_tombstones WHERE work_id = $1::uuid",
                work_id,
            )
    except Exception:
        logger.exception("work_gc root read failed work_id=%s", work_id)
        return None
    if now is None:
        return None
    present = {str(row["id"]) for row in rows}
    busy_ids = {str(row["id"]) for row in rows if row["busy"]}
    updated = {str(row["id"]): row["updated_at"] for row in rows}
    return {
        "now": now,
        "rows": list(rows),
        "present": present,
        "busy_ids": busy_ids,
        "updated": updated,
        "work_exists": bool(work_exists),
        "deleted_at": None if tombstone is None else tombstone["deleted_at"],
        "keep_turns": int(settings.writing_revert_keep_turns),
        "keep_days": int(settings.coding_revert_keep_days),
    }


async def _insert_gc_run(conn: Any, work_id: str, report: MarkReport) -> bool:
    """写失败则调用方把本轮改成 db 放弃。本函数不删除。"""
    try:
        await conn.execute(
            """
            INSERT INTO gc_runs (work_id, abort_reason, candidates, deleted)
            VALUES ($1::uuid, $2, $3, $4)
            """,
            work_id,
            report.aborted,
            report.candidates,
            report.deleted,
        )
    except Exception:
        logger.exception("gc_runs insert failed work_id=%s", work_id)
        return False
    return True


def migrate_legacy_shadow(work_root: Path, *, in_window: set[str]) -> str | None:
    """窗口内有父的标签改成无父提交，删掉分支，HEAD 指向空树。

    返回 None 表示改完或本来就是孤儿结构。返回 abort 原因时不删标签。
    空闲空间不够压缩时返回 disk_low，引用已经改完。
    """
    from app.policy.shadow_git import _cas_tag, _commit_tree, _git

    if not (work_root.exists()):
        return "work_unreadable"
    listed = list_turn_tags(work_root)
    if listed is None:
        return "git_list_failed"
    changed = False
    for turn_id, sha in listed.items():
        if turn_id not in in_window:
            continue
        parents = _git(work_root, "rev-list", "--parents", "-1", sha)
        if parents.returncode != 0:
            return "git_migrate_failed"
        parts = parents.stdout.split()
        if len(parts) <= 1:
            continue
        tree = _git(work_root, "rev-parse", f"{sha}^{{tree}}")
        if tree.returncode != 0 or not tree.stdout.strip():
            return "git_migrate_failed"
        new = _commit_tree(work_root, tree.stdout.strip(), "shadow migrate", parent=None)
        if not new:
            return "git_migrate_failed"
        if _cas_tag(work_root, turn_id, new, old=sha):
            changed = True
    heads = _git(work_root, "for-each-ref", "--format=%(refname)", "refs/heads/")
    if heads.returncode != 0:
        return "git_migrate_failed"
    head_tree = _git(work_root, "rev-parse", "HEAD^{tree}")
    if head_tree.returncode != 0 or head_tree.stdout.strip() != _EMPTY_TREE:
        if not _ensure_empty_tree(work_root):
            return "git_migrate_failed"
        empty = _commit_tree(work_root, _EMPTY_TREE, "shadow empty", parent=None)
        if not empty:
            return "git_migrate_failed"
        # HEAD 若是符号引用，不带 --no-deref 会把分支又写回来。
        moved = _git(work_root, "update-ref", "--no-deref", "HEAD", empty)
        if moved.returncode != 0:
            return "git_migrate_failed"
        changed = True
    for ref in heads.stdout.splitlines():
        ref = ref.strip()
        if not ref:
            continue
        deleted = _git(work_root, "update-ref", "-d", ref)
        if deleted.returncode != 0:
            return "git_migrate_failed"
        changed = True
    if not changed:
        return None
    return _compress(work_root)


def _ensure_empty_tree(work_root: Path) -> bool:
    """空树对象不在仓库里时写进去。commit-tree 才能用固定的空树 SHA。"""
    import os
    import subprocess

    from app.policy.shadow_git import shadow_dir

    env = os.environ.copy()
    env["GIT_DIR"] = str(shadow_dir(work_root))
    env["GIT_WORK_TREE"] = str(work_root.resolve())
    proc = subprocess.run(
        ["git", "mktree"],
        cwd=str(work_root),
        env=env,
        input="",
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    return proc.returncode == 0 and proc.stdout.strip() == _EMPTY_TREE


def _compress(work_root: Path) -> str | None:
    """空间不足则不压缩。失败时旧 pack 仍在，本轮不删标签。"""
    from app.policy.shadow_git import _git

    counted = _git(work_root, "count-objects", "-v")
    if counted.returncode != 0:
        return "git_migrate_failed"
    kib = 0
    for line in counted.stdout.splitlines():
        if line.startswith("size:") or line.startswith("size-pack:"):
            kib += int(line.split(":", 1)[1].strip() or "0")
    try:
        free = shutil.disk_usage(work_root).free
    except OSError:
        return "disk_low"
    if free < kib * 1024:
        return "disk_low"
    expired = _git(work_root, "reflog", "expire", "--expire=now", "--all")
    if expired.returncode != 0:
        return "git_migrate_failed"
    packed = _git(work_root, "gc", "--prune=1.hour.ago")
    if packed.returncode != 0:
        return "git_migrate_failed"
    return None


async def claim_work_gc(conn: Any) -> dict[str, Any] | None:
    """领取一条 work_gc。别的领取者已经锁住的行跳过。"""
    row = await conn.fetchrow(CLAIM_SQL, 1)
    if row is None:
        return None
    await conn.execute(
        """
        UPDATE outbox_jobs
        SET status = 'processing', updated_at = now()
        WHERE id = $1
        """,
        row["id"],
    )
    payload = row["payload"]
    if isinstance(payload, str):
        import json

        payload = json.loads(payload)
    return {
        "id": row["id"],
        "payload": payload,
        "attempts": row["attempts"],
        "max_attempts": row["max_attempts"],
    }


ROOTS_SQL = """
SELECT t.id::text AS id, t.scenario_id, t.updated_at, t.created_at,
       EXISTS (
           SELECT 1 FROM runs r
           WHERE r.turn_id = t.id
             AND r.status NOT IN ('completed', 'failed', 'cancelled')
       ) AS busy
FROM turns t
JOIN sessions s ON s.id = t.session_id
WHERE s.work_id = $1::uuid
"""


def roots_from_rows(rows: list[Any], *, now: datetime, keep_turns: int, keep_days: int) -> tuple[set[str], set[str]]:
    """返回 (窗口内 id, 本轮不该算作候选的 id)。查询失败不调用本函数。"""
    writing = sorted(
        (row for row in rows if str(row["scenario_id"] or "") == "writing"),
        key=lambda row: (row["created_at"], row["id"]),
        reverse=True,
    )
    window = {str(row["id"]) for row in writing[: max(1, keep_turns)]}
    horizon = now - timedelta(days=max(1, keep_days))
    grace = now - _GRACE
    keep = set(window)
    for row in rows:
        turn_id = str(row["id"])
        updated = row["updated_at"]
        if str(row["scenario_id"] or "") != "writing" and updated is not None and updated >= horizon:
            window.add(turn_id)
            keep.add(turn_id)
        if row["busy"]:
            keep.add(turn_id)
        if updated is not None and updated >= grace:
            keep.add(turn_id)
    return window, keep


async def claim_and_mark_once() -> None:
    """领取一条任务。列盘在读库之前，查询失败不删除。"""
    from app.db.pool import get_pool
    from app.settings import settings

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            job = await claim_work_gc(conn)
        if job is None:
            return
        payload = job.get("payload") or {}
        work_id = str(payload.get("work_id") or "")
        try:
            root_row = await conn.fetchrow(
                "SELECT work_root FROM works WHERE id = $1::uuid",
                work_id,
            )
            if root_row and root_row["work_root"]:
                work_root = Path(root_row["work_root"])
            else:
                work_root = Path(settings.data_dir) / "works" / work_id
            await mark_work(
                conn,
                work_id=work_id,
                work_root=work_root,
                live_turn_ids=set(),
                load_roots=True,
                quarantine_root=Path(settings.data_dir) / "quarantine",
            )
            await conn.execute(
                """
                UPDATE outbox_jobs
                SET status = 'done', updated_at = now()
                WHERE id = $1
                """,
                job["id"],
            )
        except Exception:
            logger.exception("work_gc mark failed work_id=%s", work_id)
            await conn.execute(
                """
                UPDATE outbox_jobs
                SET status = 'retry',
                    attempts = attempts + 1,
                    updated_at = now(),
                    available_at = now() + interval '30 seconds'
                WHERE id = $1
                """,
                job["id"],
            )


async def work_gc_loop() -> None:
    """runtime 领取 work_gc。api 只入队。"""
    import asyncio

    while True:
        await asyncio.sleep(30)
        try:
            await claim_and_mark_once()
        except Exception:
            logger.exception("work_gc claim failed")

