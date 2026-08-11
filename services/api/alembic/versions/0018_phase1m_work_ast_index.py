"""phase1m work_ast_index for Agent workspace AST (docs/plan/agent-workspace-ast-index.md)"""

from app.db.migration_sql import run_ddl

revision = "0018_phase1m_work_ast_index"
down_revision = "0017_phase1l_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1m_work_ast_index.sql")


def downgrade() -> None:
    pass
