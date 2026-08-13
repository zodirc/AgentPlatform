"""phase2 run_commands command channel (O2 / WP6)"""

from app.db.migration_sql import run_ddl

revision = "0021_phase2_run_commands"
down_revision = "0020_phase2_runners_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_run_commands.sql")


def downgrade() -> None:
    pass
