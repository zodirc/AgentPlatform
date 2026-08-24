"""Ops L1 向量平面路由（RAG 评测库与产品库隔离）。

控制面 metadata 仍在 product ``DATABASE_URL``；``ops-l1/`` 下语料的 ``source_*``
写入 ``OPS_DATABASE_URL``（或 ``BENCH_DATABASE_URL``）。BEIR → ``retrieval_ops``；
C-MTEB → ``retrieval_ops_zh``。
"""

from __future__ import annotations

from pathlib import Path

from app.settings import settings


def is_ops_l1_work_root(root: Path | str | None) -> bool:
    """work_root 是否在 ``ops-l1`` 树下。"""
    if root is None:
        return False
    try:
        parts = Path(root).expanduser().resolve().parts
    except OSError:
        parts = Path(str(root)).parts
    return "ops-l1" in parts


def is_ops_cmteb_work_root(root: Path | str | None) -> bool:
    """是否为 ``ops-l1/cmteb-index`` 共享 C-MTEB 索引树。"""
    if root is None:
        return False
    try:
        parts = Path(root).expanduser().resolve().parts
    except OSError:
        parts = Path(str(root)).parts
    if "ops-l1" not in parts:
        return False
    return "cmteb-index" in parts


def resolved_ops_database_url() -> str:
    """Ops 向量 DSN：``OPS_DATABASE_URL`` 或 ``BENCH_DATABASE_URL``。"""
    for raw in (settings.ops_database_url, settings.bench_database_url):
        value = str(raw or "").strip()
        if value:
            return value
    return ""


def ops_retrieval_plane_enabled() -> bool:
    """是否配置了 Ops 向量库 DSN。"""
    return bool(resolved_ops_database_url())


def retrieval_database_url_for(*, work_root: Path | str | None = None) -> str:
    """为向量/FTS 表选择 product 或 Ops DSN。"""
    if is_ops_l1_work_root(work_root) and ops_retrieval_plane_enabled():
        return resolved_ops_database_url()
    return settings.database_url


def retrieval_pg_schema_for(*, work_root: Path | str | None = None) -> str:
    """Ops L1 下返回 ``retrieval_ops`` / ``retrieval_ops_zh``，否则 product schema。"""
    if is_ops_l1_work_root(work_root) and ops_retrieval_plane_enabled():
        if is_ops_cmteb_work_root(work_root):
            return (
                str(settings.ops_retrieval_pg_schema_zh or "retrieval_ops_zh").strip()
                or "retrieval_ops_zh"
            )
        return (
            str(settings.ops_retrieval_pg_schema or "retrieval_ops").strip()
            or "retrieval_ops"
        )
    return settings.retrieval_pg_schema
