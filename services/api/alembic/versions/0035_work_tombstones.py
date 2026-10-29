"""work_tombstones for Work deletion."""

from app.db.migration_sql import run_ddl

revision = "0035_work_tombstones"
down_revision = "0034_turn_intent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_work_tombstones.sql")


def downgrade() -> None:
    pass
