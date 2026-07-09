"""phase1b model context window"""

from app.db.migration_sql import run_ddl

revision = "0007_phase1b_context_window"
down_revision = "0006_projection_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1b_context_window.sql")


def downgrade() -> None:
    pass
