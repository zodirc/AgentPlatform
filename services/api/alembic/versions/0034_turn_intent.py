"""turns.intent so pull claim restores writing intents."""

from app.db.migration_sql import run_ddl

revision = "0034_turn_intent"
down_revision = "0033_security_allow_work"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_turn_intent.sql")


def downgrade() -> None:
    pass
