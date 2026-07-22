"""phase1f works + sessions.work_id (docs/27)"""

from app.db.migration_sql import run_ddl

revision = "0011_phase1f_works"
down_revision = "0010_phase1e_provider_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1f_works.sql")


def downgrade() -> None:
    pass
