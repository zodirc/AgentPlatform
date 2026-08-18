"""Drop duplicate turn_events (turn_id, sequence) btree.

UNIQUE (turn_id, sequence) already indexes the same keys. The extra
idx_turn_events_turn_sequence doubled index disk (~882MB on a 12M-row table).

Do not use DROP INDEX CONCURRENTLY: API Alembic runs inside a transaction
(env.py begin_transaction). Also widen alembic_version.version_num — this
revision id is longer than the default varchar(32).
"""

from alembic import op

revision = "0025_phase2_drop_dup_turn_events_idx"
down_revision = "0024_phase2_turn_start_spec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Two statements: some drivers only run the first if concatenated.
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE varchar(64)")
    op.execute("DROP INDEX IF EXISTS idx_turn_events_turn_sequence")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_turn_events_turn_sequence "
        "ON turn_events (turn_id, sequence)"
    )
