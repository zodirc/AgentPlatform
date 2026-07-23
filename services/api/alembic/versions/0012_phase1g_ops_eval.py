"""phase1g ops_eval_runs (docs/29 history)"""

from app.db.migration_sql import run_ddl

revision = "0012_phase1g_ops_eval"
down_revision = "0011_phase1f_works"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1g_ops_eval_runs.sql")


def downgrade() -> None:
    pass
