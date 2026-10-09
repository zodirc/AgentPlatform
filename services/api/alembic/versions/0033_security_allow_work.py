"""Per-work command allow rules and user context clear."""

from app.db.migration_sql import run_ddl

revision = "0033_security_allow_work"
down_revision = "0032_security_quarantine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase_security_allow_work.sql")


def downgrade() -> None:
    pass
