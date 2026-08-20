"""Writing account prefs and fragment evaluation history."""

from app.db.migration_sql import run_ddl

revision = "0027_phase2_writing_signals"
down_revision = "0026_command_allow_prefixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_writing_signals.sql")


def downgrade() -> None:
    pass
