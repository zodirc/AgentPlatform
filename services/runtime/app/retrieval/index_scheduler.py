"""Turn 外 sources 索引调度（RAG 摄取平面 orchestrator）。

English: Turn-external sources index scheduler — serial sync orchestrator for RAG ingest.

职责：
- 单航班 asyncio 锁串行 sync；startup / watch / CLI / API 共用
- seed + 各 Work private sources 分 scope 同步；跳过 ops-l1 全租户误触
- 协作式取消、跨进程 takeover、孤儿 DB 事务清理

在 RAG 链路中的位置：
  不在 ``search_sources`` 热路径；驱动 ``store.sync`` 与 Ops BEIR/C-MTEB 重嵌。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.settings import settings

logger = logging.getLogger(__name__)

_sync_lock = asyncio.Lock()
_startup_task: asyncio.Task[None] | None = None
# Cooperative cancel: bump generation so in-flight + queued waiters abort.
# Cross-process: also persisted under data_dir so ``make sync`` can preempt
# another docker-exec sync_cli / runtime worker.
_cancel_gen = 0
_cancel_lock = threading.Lock()
_active_cancel_token = threading.local()


class SourcesSyncCancelled(Exception):
    """sources 索引 sync 被显式取消时抛出。"""


def _cancel_gen_path() -> Path:
    from app.settings import settings

    return Path(settings.data_dir) / "vectorstore" / "sync_cancel_gen"


def _read_cancel_gen_file() -> int:
    path = _cancel_gen_path()
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else 0
    except (OSError, ValueError):
        return 0


def _write_cancel_gen_file(gen: int) -> None:
    path = _cancel_gen_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(int(gen)), encoding="utf-8")
    except OSError:
        logger.warning("failed to persist sync cancel gen", exc_info=True)


def bump_sync_cancel() -> int:
    """递增取消代数，使在途 sync 与锁等待者中止；返回新 generation。"""
    global _cancel_gen
    with _cancel_lock:
        file_gen = _read_cancel_gen_file()
        _cancel_gen = max(int(_cancel_gen), int(file_gen)) + 1
        gen = _cancel_gen
        _write_cancel_gen_file(gen)
    logger.info("sources index sync cancel requested; gen=%s", gen)
    return gen


def sync_cancel_token() -> int:
    global _cancel_gen
    with _cancel_lock:
        file_gen = _read_cancel_gen_file()
        if file_gen > _cancel_gen:
            _cancel_gen = file_gen
        return _cancel_gen


def bind_sync_cancel_token(token: int) -> None:
    _active_cancel_token.token = token


def clear_sync_cancel_token() -> None:
    if hasattr(_active_cancel_token, "token"):
        delattr(_active_cancel_token, "token")


def check_sync_cancelled() -> None:
    """嵌入/写入循环中调用；跨进程 cancel 文件与线程 token 均生效。"""
    token = getattr(_active_cancel_token, "token", None)
    if token is None:
        return
    if token != sync_cancel_token():
        raise SourcesSyncCancelled("sources index sync cancelled")


def _terminate_orphan_sync_db_backends() -> list[int]:
    """Kill leftover sync transactions that hold relation locks after SIGTERM.

    A killed ``sync_cli`` often leaves Postgres ``idle in transaction`` for minutes;
    the next sync then blocks forever in ``ensure_schema`` ALTER TABLE.
    Covers product ``DATABASE_URL`` and Ops ``OPS_DATABASE_URL`` / ``BENCH_DATABASE_URL``.
    """
    terminated: list[int] = []
    try:
        import psycopg

        from app.retrieval.ops_plane import resolved_ops_database_url
        from app.settings import settings

        dsns: list[str] = [settings.database_url]
        ops = resolved_ops_database_url()
        if ops and ops not in dsns:
            dsns.append(ops)

        for raw_dsn in dsns:
            dsn = raw_dsn.replace("postgresql+asyncpg://", "postgresql://")
            dsn = dsn.replace("postgres://", "postgresql://")
            try:
                with psycopg.connect(dsn, connect_timeout=5, autocommit=True) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT pid FROM pg_stat_activity
                            WHERE datname = current_database()
                              AND pid <> pg_backend_pid()
                              AND (
                                (
                                  state = 'idle in transaction'
                                  AND xact_start < now() - interval '15 seconds'
                                  AND (
                                    query ILIKE '%source_chunks%'
                                    OR query ILIKE '%source_files%'
                                    OR query ILIKE '%source_index%'
                                  )
                                )
                                OR (
                                  wait_event_type = 'Lock'
                                  AND state = 'active'
                                  AND (
                                    query ILIKE '%source_files%'
                                    OR query ILIKE '%source_chunks%'
                                    OR query ILIKE '%ALTER TABLE%'
                                  )
                                )
                                OR (
                                  state = 'idle in transaction'
                                  AND xact_start < now() - interval '120 seconds'
                                )
                              )
                            """
                        )
                        pids = [int(row[0]) for row in cur.fetchall()]
                        for pid in pids:
                            cur.execute("SELECT pg_terminate_backend(%s)", (pid,))
                            terminated.append(pid)
            except Exception:
                logger.warning(
                    "failed to terminate orphan sync DB backends for one DSN",
                    exc_info=True,
                )
    except Exception:
        logger.warning("failed to terminate orphan sync DB backends", exc_info=True)
    return terminated


