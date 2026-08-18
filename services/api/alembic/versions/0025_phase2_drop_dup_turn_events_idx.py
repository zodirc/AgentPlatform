"""Drop duplicate turn_events (turn_id, sequence) btree.

UNIQUE (turn_id, sequence) already indexes the same keys. The extra
idx_turn_events_turn_sequence doubled index disk (~882MB on a 12M-row table).
"""

from alembic import op

from app.db.migration_sql import DDL_DIR

revision = "0025_phase2_drop_dup_turn_events_idx"
down_revision = "0024_phase2_turn_start_spec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = (DDL_DIR / "phase2_drop_dup_turn_events_idx.sql").read_text()
    with op.get_context().autocommit_block():
        op.execute(sql)


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_turn_events_turn_sequence "
        "ON turn_events (turn_id, sequence)"
    )
