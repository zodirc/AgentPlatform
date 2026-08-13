"""Ephemeral projection snapshot for cross-process eval (A6 §7.2 memory-only).

Indexer writes; runtime loads. Not used for product DB-backed works.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from app.structural.workspace_index.types import FileEntry, IndexMeta, IndexStatus

logger = logging.getLogger(__name__)

_SNAPSHOT_REL = Path(".agent") / "ast_index_snapshot.json"


def snapshot_path(work_root: Path | str) -> Path:
    return Path(work_root).resolve() / _SNAPSHOT_REL


def write_snapshot(
    work_root: Path | str,
    *,
    meta: IndexMeta,
    entries: list[FileEntry],
) -> Path:
    """Atomic write of meta + file entries under work_root/.agent/."""
    root = Path(work_root).resolve()
    path = snapshot_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    body: dict[str, Any] = {
        "version": 1,
        "meta": {
            "work_id": str(meta.work_id),
            "owner_user_id": meta.owner_user_id,
            "status": meta.status.value,
            "generation": int(meta.generation),
            "files_total": int(meta.files_total),
            "files_done": int(meta.files_done),
            "error": meta.error,
            "ephemeral": True,
        },
        "files": [e.to_row() for e in entries],
    }
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".ast_snap_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def read_snapshot(
    work_root: Path | str,
) -> tuple[IndexMeta, list[FileEntry]] | None:
    path = snapshot_path(work_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("ast snapshot read failed path=%s err=%s", path, exc)
        return None
    if not isinstance(data, dict):
        return None
    raw_meta = data.get("meta") or {}
    try:
        wid = UUID(str(raw_meta.get("work_id")))
    except (TypeError, ValueError):
        return None
    status_raw = str(raw_meta.get("status") or IndexStatus.COLD.value)
    try:
        status = IndexStatus(status_raw)
    except ValueError:
        status = IndexStatus.ERROR
    meta = IndexMeta(
        work_id=wid,
        owner_user_id=str(raw_meta.get("owner_user_id") or ""),
        status=status,
        generation=int(raw_meta.get("generation") or 0),
        files_total=int(raw_meta.get("files_total") or 0),
        files_done=int(raw_meta.get("files_done") or 0),
        error=raw_meta.get("error"),
        ephemeral=True,
    )
    files_raw = data.get("files") or []
    entries: list[FileEntry] = []
    if isinstance(files_raw, list):
        for row in files_raw:
            if isinstance(row, dict):
                try:
                    entries.append(FileEntry.from_row(row))
                except Exception:
                    continue
    return meta, entries


def drop_snapshot(work_root: Path | str) -> None:
    path = snapshot_path(work_root)
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        logger.warning("ast snapshot unlink failed path=%s", path, exc_info=True)
