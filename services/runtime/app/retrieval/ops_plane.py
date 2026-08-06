"""Ops L1 vector plane routing (Schema A).

Control-plane metadata (works / sessions / turns) stays on product ``DATABASE_URL``.
Official L1 corpora under ``ops-l1/`` write and search ``source_*`` on
``OPS_DATABASE_URL`` (falls back to ``BENCH_DATABASE_URL``), isolating eval
vectors from the product pgvector database while sharing one runtime process.
"""

from __future__ import annotations

from pathlib import Path

from app.settings import settings


def is_ops_l1_work_root(root: Path | str | None) -> bool:
    """True when ``work_root`` lives under the Ops L1 tree (``ops-l1``)."""
    if root is None:
        return False
    try:
        parts = Path(root).expanduser().resolve().parts
    except OSError:
        parts = Path(str(root)).parts
    return "ops-l1" in parts


def resolved_ops_database_url() -> str:
    """Ops vector DSN: ``OPS_DATABASE_URL`` or ``BENCH_DATABASE_URL``."""
    for raw in (settings.ops_database_url, settings.bench_database_url):
        value = str(raw or "").strip()
        if value:
            return value
    return ""


def ops_retrieval_plane_enabled() -> bool:
    return bool(resolved_ops_database_url())


def retrieval_database_url_for(*, work_root: Path | str | None = None) -> str:
    """Pick product vs Ops DSN for vector/FTS tables."""
    if is_ops_l1_work_root(work_root) and ops_retrieval_plane_enabled():
        return resolved_ops_database_url()
    return settings.database_url


def retrieval_pg_schema_for(*, work_root: Path | str | None = None) -> str:
    if is_ops_l1_work_root(work_root) and ops_retrieval_plane_enabled():
        return str(settings.ops_retrieval_pg_schema or "retrieval_ops").strip() or "retrieval_ops"
    return settings.retrieval_pg_schema
