"""phase1n work_ast_index_jobs for A6 remote indexer queue"""

from app.db.migration_sql import run_ddl

revision = "0019_phase1n_work_ast_index_jobs"
down_revision = "0018_phase1m_work_ast_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1n_work_ast_index_jobs.sql")


def downgrade() -> None:
    pass
