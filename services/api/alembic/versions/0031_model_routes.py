"""User-scoped scenario/role model routing."""

from app.db.migration_sql import run_ddl

revision = "0031_model_routes"
down_revision = "0030_work_memories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_model_routes.sql")


def downgrade() -> None:
    pass
