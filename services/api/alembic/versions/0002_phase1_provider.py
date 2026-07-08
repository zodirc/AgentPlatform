"""phase1 provider configs"""

from app.db.migration_sql import run_ddl

revision = "0002_phase1_provider"
down_revision = "0001_phase0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1_provider_configs.sql")


def downgrade() -> None:
    pass
