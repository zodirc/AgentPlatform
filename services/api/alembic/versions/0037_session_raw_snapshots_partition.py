"""Partition session_raw_snapshots by created_at.

The old table becomes one history partition. Rows on or after next month's
first day stop the migration before the rename.
"""

from __future__ import annotations

from alembic import op

from app.db.monthly_partition import SERIES_SPECS, attach_monthly_history

revision = "0037_session_raw_snapshots_partition"
down_revision = "0036_turn_events_partition"
branch_labels = None
depends_on = None

_SPEC = SERIES_SPECS[0]


def upgrade() -> None:
    def _concurrent(sql: str) -> None:
        with op.get_context().autocommit_block():
            op.execute(sql)

    attach_monthly_history(op.get_bind, _concurrent, _SPEC)


def downgrade() -> None:
    pass
