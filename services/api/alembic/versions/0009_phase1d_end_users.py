"""phase1d end users and session ownership"""

from app.db.migration_sql import run_ddl

revision = "0009_phase1d_end_users"
down_revision = "0008_phase1c_session_transcripts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1d_end_users.sql")


def downgrade() -> None:
    pass
