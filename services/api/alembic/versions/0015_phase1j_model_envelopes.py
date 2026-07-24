"""phase1j model_request_envelopes (docs/33 HM4)"""

from app.db.migration_sql import run_ddl

revision = "0015_phase1j_model_envelopes"
down_revision = "0014_phase1i_raw_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1j_model_envelopes.sql")


def downgrade() -> None:
    pass
