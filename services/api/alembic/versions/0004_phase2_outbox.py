"""phase2 outbox"""

from app.db.migration_sql import run_ddl

revision = "0004_phase2_outbox"
down_revision = "0003_phase1_extensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_outbox.sql")


def downgrade() -> None:
    pass
