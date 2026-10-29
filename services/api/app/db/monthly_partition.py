"""把已有时间列的普通表挂成按月分区。切点之后已有行则停下，不改名、不挂载。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text

_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class MonthlyTable:
    table: str
    time_column: str
    columns_sql: str
    indexes: tuple[tuple[str, str], ...] = ()
    foreign_keys: tuple[tuple[str, str], ...] = ()
    sequence: str | None = None
    id_column: str = "id"


SERIES_SPECS = (
    MonthlyTable(
        table="session_raw_snapshots",
        time_column="created_at",
        columns_sql="""
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL,
            turn_id UUID NOT NULL,
            step_index INT NOT NULL DEFAULT 0,
            messages JSONB NOT NULL DEFAULT '[]'::jsonb,
            tools_fingerprint TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        """,
        indexes=(
            ("idx_session_raw_snapshots_turn", "(turn_id, step_index)"),
            ("idx_session_raw_snapshots_session", "(session_id, created_at DESC)"),
        ),
        foreign_keys=(
            (
                "session_raw_snapshots_session_id_fkey",
                "FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE",
            ),
        ),
    ),
    MonthlyTable(
        table="model_request_envelopes",
        time_column="created_at",
        columns_sql="""
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            turn_id UUID NOT NULL,
            session_id UUID,
            step_index INT NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL,
            fill_ratio DOUBLE PRECISION,
            envelope JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        """,
        indexes=(
            ("idx_model_request_envelopes_turn", "(turn_id, step_index)"),
        ),
    ),
    MonthlyTable(
        table="projection_log",
        time_column="created_at",
        columns_sql="""
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            turn_id UUID,
            last_event_sequence BIGINT NOT NULL DEFAULT 0,
            error TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        """,
        indexes=(
            ("idx_projection_log_turn", "(turn_id, created_at DESC)"),
        ),
    ),
    MonthlyTable(
        table="audit_log",
        time_column="ts",
        columns_sql="""
            id BIGINT NOT NULL DEFAULT nextval('audit_log_id_seq'::regclass),
            ts TIMESTAMPTZ NOT NULL DEFAULT now(),
            actor_user_id UUID,
            actor_username TEXT,
            action VARCHAR(64) NOT NULL,
            resource_type VARCHAR(32) NOT NULL,
            resource_id TEXT,
            detail JSONB,
            PRIMARY KEY (id, ts)
        """,
        indexes=(
            ("idx_audit_log_ts", "(ts DESC)"),
            ("idx_audit_log_actor", "(actor_user_id, ts DESC)"),
        ),
        sequence="audit_log_id_seq",
    ),
)


def _ident(name: str) -> str:
    if not _IDENT.fullmatch(name):
        raise RuntimeError(f"refusing identifier {name!r}")
    return name


def month_bounds(cutover: datetime, count: int = 3) -> list[tuple[datetime, datetime]]:
    """月分区从切换点起算。历史分区的上界就是切换点，两边不重叠。"""
    start = datetime(cutover.year, cutover.month, 1, tzinfo=timezone.utc)
    bounds: list[tuple[datetime, datetime]] = []
    year = start.year
    month = start.month
    for _ in range(count):
        begin = datetime(year, month, 1, tzinfo=timezone.utc)
        month += 1
        if month > 12:
            month = 1
            year += 1
        end = datetime(year, month, 1, tzinfo=timezone.utc)
        bounds.append((begin, end))
    return bounds


def attach_monthly_history(get_bind, run_concurrent, spec: MonthlyTable) -> None:
    """旧表变成历史分区。切换点是下个月 1 日；切点上已有行则抛错并停止。"""
    table = _ident(spec.table)
    time_column = _ident(spec.time_column)
    id_column = _ident(spec.id_column)
    unique_index = _ident(f"uq_{table}_{id_column}_{time_column}")
    run_concurrent(
        f"""
        CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {unique_index}
        ON {table} ({id_column}, {time_column})
        """
    )
    bind = get_bind()
    # 此后同一事务持 ACCESS EXCLUSIVE，直到挂载结束。
    bind.execute(text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    cutover = bind.execute(
        text("SELECT date_trunc('month', now()) + interval '1 month'")
    ).scalar()
    if cutover is None:
        raise RuntimeError(f"{table} cutover is missing; migration stopped")
    future = bind.execute(
        text(f"SELECT 1 FROM {table} WHERE {time_column} >= :cutover LIMIT 1"),
        {"cutover": cutover},
    ).first()
    if future is not None:
        # 切点之后已有行时历史分区和月分区的范围会叠在一起，停在改名之前。
        raise RuntimeError(
            f"{table} has rows on or after the cutover; migration stopped"
        )
    cutover_sql = cutover.isoformat()
    bind.execute(text(
        f"""
        ALTER TABLE {table}
        ADD CONSTRAINT {table}_history_cut
        CHECK ({time_column} < TIMESTAMPTZ '{cutover_sql}') NOT VALID
        """
    ))
    bind.execute(text(
        f"ALTER TABLE {table} VALIDATE CONSTRAINT {table}_history_cut"
    ))
    bind.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey"))
    bind.execute(text(
        f"""
        ALTER TABLE {table}
        ADD CONSTRAINT {table}_pkey
        PRIMARY KEY USING INDEX {unique_index}
        """
    ))
    bind.execute(text(
        f"""
        CREATE TABLE {table}_parent (
            {spec.columns_sql}
        ) PARTITION BY RANGE ({time_column})
        """
    ))
    bind.execute(text(f"ALTER TABLE {table} RENAME TO {table}_history"))
    bind.execute(text(f"ALTER TABLE {table}_parent RENAME TO {table}"))
    bind.execute(text(
        f"""
        ALTER TABLE {table}
        ATTACH PARTITION {table}_history
        FOR VALUES FROM (MINVALUE) TO (TIMESTAMPTZ '{cutover_sql}')
        """
    ))
    for name, _body in spec.foreign_keys:
        constraint = _ident(name)
        bind.execute(text(
            f"ALTER TABLE {table}_history DROP CONSTRAINT IF EXISTS {constraint}"
        ))
    for name, body in spec.foreign_keys:
        constraint = _ident(name)
        bind.execute(text(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} {body}"
        ))
    for name, _columns in spec.indexes:
        bind.execute(text(f"DROP INDEX IF EXISTS {_ident(name)}"))
    for name, columns in spec.indexes:
        bind.execute(text(
            f"CREATE INDEX {_ident(name)} ON {table} {columns}"
        ))
    if spec.sequence is not None:
        sequence = _ident(spec.sequence)
        bind.execute(text(
            f"ALTER SEQUENCE {sequence} OWNED BY {table}.{id_column}"
        ))
    for begin, end in month_bounds(cutover, 3):
        name = f"{table}_y{begin.year}m{begin.month:02d}"
        bind.execute(text(
            f"""
            CREATE TABLE IF NOT EXISTS {name}
            PARTITION OF {table}
            FOR VALUES FROM (TIMESTAMPTZ '{begin.isoformat()}')
            TO (TIMESTAMPTZ '{end.isoformat()}')
            """
        ))