def request_sync_takeover(*, wait_s: float = 20.0) -> dict[str, Any]:
    """取消旧 sync、杀 sync_cli、终止孤儿 PG 锁，供 ``make sync`` 接管/resume。

    参数:
        wait_s: 等待旧 building 状态退出的最长时间（秒）。
    返回:
        cancel_gen、killed_pids、db_terminated 等诊断信息。
    """
    import os
    import signal
    import time

    prior = None
    try:
        from app.retrieval.sync_progress import read_sync_progress

        prior = read_sync_progress()
    except Exception:
        prior = None

    building = (
        isinstance(prior, dict)
        and str(prior.get("status") or "") == "building"
        and str(prior.get("phase") or "")
        not in ("", "finished", "error", "starting")
    )
    gen = bump_sync_cancel()
    my_pid = os.getpid()
    killed: list[int] = []

    def _kill_sync_cli(sig: int) -> None:
        try:
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit():
                    continue
                pid = int(entry.name)
                if pid == my_pid:
                    continue
                try:
                    raw = (entry / "cmdline").read_bytes()
                except OSError:
                    continue
                cmd = raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore")
                if "app.retrieval.sync_cli" in cmd or "retrieval.sync_cli" in cmd:
                    try:
                        os.kill(pid, sig)
                        if pid not in killed:
                            killed.append(pid)
                    except OSError:
                        pass
        except OSError:
            pass

    _kill_sync_cli(signal.SIGTERM)
    time.sleep(1.0)
    _kill_sync_cli(signal.SIGKILL)

    # Critical: drop idle-in-transaction locks left by killed clients.
    db_terminated = _terminate_orphan_sync_db_backends()
    time.sleep(0.3)
    # Second pass in case terminate raced with a reconnecting waiter.
    db_terminated2 = _terminate_orphan_sync_db_backends()
    for pid in db_terminated2:
        if pid not in db_terminated:
            db_terminated.append(pid)

    deadline = time.monotonic() + min(8.0, max(0.0, float(wait_s)))
    while time.monotonic() < deadline:
        try:
            from app.retrieval.sync_progress import read_sync_progress

            cur = read_sync_progress()
        except Exception:
            cur = None
        if not isinstance(cur, dict):
            break
        status = str(cur.get("status") or "")
        phase = str(cur.get("phase") or "")
        if status != "building" or phase in ("finished", "error", ""):
            break
        if "cancel" in str(cur.get("error") or "").lower():
            break
        time.sleep(0.3)

    return {
        "cancel_gen": gen,
        "killed_pids": killed,
        "db_terminated": db_terminated,
        "had_building": building,
        "prior_phase": (prior or {}).get("phase") if isinstance(prior, dict) else None,
    }


