"""phase2 runners registry + runs.lease_expires_at (O3 / WP1)"""

from app.db.migration_sql import run_ddl

revision = "0020_phase2_runners_lease"
down_revision = "0019_phase1n_work_ast_index_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_runners_lease.sql")


def downgrade() -> None:
    pass
