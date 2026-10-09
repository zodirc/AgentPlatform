"""Quarantine store for isolated tool bodies."""

from app.db.migration_sql import run_ddl

revision = "0032_security_quarantine"
down_revision = "0031_model_routes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase_security_quarantine.sql")


def downgrade() -> None:
    pass
