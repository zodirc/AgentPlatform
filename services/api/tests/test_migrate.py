from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db import migrate as migrate_mod
from app.db.migration_sql import DDL_DIR, run_ddl


def test_ddl_directory_resolves() -> None:
    assert DDL_DIR.is_dir()
    assert (DDL_DIR / "phase0.sql").read_text()


def test_run_ddl_executes_sql(monkeypatch) -> None:
    executed: list[str] = []

    class FakeOp:
        @staticmethod
        def execute(sql: str) -> None:
            executed.append(sql)

    monkeypatch.setattr("app.db.migration_sql.op", FakeOp)
    run_ddl("phase0.sql")
    assert executed and "CREATE" in executed[0].upper()


def test_run_alembic_upgrade(monkeypatch) -> None:
    called: list[str] = []

    def fake_upgrade(cfg, rev):
        called.append(rev)

    monkeypatch.setattr(migrate_mod, "_maybe_stamp_legacy_db", lambda _cfg: None)
    monkeypatch.setattr(migrate_mod.command, "upgrade", fake_upgrade)
    migrate_mod.run_alembic_upgrade()
    assert called == ["head"]


def test_maybe_stamp_legacy_db_when_sessions_exist(monkeypatch) -> None:
    class FakeInspector:
        def get_table_names(self):
            return ["sessions", "turns"]

    class FakeEngine:
        def dispose(self) -> None:
            return None

    stamped: list[str] = []

    monkeypatch.setattr(migrate_mod, "create_engine", lambda _url: FakeEngine())
    monkeypatch.setattr(migrate_mod, "inspect", lambda _engine: FakeInspector())
    monkeypatch.setattr(migrate_mod.command, "stamp", lambda _cfg, rev: stamped.append(rev))

    migrate_mod._maybe_stamp_legacy_db(migrate_mod._alembic_cfg())
    assert stamped == ["head"]


@pytest.mark.asyncio
async def test_apply_migrations_delegates_to_executor(monkeypatch) -> None:
    monkeypatch.setattr(migrate_mod, "run_alembic_upgrade", lambda: None)
    await migrate_mod.apply_migrations()


@pytest.mark.asyncio
async def test_run_executes_pool_and_migrations(monkeypatch) -> None:
    monkeypatch.setattr(migrate_mod, "init_pool", AsyncMock())
    monkeypatch.setattr(migrate_mod, "apply_migrations", AsyncMock())
    monkeypatch.setattr(migrate_mod, "close_pool", AsyncMock())
    await migrate_mod._run()
    migrate_mod.init_pool.assert_awaited_once()
    migrate_mod.apply_migrations.assert_awaited_once()
    migrate_mod.close_pool.assert_awaited_once()


def test_main_invokes_asyncio_run(monkeypatch) -> None:
    seen: list[str] = []

    def capture_run(coro):
        seen.append("run")
        coro.close()

    monkeypatch.setattr(migrate_mod.asyncio, "run", capture_run)
    migrate_mod.main()
    assert seen == ["run"]
