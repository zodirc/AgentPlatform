"""phase0 core schema"""

from app.db.migration_sql import run_ddl

revision = "0001_phase0"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase0.sql")


def downgrade() -> None:
    pass
