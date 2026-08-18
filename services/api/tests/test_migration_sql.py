from __future__ import annotations

from app.db.migration_sql import DDL_DIR


def test_ddl_directory_contains_phase0() -> None:
    assert (DDL_DIR / "phase0.sql").is_file()
    assert (DDL_DIR / "phase2_outbox.sql").is_file()
    drop_dup = (DDL_DIR / "phase2_drop_dup_turn_events_idx.sql").read_text()
    assert "DROP INDEX IF EXISTS idx_turn_events_turn_sequence" in drop_dup
    assert "CONCURRENTLY" not in drop_dup
    assert "varchar(64)" in drop_dup
