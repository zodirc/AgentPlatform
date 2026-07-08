from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.db.pool import close_pool, init_pool
from app.settings import settings

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _alembic_cfg() -> Config:
    return Config(str(_ALEMBIC_INI))


def _database_engine_url() -> str:
    url = settings.database_url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _maybe_stamp_legacy_db(cfg: Config) -> None:
    """Existing volumes created before Alembic need a one-time stamp to head."""
    engine = create_engine(_database_engine_url())
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    if "sessions" in tables and "alembic_version" not in tables:
        command.stamp(cfg, "head")


def run_alembic_upgrade() -> None:
    cfg = _alembic_cfg()
    _maybe_stamp_legacy_db(cfg)
    command.upgrade(cfg, "head")


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
