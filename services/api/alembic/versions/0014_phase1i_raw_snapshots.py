"""phase1i session_raw_snapshots (docs/33 HM2)"""

from app.db.migration_sql import run_ddl

revision = "0014_phase1i_raw_snapshots"
down_revision = "0013_phase1h_visibility_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1i_session_raw_snapshots.sql")


def downgrade() -> None:
    pass
