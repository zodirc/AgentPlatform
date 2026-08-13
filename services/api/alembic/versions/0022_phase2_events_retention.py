"""phase2 turn_events retention metadata (O7 / WP3)

Full PARTITION BY RANGE rewrite of a live ``turn_events`` table requires a
maintenance window (unique indexes must include the partition key ``ts``).
Growth is capped by the application retention job instead; partition conversion
is an ops-run follow-up when the table is rebuilt or greenfield.
"""

from app.db.migration_sql import run_ddl

revision = "0022_phase2_events_retention"
down_revision = "0021_phase2_run_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_events_retention.sql")


def downgrade() -> None:
    pass
