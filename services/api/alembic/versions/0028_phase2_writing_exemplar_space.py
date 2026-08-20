"""Writing exemplar metric space (signatures + prototypes)."""

from app.db.migration_sql import run_ddl

revision = "0028_phase2_writing_exemplar_space"
down_revision = "0027_phase2_writing_signals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_ddl("phase2_writing_exemplar_space.sql")


def downgrade() -> None:
    pass
