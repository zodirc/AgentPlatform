"""phase1e model provider owner_user_id"""

from app.db.migration_sql import run_ddl

revision = "0010_phase1e_provider_owner"
down_revision = "0009_phase1d_end_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1e_provider_owner.sql")


def downgrade() -> None:
    pass
