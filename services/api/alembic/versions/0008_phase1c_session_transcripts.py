"""phase1c session transcripts"""

from app.db.migration_sql import run_ddl

revision = "0008_phase1c_session_transcripts"
down_revision = "0007_phase1b_context_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1c_session_transcripts.sql")


def downgrade() -> None:
    pass
