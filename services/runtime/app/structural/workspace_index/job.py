"""Cold-start / incremental parse job (§3.1). Off-loop; never awaited from StartTurn."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from uuid import UUID

from app.settings import settings
from app.structural.workspace_index.hashutil import hash_bytes
from app.structural.workspace_index.ignore import dir_skipped, file_skipped
from app.structural.workspace_index.parse import extract_definitions_for_path
from app.structural.workspace_index.projection import IndexProjection, get_projection_registry
from app.structural.workspace_index.store import AstIndexStore
from app.structural.workspace_index.types import FileEntry, IndexMeta, IndexStatus, SymbolRec

logger = logging.getLogger(__name__)

_BATCH_SIZE = 200


def walk_work_files(
    work_root: Path,
    *,
    max_files: int,
    max_file_bytes: int,
) -> list[Path]:
    """Collect candidate files under work_root using lexical-family ignores."""
    root = work_root.resolve()
    out: list[Path] = []
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not dir_skipped(d)]
        for name in filenames:
            path = Path(dirpath) / name
            if file_skipped(path):
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
        rel = abs_path.resolve().relative_to(work_root.resolve()).as_posix()
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
) -> IndexMeta:
    """Full walk + parse + batch upsert + memory projection replace."""
    store = store or AstIndexStore()
    registry = get_projection_registry()
    max_files = max(1, int(settings.workspace_ast_max_files))
    max_bytes = max(1024, int(settings.workspace_ast_max_file_bytes))
    concurrency = max(1, min(8, int(settings.workspace_ast_parse_concurrency)))

    meta = await store.ensure_meta(work_id, owner_user_id=owner_user_id)
    generation = int(meta.generation) + 1
    paths = await asyncio.to_thread(
        walk_work_files, work_root, max_files=max_files, max_file_bytes=max_bytes
    )
    meta = IndexMeta(
        work_id=work_id,
        owner_user_id=owner_user_id,
        status=IndexStatus.BUILDING,
        generation=generation,
        files_total=len(paths),
        files_done=0,
        error=None,
    )
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
    error: str | None = None

    async def _one(path: Path) -> FileEntry | None:
        async with sem:
            return await asyncio.to_thread(
                parse_file_entry,
                path,
                work_root=work_root,
                generation=generation,
                max_file_bytes=max_bytes,
            )

    try:
        for i in range(0, len(paths), concurrency):
            chunk = paths[i : i + concurrency]
            results = await asyncio.gather(*[_one(p) for p in chunk], return_exceptions=True)
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
                    )
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
            )
            await store.upsert_files_batch(
                work_id, batch, owner_user_id=owner_user_id, meta=meta
            )
            for e in batch:
                proj.upsert_file(e, meta=meta)

        meta = IndexMeta(
            work_id=work_id,
            owner_user_id=owner_user_id,
            status=IndexStatus.READY,
            generation=generation,
            files_total=len(paths),
            files_done=done,
            error=None,
        )
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
        )
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
