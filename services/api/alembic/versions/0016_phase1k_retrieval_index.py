"""phase1k partial index for retrieval.completed events (docs/35 A13)"""

from app.db.migration_sql import run_ddl

revision = "0016_phase1k_retrieval_index"
down_revision = "0015_phase1j_model_envelopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase1k_retrieval_event_index.sql")


def downgrade() -> None:
    pass