def _is_ops_l1_root(root: Path) -> bool:
    """True for Official L1 trees under ``ops-l1`` (ephemeral runs + beir-index).

    Full-tenant sync (startup / sources_watch / write-triggered ``reason=api``)
    must skip these. L1 retrieval indexes ``beir-index`` only via work-scoped
    ``api-work``; letting global sync touch FiQA mid-materialize double-embeds
    and steals the process-wide sync lock.
    """
    from app.retrieval.ops_plane import is_ops_l1_work_root

    return is_ops_l1_work_root(root)


def _is_ephemeral_ops_l1_root(root: Path) -> bool:
    """True for per-run L1 trees (excludes shared ``beir-index`` cache).

    Prefer :func:`_is_ops_l1_root` for full-tenant skip decisions.
    """
    parts = root.resolve().parts
    if "ops-l1" not in parts:
        return False
    i = parts.index("ops-l1")
    rest = parts[i + 1 :]
    if not rest:
        return False
    return rest[0] != "beir-index"


def _sync_one(
    sources_dir: Path,
    *,
    workspace_root: Path,
    work_id: str | None = None,
    visibility: str = "private",
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    from app.retrieval.store import get_sources_store

    check_sync_cancelled()
    if not sources_dir.exists():
        return {
            "indexed_files": 0,
            "chunks": 0,
            "added": 0,
            "updated": 0,
            "skipped": 0,
            "removed": 0,
            "work_id": work_id,
            "visibility": visibility,
        }
    logger.info(
        "sources index sync scope; visibility=%s dir=%s work_id=%s",
        visibility,
        sources_dir,
        work_id or "-",
    )
    try:
        from app.retrieval.sync_progress import report_sync_progress

        report_sync_progress(
            force=True,
            status="building",
            phase="prepare",
            visibility=visibility,
            path=str(sources_dir),
            work_id=work_id,
            files_done=None,
            dirty_files=None,
            skipped=None,
            chunks_embedded=None,
            rate_chunks_per_s=None,
            eta_s=None,
        )
    except Exception:
        logger.debug("sync progress scope report skipped", exc_info=True)
    store = get_sources_store(work_root=workspace_root)
    return store.sync(
        sources_dir,
        workspace_root=workspace_root,
        work_id=work_id,
        visibility=visibility,
        owner_user_id=owner_user_id,
    )


def _purge_orphan_private() -> dict[str, int]:
    from app.retrieval.store import get_sources_store

    store = get_sources_store()
    purge = getattr(store, "delete_orphan_private_rows", None)
    if callable(purge):
        result = purge()
        if isinstance(result, dict):
            return {str(k): int(v) for k, v in result.items()}
    return {}


def sync_sources_index_blocking() -> dict[str, Any]:
    """阻塞式全租户增量 sync（可 ``asyncio.to_thread`` 包装）。"""
    workspace_root = Path(settings.workspace_root).resolve()
    results: list[dict[str, Any]] = []

    seed_dir = workspace_root / "sources" / "seed"
    if seed_dir.is_dir():
        results.append(
            _sync_one(
                seed_dir,
                workspace_root=workspace_root,
                work_id=None,
                visibility="seed",
            )
        )

    work_roots_synced: set[Path] = set()
    try:
        import psycopg

        dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        dsn = dsn.replace("postgres://", "postgresql://")
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, work_root, owner_user_id FROM works
                    """
                )
                works = cur.fetchall()
        for work_id, work_root, owner_id in works:
            root = Path(str(work_root)).resolve()
            if _is_ops_l1_root(root):
                logger.info(
                    "sources index sync skip ops-l1 work; work_id=%s dir=%s",
                    work_id,
                    root,
                )
                continue
            src = root / "sources"
            if not src.is_dir():
                continue
            work_roots_synced.add(root)
            check_sync_cancelled()
            results.append(
                _sync_one(
                    src,
                    workspace_root=root,
                    work_id=str(work_id),
                    visibility="private",
                    owner_user_id=str(owner_id) if owner_id else None,
                )
            )
    except SourcesSyncCancelled:
        raise
    except Exception as exc:
        logger.warning("works-scoped index sync skipped: %s", exc)

    if workspace_root.resolve() not in work_roots_synced:
        sources_root = workspace_root / "sources"
        if sources_root.is_dir():
            try:
                results.append(
                    _sync_one(
                        sources_root,
                        workspace_root=workspace_root,
                        work_id=None,
                        visibility="private",
                    )
                )
            except ValueError as exc:
                logger.warning("workspace_root sources sync skipped: %s", exc)

    orphan = _purge_orphan_private()

    if not results and not orphan:
        return {
            "indexed_files": 0,
            "chunks": 0,
            "added": 0,
            "updated": 0,
            "skipped": 0,
            "removed": 0,
        }

    merged = {
        "indexed_files": sum(int(r.get("indexed_files") or 0) for r in results),
        "chunks": sum(int(r.get("chunks") or 0) for r in results),
        "added": sum(int(r.get("added") or 0) for r in results),
        "updated": sum(int(r.get("updated") or 0) for r in results),
        "skipped": sum(int(r.get("skipped") or 0) for r in results),
        "removed": sum(int(r.get("removed") or 0) for r in results),
        "scopes": len(results),
        **orphan,
    }
    return merged


def sync_sources_index_work_blocking(
    *,
    work_id: str,
    work_root: str,
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    """仅同步单个 Work 的 ``sources/``（L1/Ops，避免全租户扫盘）。"""
    root = Path(str(work_root)).resolve()
    src = root / "sources"
    result = _sync_one(
        src,
        workspace_root=root,
        work_id=str(work_id),
        visibility="private",
        owner_user_id=str(owner_user_id) if owner_user_id else None,
    )
    merged = dict(result) if isinstance(result, dict) else {"result": result}
    merged.setdefault("scopes", 1)
    return merged


def _list_ops_index_works(*, index_token: str) -> list[tuple[str, str, str | None]]:
    """Return ``(work_id, work_root, owner)`` for shared Ops index works.

    ``index_token`` is ``beir-index`` or ``cmteb-index``.
    """
    import psycopg

    token = str(index_token or "").strip()
    if token not in {"beir-index", "cmteb-index"}:
        raise ValueError(f"unsupported ops index token: {index_token}")
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    dsn = dsn.replace("postgres://", "postgresql://")
    like_child = f"%/ops-l1/{token}/%"
    like_root = f"%/ops-l1/{token}"
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id::text, work_root, owner_user_id::text
                FROM works
                WHERE work_root LIKE %s OR work_root LIKE %s
                ORDER BY work_root
                """,
                (like_child, like_root),
            )
            rows = cur.fetchall()
    out: list[tuple[str, str, str | None]] = []
    for work_id, work_root, owner_id in rows:
        root = Path(str(work_root)).resolve()
        if not _is_ops_l1_root(root):
            continue
        parts = root.parts
        if token not in parts:
            continue
        out.append((str(work_id), str(root), str(owner_id) if owner_id else None))
    return out


