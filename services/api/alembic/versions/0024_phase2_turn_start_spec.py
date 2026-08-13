"""phase2 turn StartSpec (ops_eval/model_mode) + model secret escrow"""

from app.db.migration_sql import run_ddl

revision = "0024_phase2_turn_start_spec"
down_revision = "0023_phase2_pull_start_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_turn_start_spec.sql")


def downgrade() -> None:
    pass
