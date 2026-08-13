"""phase2 pull_eligible + turns.plan_phase + deactivate eval-openai (pull start context)"""

from app.db.migration_sql import run_ddl

revision = "0023_phase2_pull_start_context"
down_revision = "0022_phase2_events_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_pull_start_context.sql")


def downgrade() -> None:
    pass
