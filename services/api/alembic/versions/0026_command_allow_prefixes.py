"""Per-user command approval allow-list prefixes."""

from app.db.migration_sql import run_ddl

revision = "0026_command_allow_prefixes"
down_revision = "0025_phase2_drop_dup_turn_events_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_command_allow_prefixes.sql")


def downgrade() -> None:
    pass
