"""phase1h works.visibility_seed (docs/27 TenantContext)"""

from app.db.migration_sql import run_ddl

revision = "0013_phase1h_visibility_seed"
down_revision = "0012_phase1g_ops_eval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1h_work_visibility_seed.sql")


def downgrade() -> None:
    pass
