"""phase1l audit_log for sensitive operations (docs/35 B17)"""

from app.db.migration_sql import run_ddl

revision = "0017_phase1l_audit_log"
down_revision = "0016_phase1k_retrieval_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1l_audit_log.sql")


def downgrade() -> None:
    pass
