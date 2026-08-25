"""Index turn_events.run_id so session hard-delete FK checks stay index scans."""

from app.db.migration_sql import run_ddl

revision = "0029_phase2_turn_events_run_id_idx"
down_revision = "0028_phase2_exemplar_space"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_turn_events_run_id_idx.sql")


def downgrade() -> None:
    pass
