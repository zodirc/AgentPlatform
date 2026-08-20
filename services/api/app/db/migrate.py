from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.db.pool import close_pool, init_pool
from app.settings import settings

logger = logging.getLogger(__name__)

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _alembic_cfg() -> Config:
    return Config(str(_ALEMBIC_INI))


def _database_engine_url() -> str:
    url = settings.database_url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _maybe_stamp_legacy_db(cfg: Config) -> None:
    """Start known legacy Phase 0 volumes at their actual migration baseline."""
    engine = create_engine(_database_engine_url())
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    if "sessions" in tables and "alembic_version" not in tables:
        # These volumes predate Alembic but already contain Phase 0's core
        # tables. Stamping head would silently skip every later migration.
        command.stamp(cfg, "0001_phase0")


def widen_alembic_version_column(connection) -> None:
    """Alembic's default version_num is varchar(32); some revision ids are longer."""
    if getattr(getattr(connection, "dialect", None), "name", "") != "postgresql":
        return
    connection.execute(
        text(
            "ALTER TABLE IF EXISTS alembic_version "
            "ALTER COLUMN version_num TYPE varchar(64)"
        )
    )
    if connection.in_transaction():
        connection.commit()


# Unpushed long id → ≤32 char id. Must run after widen (old value is 34 chars).
_REWRITE_0028_SQL = """
DO $rewrite$
BEGIN
  IF to_regclass('public.alembic_version') IS NOT NULL THEN
    UPDATE alembic_version
       SET version_num = '0028_phase2_exemplar_space'
     WHERE version_num = '0028_phase2_writing_exemplar_space';
  END IF;
END
$rewrite$;
"""


def rewrite_unpushed_revision_ids(connection) -> None:
    """Map a local-only overlong stamp onto the published revision id."""
    if getattr(getattr(connection, "dialect", None), "name", "") != "postgresql":
        return
    connection.execute(text(_REWRITE_0028_SQL))
    if connection.in_transaction():
        connection.commit()


def run_alembic_upgrade() -> None:
    cfg = _alembic_cfg()
    try:
        _maybe_stamp_legacy_db(cfg)
        command.upgrade(cfg, "head")
    except Exception:
        logger.exception("alembic upgrade to head failed")
        sys.stderr.flush()
        sys.stdout.flush()
        raise


async def apply_migrations() -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, run_alembic_upgrade)


async def _run() -> None:
    await init_pool()
    await apply_migrations()
    await close_pool()


def main() -> None:
    asyncio.run(_run())
    print("Alembic migrations applied.")


if __name__ == "__main__":
    main()
