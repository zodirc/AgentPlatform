"""Partition audit_log by ts.

audit_log has no created_at column. The primary key becomes (id, ts) and the
existing sequence stays owned by the parent. Rows on or after next month's
first day stop the migration before the rename.
"""

from __future__ import annotations

from alembic import op

from app.db.monthly_partition import SERIES_SPECS, attach_monthly_history

revision = "0040_audit_log_partition"
down_revision = "0039_projection_log_partition"
branch_labels = None
depends_on = None

_SPEC = SERIES_SPECS[3]


def upgrade() -> None:
    def _concurrent(sql: str) -> None:
        with op.get_context().autocommit_block():
            op.execute(sql)

    attach_monthly_history(op.get_bind, _concurrent, _SPEC)


def downgrade() -> None:
    pass
