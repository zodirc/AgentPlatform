"""Partition turn_events by the owning turn's created_at.

Stops if (turn_id, sequence) is already duplicated. The old table becomes one
history partition. Turns created after the cutover land in monthly partitions.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0036_turn_events_partition"
down_revision = "0035_work_tombstones"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicate = bind.execute(
        text(
            """
            SELECT 1
            FROM turn_events
            GROUP BY turn_id, sequence
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError("turn_events has duplicate (turn_id, sequence); migration stopped")

    bind.execute(text(
        "ALTER TABLE turn_events ADD COLUMN IF NOT EXISTS turn_created_at timestamptz"
    ))
    while True:
        with op.get_context().autocommit_block():
            result = op.get_bind().execute(
                text(
                    """
                    WITH batch AS (
                        SELECT ctid
                        FROM turn_events
                        WHERE turn_created_at IS NULL
                        LIMIT 5000
                    )
                    UPDATE turn_events te
                    SET turn_created_at = COALESCE(
                        (SELECT t.created_at FROM turns t WHERE t.id = te.turn_id),
                        te.ts
                    )
                    FROM batch
                    WHERE te.ctid = batch.ctid
                    """
                )
            )
        if not result.rowcount:
            break

    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE turn_events ALTER COLUMN turn_created_at SET NOT NULL"
    ))
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_turn_events_event_created
            ON turn_events (event_id, turn_created_at)
            """
        )
        op.execute(
            """
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_turn_events_seq_created
            ON turn_events (turn_id, sequence, turn_created_at)
            """
        )

    bind = op.get_bind()
    bind.execute(text("LOCK TABLE turn_events IN ACCESS EXCLUSIVE MODE"))
    cutover = bind.execute(
        text("SELECT date_trunc('month', now()) + interval '1 month'")
    ).scalar()
    future = bind.execute(
        text("SELECT 1 FROM turn_events WHERE turn_created_at >= :cutover LIMIT 1"),
        {"cutover": cutover},
    ).first()
    if future is not None:
        raise RuntimeError("turn_events has turn_created_at on or after the cutover; migration stopped")
    cutover_sql = cutover.isoformat()
    bind.execute(text(
        f"""
        ALTER TABLE turn_events
        ADD CONSTRAINT turn_events_history_cut
        CHECK (turn_created_at < TIMESTAMPTZ '{cutover_sql}') NOT VALID
        """
    ))
    bind.execute(text(
        "ALTER TABLE turn_events VALIDATE CONSTRAINT turn_events_history_cut"
    ))
    bind.execute(text("ALTER TABLE turn_events DROP CONSTRAINT IF EXISTS turn_events_pkey"))
    bind.execute(text(
        "ALTER TABLE turn_events DROP CONSTRAINT IF EXISTS turn_events_turn_id_sequence_key"
    ))
    bind.execute(text(
        """
        ALTER TABLE turn_events
        ADD CONSTRAINT turn_events_pkey
        PRIMARY KEY USING INDEX uq_turn_events_event_created
        """
    ))
    bind.execute(text(
        """
        ALTER TABLE turn_events
        ADD CONSTRAINT turn_events_turn_id_sequence_turn_created_at_key
        UNIQUE USING INDEX uq_turn_events_seq_created
        """
    ))
    bind.execute(text(
        """
        CREATE TABLE turn_events_parent (
            event_id            UUID NOT NULL DEFAULT gen_random_uuid(),
            turn_id             UUID NOT NULL,
            stream_id           UUID NOT NULL,
            sequence            BIGINT NOT NULL,
            type                VARCHAR(64) NOT NULL,
            run_id              UUID NOT NULL,
            step_index          INTEGER NOT NULL DEFAULT 0,
            trace_id            UUID NOT NULL,
            causation_id        UUID,
            ts                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            payload             JSONB NOT NULL DEFAULT '{}',
            turn_created_at     TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (event_id, turn_created_at),
            UNIQUE (turn_id, sequence, turn_created_at)
        ) PARTITION BY RANGE (turn_created_at)
        """
    ))
    bind.execute(text("ALTER TABLE turn_events RENAME TO turn_events_history"))
    bind.execute(text("ALTER TABLE turn_events_parent RENAME TO turn_events"))
    bind.execute(text(
        f"""
        ALTER TABLE turn_events
        ATTACH PARTITION turn_events_history
        FOR VALUES FROM (MINVALUE) TO (TIMESTAMPTZ '{cutover_sql}')
        """
    ))
    bind.execute(text(
        "ALTER TABLE turn_events_history DROP CONSTRAINT IF EXISTS turn_events_turn_id_fkey"
    ))
    bind.execute(text(
        "ALTER TABLE turn_events_history DROP CONSTRAINT IF EXISTS turn_events_run_id_fkey"
    ))
    bind.execute(text(
        """
        ALTER TABLE turn_events
        ADD CONSTRAINT turn_events_turn_id_fkey
        FOREIGN KEY (turn_id) REFERENCES turns(id)
        """
    ))
    bind.execute(text(
        """
        ALTER TABLE turn_events
        ADD CONSTRAINT turn_events_run_id_fkey
        FOREIGN KEY (run_id) REFERENCES runs(id)
        """
    ))
    bind.execute(text("DROP TRIGGER IF EXISTS turn_events_notify ON turn_events_history"))
    bind.execute(text(
        """
        CREATE TRIGGER turn_events_notify
        AFTER INSERT ON turn_events
        FOR EACH ROW EXECUTE FUNCTION notify_turn_event()
        """
    ))
    bind.execute(text(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_runtime_append') THEN
                GRANT INSERT ON turn_events TO agent_runtime_append;
                REVOKE UPDATE, DELETE ON turn_events FROM agent_runtime_append;
            END IF;
        END $$
        """
    ))
    bind.execute(text("DROP INDEX IF EXISTS idx_turn_events_run_id"))
    bind.execute(text(
        "CREATE INDEX idx_turn_events_run_id ON turn_events (run_id)"
    ))
    _ensure_months(bind, cutover)


def _ensure_months(bind, cutover) -> None:
    from datetime import datetime, timezone

    start = datetime(cutover.year, cutover.month, 1, tzinfo=timezone.utc)
    for offset in range(3):
        year = start.year
        month = start.month + offset
        while month > 12:
            month -= 12
            year += 1
        begin = datetime(year, month, 1, tzinfo=timezone.utc)
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year += 1
        end = datetime(next_year, next_month, 1, tzinfo=timezone.utc)
        name = f"turn_events_y{year}m{month:02d}"
        bind.execute(text(
            f"""
            CREATE TABLE IF NOT EXISTS {name}
            PARTITION OF turn_events
            FOR VALUES FROM (TIMESTAMPTZ '{begin.isoformat()}')
            TO (TIMESTAMPTZ '{end.isoformat()}')
            """
        ))


def downgrade() -> None:
    pass