def _list_ops_beir_works() -> list[tuple[str, str, str | None]]:
    """Return ``(work_id, work_root, owner_user_id)`` for shared BEIR index works."""
    return _list_ops_index_works(index_token="beir-index")


def _list_ops_cmteb_works() -> list[tuple[str, str, str | None]]:
    """Return works for shared C-MTEB index trees (``ops-l1/cmteb-index``)."""
    return _list_ops_index_works(index_token="cmteb-index")


def _sync_ops_index_works_blocking(
    works: list[tuple[str, str, str | None]],
    *,
    label: str,
) -> dict[str, Any]:
    if not works:
        logger.info("ops %s index sync: no works registered", label)
        return {
            "indexed_files": 0,
            "chunks": 0,
            "added": 0,
            "updated": 0,
            "skipped": 0,
            "removed": 0,
            "scopes": 0,
            "works": [],
        }

    results: list[dict[str, Any]] = []
    total = len(works)
    for i, (work_id, work_root, owner_id) in enumerate(works, start=1):
        check_sync_cancelled()
        logger.info(
            "ops %s index sync start; work=%s/%s work_id=%s dir=%s",
            label,
            i,
            total,
            work_id,
            work_root,
        )
        try:
            from app.retrieval.sync_progress import report_sync_progress

            report_sync_progress(
                force=True,
                status="building",
                phase="scope",
                scopes_done=i,
                scopes_total=total,
                work_id=work_id,
                path=work_root,
                chunks_embedded=0,
                chunks_total=None,
                rate_chunks_per_s=None,
                eta_s=None,
            )
        except Exception:
            logger.debug("ops %s scope progress skipped", label, exc_info=True)
        results.append(
            sync_sources_index_work_blocking(
                work_id=work_id,
                work_root=work_root,
                owner_user_id=owner_id,
            )
        )

    return {
        "indexed_files": sum(int(r.get("indexed_files") or 0) for r in results),
        "chunks": sum(int(r.get("chunks") or 0) for r in results),
        "added": sum(int(r.get("added") or 0) for r in results),
        "updated": sum(int(r.get("updated") or 0) for r in results),
        "skipped": sum(int(r.get("skipped") or 0) for r in results),
        "removed": sum(int(r.get("removed") or 0) for r in results),
        "scopes": len(results),
        "reindexed_scopes": sum(1 for r in results if r.get("reindexed")),
        "works": [
            {
                "work_id": wid,
                "work_root": root,
                "reindexed": bool(res.get("reindexed")),
                "indexed_files": res.get("indexed_files"),
                "chunks": res.get("chunks"),
                "elapsed_s": res.get("elapsed_s"),
            }
            for (wid, root, _), res in zip(works, results, strict=True)
        ],
    }


