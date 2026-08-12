"""Cold-start / incremental parse job (§3.1). Off-loop; never awaited from StartTurn."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from uuid import UUID

from app.retrieval.chunking import language_for_code_path
from app.settings import settings
from app.structural.workspace_index.hashutil import hash_bytes
from app.structural.workspace_index.ignore import dir_skipped, file_skipped
from app.structural.workspace_index.parse import extract_definitions_for_path
from app.structural.workspace_index.projection import IndexProjection, get_projection_registry
from app.structural.workspace_index.store import AstIndexStore
from app.structural.workspace_index.types import FileEntry, IndexMeta, IndexStatus, SymbolRec

logger = logging.getLogger(__name__)

_BATCH_SIZE = 200

# Dedicated pool so AST cold-start cannot exhaust the default asyncio executor
# (turns / grep / materialize share that pool — starvation → start_turn ReadTimeout).
_AST_EXECUTOR: ThreadPoolExecutor | None = None


def _ast_executor() -> ThreadPoolExecutor:
    global _AST_EXECUTOR
    if _AST_EXECUTOR is None:
        workers = max(1, min(4, int(settings.workspace_ast_parse_concurrency)))
        _AST_EXECUTOR = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="ast-index"
        )
    return _AST_EXECUTOR


async def _to_ast_thread(fn, /, *args, **kwargs):
    loop = asyncio.get_running_loop()
    call = partial(fn, *args, **kwargs) if kwargs else partial(fn, *args)
    return await loop.run_in_executor(_ast_executor(), call)


def walk_work_files(
    work_root: Path,
    *,
    max_files: int,
    max_file_bytes: int,
    code_only: bool = True,
    deadline: float | None = None,
) -> list[Path]:
    """Collect candidate files under work_root using lexical-family ignores.

    ``code_only=True`` (default): only extensions with a tree-sitter/regex
    language mapping — skips .rst/.fits/.c/data noise that cannot feed Locate.
    """
    root = work_root.resolve()
    out: list[Path] = []
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if deadline is not None and time.monotonic() >= deadline:
            break
        dirnames[:] = [d for d in dirnames if not dir_skipped(d)]
        for name in filenames:
            path = Path(dirpath) / name
            if file_skipped(path):
                continue
            if code_only and language_for_code_path(path) is None:
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            if st.st_size > max_file_bytes:
                # Still track as skipped entry later; include path for hash/meta.
                out.append(path)
            else:
                out.append(path)
            if len(out) >= max_files:
                return out
    return out


def parse_file_entry(
    abs_path: Path,
    *,
    work_root: Path,
    generation: int,
    max_file_bytes: int,
) -> FileEntry | None:
    """Read → hash → parse one file. Returns skipped entry on unsupported/oversize."""
    try:
        rel = os.path.relpath(str(abs_path), str(work_root))
        if rel.startswith(".."):
            return None
        rel = rel.replace("\\", "/")
    except ValueError:
        return None
    try:
        st = abs_path.stat()
    except OSError:
        return None
    mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
    size = int(st.st_size)
    if size > max_file_bytes:
        # Hash first max_file_bytes only for identity; mark skipped.
        try:
            with abs_path.open("rb") as fh:
                data = fh.read(max_file_bytes)
        except OSError:
            return None
        return FileEntry(
            path=rel,
            lang="skipped",
            content_hash=hash_bytes(data),
            mtime_ns=mtime_ns,
            size=size,
            symbols=[],
            generation=generation,
        )
    try:
        data = abs_path.read_bytes()
    except OSError:
        return None
    content_hash = hash_bytes(data)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return FileEntry(
            path=rel,
            lang="skipped",
            content_hash=content_hash,
            mtime_ns=mtime_ns,
            size=size,
            symbols=[],
            generation=generation,
        )
    lang, symbols = extract_definitions_for_path(abs_path, text)
    return FileEntry(
        path=rel,
        lang=lang,
        content_hash=content_hash,
        mtime_ns=mtime_ns,
        size=size,
        symbols=list(symbols),
        generation=generation,
    )


async def run_cold_start(
    *,
    work_id: UUID,
    owner_user_id: str,
    work_root: Path,
    store: AstIndexStore | None = None,
    memory_only: bool = False,
    budget_s: float | None = None,
) -> IndexMeta:
    """Full walk + parse + (optional) batch upsert + memory projection replace.

    ``memory_only=True`` (§7.2 eval-ephemeral): skip all ``work_ast_*`` writes;
    projection lives in-process until Work ends / eviction.
    """
    store = store or AstIndexStore()
    registry = get_projection_registry()
    max_files = max(1, int(settings.workspace_ast_max_files))
    if memory_only:
        eval_cap = int(getattr(settings, "workspace_ast_eval_max_files", 0) or 0)
        if eval_cap > 0:
            max_files = max(1, min(max_files, eval_cap))
    max_bytes = max(1024, int(settings.workspace_ast_max_file_bytes))
    concurrency = max(1, min(8, int(settings.workspace_ast_parse_concurrency)))
    if memory_only:
        eval_conc = int(
            getattr(settings, "workspace_ast_eval_parse_concurrency", 0) or 0
        )
        if eval_conc > 0:
            concurrency = max(1, min(concurrency, eval_conc))
    budget = budget_s
    if budget is None and memory_only:
        budget = float(settings.workspace_ast_eval_budget_seconds)
    deadline = (time.monotonic() + float(budget)) if budget and budget > 0 else None

    if memory_only:
        generation = 1
        meta = IndexMeta(
            work_id=work_id,
            owner_user_id=owner_user_id,
            status=IndexStatus.BUILDING,
            generation=generation,
            files_total=0,
            files_done=0,
            error=None,
            ephemeral=True,
        )
    else:
        meta = await store.ensure_meta(work_id, owner_user_id=owner_user_id)
        generation = int(meta.generation) + 1
        meta = IndexMeta(
            work_id=work_id,
            owner_user_id=owner_user_id,
            status=IndexStatus.BUILDING,
            generation=generation,
            files_total=0,
            files_done=0,
            error=None,
            ephemeral=False,
        )
        await store.upsert_meta(meta)

    # Budget covers walk + parse (astropy-scale trees must not burn the whole
    # window on non-code noise before any symbol is queryable).
    paths = await _to_ast_thread(
        walk_work_files,
        work_root,
        max_files=max_files,
        max_file_bytes=max_bytes,
        code_only=True,
        deadline=deadline,
    )
    meta = IndexMeta(
        work_id=work_id,
        owner_user_id=owner_user_id,
        status=IndexStatus.BUILDING,
        generation=generation,
        files_total=len(paths),
        files_done=0,
        error=None,
        ephemeral=memory_only,
    )
    if not memory_only:
        await store.upsert_meta(meta)
    proj = registry.get(work_id) or IndexProjection(
        work_id=work_id,
        owner_user_id=owner_user_id,
        meta=meta,
    )
    if registry.get(work_id) is None:
        registry.put(proj)
    else:
        proj.meta = meta

    sem = asyncio.Semaphore(concurrency)
    entries: list[FileEntry] = []
    batch: list[FileEntry] = []
    done = 0
    timed_out = False

    async def _one(path: Path) -> FileEntry | None:
        async with sem:
            return await _to_ast_thread(
                parse_file_entry,
                path,
                work_root=work_root,
                generation=generation,
                max_file_bytes=max_bytes,
            )

    try:
        for i in range(0, len(paths), concurrency):
            if deadline is not None and time.monotonic() >= deadline:
                timed_out = True
                logger.info(
                    "workspace_ast cold_start budget hit work_id=%s done=%s/%s",
                    work_id,
                    done,
                    len(paths),
                )
                break
            chunk = paths[i : i + concurrency]
            results = await asyncio.gather(*[_one(p) for p in chunk], return_exceptions=True)
            # Yield so StartTurn / health can progress while indexing.
            await asyncio.sleep(0)
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("workspace_ast parse failed: %s", result)
                    continue
                if result is None:
                    continue
                batch.append(result)
                entries.append(result)
                done += 1
                if len(batch) >= _BATCH_SIZE:
                    meta = IndexMeta(
                        work_id=work_id,
                        owner_user_id=owner_user_id,
                        status=IndexStatus.BUILDING,
                        generation=generation,
                        files_total=len(paths),
                        files_done=done,
                        ephemeral=memory_only,
                    )
                    if not memory_only:
                        await store.upsert_files_batch(
                            work_id, batch, owner_user_id=owner_user_id, meta=meta
                        )
                    for e in batch:
                        proj.upsert_file(e, meta=meta)
                    batch = []
        if batch:
            meta = IndexMeta(
                work_id=work_id,
                owner_user_id=owner_user_id,
                status=IndexStatus.BUILDING,
                generation=generation,
                files_total=len(paths),
                files_done=done,
                ephemeral=memory_only,
            )
            if not memory_only:
                await store.upsert_files_batch(
                    work_id, batch, owner_user_id=owner_user_id, meta=meta
                )
            for e in batch:
                proj.upsert_file(e, meta=meta)

        # Partial budget → stale (queryable); full → ready (§7.2).
        final_status = (
            IndexStatus.STALE if timed_out and done > 0 else IndexStatus.READY
        )
        if timed_out and done == 0:
            final_status = IndexStatus.ERROR
        meta = IndexMeta(
            work_id=work_id,
            owner_user_id=owner_user_id,
            status=final_status,
            generation=generation,
            files_total=len(paths),
            files_done=done,
            error=("budget_timeout" if timed_out and done == 0 else None),
            ephemeral=memory_only,
        )
        if not memory_only:
            await store.upsert_meta(meta)
        proj.replace_all(entries, meta=meta)
        registry.put(proj)
        return meta
    except Exception as exc:
        error = str(exc)[:500]
        logger.exception("workspace_ast cold_start failed work_id=%s", work_id)
        meta = IndexMeta(
            work_id=work_id,
            owner_user_id=owner_user_id,
            status=IndexStatus.ERROR,
            generation=generation,
            files_total=len(paths),
            files_done=done,
            error=error,
            ephemeral=memory_only,
        )
        if not memory_only:
            try:
                await store.upsert_meta(meta)
            except Exception:
                logger.exception("workspace_ast failed to persist error meta")
        proj.meta = meta
        return meta


def parse_single_file_fallback(
    abs_path: Path,
    *,
    work_root: Path,
    generation: int = 0,
) -> list[SymbolRec]:
    """Zed-style single-file instant parse for stale query correction (§4.1)."""
    max_bytes = max(1024, int(settings.workspace_ast_max_file_bytes))
    entry = parse_file_entry(
        abs_path,
        work_root=work_root,
        generation=generation,
        max_file_bytes=max_bytes,
    )
    if entry is None:
        return []
    return list(entry.symbols)
