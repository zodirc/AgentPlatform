from __future__ import annotations

from app.db.migration_sql import DDL_DIR


def test_ddl_directory_contains_phase0() -> None:
    assert (DDL_DIR / "phase0.sql").is_file()
    assert (DDL_DIR / "phase2_outbox.sql").is_file()