def sync_ops_beir_indexes_blocking() -> dict[str, Any]:
    """强制 work-scoped 同步 Ops BEIR 语料（FiQA/SciFact 等）。"""
    return _sync_ops_index_works_blocking(_list_ops_beir_works(), label="beir")


def sync_ops_cmteb_indexes_blocking() -> dict[str, Any]:
    """强制 work-scoped 同步 Ops C-MTEB 语料（``cmteb-index``）。"""
    return _sync_ops_index_works_blocking(_list_ops_cmteb_works(), label="cmteb")


async def run_ops_beir_index_sync(*, reason: str = "ops-beir") -> dict[str, Any]:
    """在全局 sync 锁下串行 Ops BEIR 重嵌。"""
    token = sync_cancel_token()
    async with _sync_lock:
        return await _finish_sync_locked(
            reason=reason,
            runner=sync_ops_beir_indexes_blocking,
            work_id=None,
            path="ops-l1/beir-index",
            cancel_token=token,
        )


async def run_ops_cmteb_index_sync(*, reason: str = "ops-cmteb") -> dict[str, Any]:
    """在全局 sync 锁下串行 Ops C-MTEB 重嵌（独立 schema ``retrieval_ops_zh``）。"""
    token = sync_cancel_token()
    async with _sync_lock:
        return await _finish_sync_locked(
            reason=reason,
            runner=sync_ops_cmteb_indexes_blocking,
            work_id=None,
            path="ops-l1/cmteb-index",
            cancel_token=token,
        )


