"""projection failure audit log"""

from app.db.migration_sql import run_ddl
from alembic import op

revision = "0006_projection_log"
down_revision = "0005_notify_trigger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_projection_log.sql")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS projection_log;")
