"""gc_runs and one in-flight work_gc job per work."""

from app.db.migration_sql import run_ddl

revision = "0041_gc_runs"
down_revision = "0040_audit_log_partition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_gc_runs.sql")


def downgrade() -> None:
    pass