async def _finish_sync_locked(
    *,
    reason: str,
    runner: Callable[[], dict[str, Any]],
    work_id: str | None = None,
    path: str | None = None,
    cancel_token: int,
) -> dict[str, Any]:
    """Shared single-flight wrapper used by full + work-scoped sync."""
    from app.retrieval.sync_progress import (
        mark_sync_error,
        mark_sync_finished,
        mark_sync_started,
    )

    logger.info(
        "sources index sync starting; reason=%s work_id=%s cancel_token=%s",
        reason,
        work_id or "-",
        cancel_token,
    )
    if cancel_token != sync_cancel_token():
        mark_sync_error(
            "cancelled while waiting for sync lock",
            reason=reason,
            path=path,
            work_id=work_id,
        )
        return {
            "status": "cancelled",
            "reason": reason,
            "error": "cancelled while waiting for sync lock",
        }

    mark_sync_started(reason=reason, path=path, work_id=work_id)
    try:

        def _runner_bound() -> dict[str, Any]:
            bind_sync_cancel_token(cancel_token)
            try:
                if cancel_token != sync_cancel_token():
                    raise SourcesSyncCancelled("sources index sync cancelled")
                return runner()
            finally:
                clear_sync_cancel_token()

        result = await asyncio.to_thread(_runner_bound)
    except SourcesSyncCancelled as exc:
        logger.info("sources index sync cancelled; reason=%s", reason)
        mark_sync_error(str(exc), reason=reason, path=path, work_id=work_id)
        return {"status": "cancelled", "reason": reason, "error": str(exc)}
    except Exception as exc:
        logger.exception("sources index sync failed; reason=%s", reason)
        mark_sync_error(str(exc), reason=reason, path=path, work_id=work_id)
        return {"status": "error", "reason": reason, "error": str(exc)}

    payload = dict(result) if isinstance(result, dict) else {"result": result}
    payload.setdefault("status", "ok")
    payload["reason"] = reason
    if work_id:
        payload["work_id"] = work_id
    if path:
        payload.setdefault("path", path)
    if str(payload.get("status") or "") == "error":
        mark_sync_error(
            str(payload.get("error") or "sources index sync failed"),
            reason=reason,
            path=path,
            work_id=work_id,
        )
    else:
        mark_sync_finished(payload, reason=reason)
    logger.info(
        "sources index sync finished; reason=%s work_id=%s indexed_files=%s chunks=%s "
        "added=%s updated=%s skipped=%s elapsed_s=%s embed_batch_size=%s",
        reason,
        work_id or "-",
        payload.get("indexed_files"),
        payload.get("chunks"),
        payload.get("added"),
        payload.get("updated"),
        payload.get("skipped"),
        payload.get("elapsed_s"),
        payload.get("embed_batch_size"),
    )
    return payload


async def run_sources_index_sync(*, reason: str = "manual") -> dict[str, Any]:
    """进程级单航班全租户 sync（锁上等待者会重新扫描）。"""
    token = sync_cancel_token()
    async with _sync_lock:
        return await _finish_sync_locked(
            reason=reason,
            runner=sync_sources_index_blocking,
            work_id=None,
            path=None,
            cancel_token=token,
        )


async def run_sources_index_sync_work(
    *,
    work_id: str,
    work_root: str,
    owner_user_id: str | None = None,
    reason: str = "work",
) -> dict[str, Any]:
    """单 Work scope sync，与全租户 sync 共用锁。"""
    token = sync_cancel_token()

    def _runner() -> dict[str, Any]:
        return sync_sources_index_work_blocking(
            work_id=work_id,
            work_root=work_root,
            owner_user_id=owner_user_id,
        )

    async with _sync_lock:
        return await _finish_sync_locked(
            reason=reason,
            runner=_runner,
            work_id=str(work_id),
            path=str(work_root),
            cancel_token=token,
        )


async def cancel_sources_index_sync() -> dict[str, Any]:
    """中止在途 sync 及锁队列上的等待者。"""
    gen = bump_sync_cancel()
    from app.retrieval.sync_progress import mark_sync_error

    mark_sync_error("sources index sync cancelled", reason="cancel")
    return {"accepted": True, "status": "cancelling", "cancel_gen": gen}


async def _delayed_startup_sync() -> None:
    delay = max(0.0, float(settings.sources_startup_sync_delay_seconds))
    if delay:
        await asyncio.sleep(delay)
    await run_sources_index_sync(reason="startup")


def schedule_startup_sources_sync() -> asyncio.Task[None] | None:
    """启动后延迟 fire-and-forget sync，不阻塞 lifespan。"""
    global _startup_task
    if not settings.sources_startup_sync_enabled:
        logger.info("sources startup sync disabled")
        return None
    if _startup_task is not None and not _startup_task.done():
        return _startup_task
    _startup_task = asyncio.create_task(_delayed_startup_sync())
    return _startup_task


async def cancel_startup_sources_sync() -> None:
    global _startup_task
    task = _startup_task
    _startup_task = None
    if task is None:
        return
    bump_sync_cancel()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
