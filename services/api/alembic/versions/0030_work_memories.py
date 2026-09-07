"""Work-scoped memory rows (scope / lifetime / trust)."""

from app.db.migration_sql import run_ddl

revision = "0030_work_memories"
down_revision = "0029_turn_events_run_id_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_work_memories.sql")


def downgrade() -> None:
    pass
