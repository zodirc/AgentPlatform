"""phase1 extensions"""

from app.db.migration_sql import run_ddl

revision = "0003_phase1_extensions"
down_revision = "0002_phase1_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1_extensions.sql")


def downgrade() -> None:
    pass
