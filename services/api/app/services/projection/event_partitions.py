"""turn_events 月分区：提前建下月，过保留期且没有非终态 Turn 时删分区。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.db.monthly_partition import SERIES_SPECS, _ident
from app.db.pool import get_bypass_pool
from app.observability.metrics import metrics
from app.settings import settings

logger = logging.getLogger(__name__)


def classify_partition(
    *,
    non_terminal: bool,
    newest_update: datetime | None,
    upper_bound: datetime | None,
    now: datetime,
    retention_days: int,
) -> str:
    """返回 pinned、drop 或 keep。

    分区里还有非终态 Turn 时不删，调用方记 gc_aborted。
    上界还没过保留期，或者分区里最新的 Turn 还没过保留期，也不删。
    """
    if non_terminal:
        return "pinned"
    if upper_bound is None:
        return "keep"
    horizon = now - timedelta(days=retention_days)
    if upper_bound > horizon:
        return "keep"
    if newest_update is not None and newest_update >= horizon:
        return "keep"
    return "drop"


def same_turn_month(turn_created_at: datetime, event_ts: datetime) -> str:
    """分区月份只看 Turn 的创建时间。事件 ts 跨月也不换分区。"""
    del event_ts
    return turn_created_at.strftime("%Y-%m")


async def maintain_turn_event_partitions() -> dict[str, int]:
    """建当前月和下一个月的分区，并按保留期删除已经空出来的旧分区。"""
    pool = await get_bypass_pool()
    days = max(1, int(getattr(settings, "events_structural_retention_days", 90) or 90))
    now = datetime.now(timezone.utc)
    created = 0
    dropped = 0
    pinned = 0
    async with pool.acquire() as conn:
        parent = await conn.fetchval(
            "SELECT to_regclass('public.turn_events') IS NOT NULL"
        )
        if not parent:
            return {"created": 0, "dropped": 0, "pinned": 0}
        partitioned = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM pg_partitioned_table
                WHERE partrelid = 'public.turn_events'::regclass
            )
            """
        )
        if not partitioned:
            return {"created": 0, "dropped": 0, "pinned": 0}
        for offset in (0, 1):
            month = _month_start(now, offset)
            name = f"turn_events_y{month.year}m{month.month:02d}"
            nxt = _month_start(now, offset + 1)
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {name}
                PARTITION OF turn_events
                FOR VALUES FROM ('{month.isoformat()}') TO ('{nxt.isoformat()}')
                """
            )
            created += 1
        rows = await conn.fetch(
            """
            SELECT child.relname AS name,
                   pg_get_expr(child.relpartbound, child.oid) AS bound
            FROM pg_inherits
            JOIN pg_class parent ON parent.oid = pg_inherits.inhparent
            JOIN pg_class child ON child.oid = pg_inherits.inhrelid
            WHERE parent.relname = 'turn_events'
            """
        )
        for row in rows:
            upper = _upper_bound(str(row["bound"] or ""))
            stats = await conn.fetchrow(
                """
                SELECT
                    EXISTS (
                        SELECT 1 FROM turns t
                        WHERE t.created_at < $1::timestamptz
                          AND ($2::timestamptz IS NULL OR t.created_at >= $2::timestamptz)
                          AND t.status NOT IN ('completed', 'failed', 'cancelled')
                    ) AS non_terminal,
                    (
                        SELECT max(t.updated_at) FROM turns t
                        WHERE t.created_at < $1::timestamptz
                          AND ($2::timestamptz IS NULL OR t.created_at >= $2::timestamptz)
                    ) AS newest
                """,
                upper or now,
                _lower_bound(str(row["bound"] or "")),
            )
            decision = classify_partition(
                non_terminal=bool(stats["non_terminal"]) if stats else False,
                newest_update=stats["newest"] if stats else None,
                upper_bound=upper,
                now=now,
                retention_days=days,
            )
            if decision == "pinned":
                pinned += 1
                metrics.inc("gc_aborted", layer="0", reason="partition_pinned")
                continue
            if decision != "drop":
                continue
            name = str(row["name"])
            if not name.startswith("turn_events_"):
                continue
            await conn.execute(f"DROP TABLE {name}")
            dropped += 1
    if dropped or pinned:
        logger.info("turn_events partitions dropped=%s pinned=%s", dropped, pinned)
    return {"created": created, "dropped": dropped, "pinned": pinned}


async def maintain_series_partitions() -> dict[str, int]:
    """四张时间序列表：建当前月和下一个月，上界已过保留期则删分区。"""
    pool = await get_bypass_pool()
    days = max(1, int(getattr(settings, "events_structural_retention_days", 90) or 90))
    now = datetime.now(timezone.utc)
    created = 0
    dropped = 0
    async with pool.acquire() as conn:
        for spec in SERIES_SPECS:
            table = _ident(spec.table)
            present = await conn.fetchval(
                "SELECT to_regclass($1) IS NOT NULL",
                f"public.{table}",
            )
            if not present:
                continue
            partitioned = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_partitioned_table
                    WHERE partrelid = $1::regclass
                )
                """,
                f"public.{table}",
            )
            if not partitioned:
                continue
            for offset in (0, 1):
                month = _month_start(now, offset)
                name = f"{table}_y{month.year}m{month.month:02d}"
                nxt = _month_start(now, offset + 1)
                await conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {name}
                    PARTITION OF {table}
                    FOR VALUES FROM ('{month.isoformat()}') TO ('{nxt.isoformat()}')
                    """
                )
                created += 1
            rows = await conn.fetch(
                """
                SELECT child.relname AS name,
                       pg_get_expr(child.relpartbound, child.oid) AS bound
                FROM pg_inherits
                JOIN pg_class parent ON parent.oid = pg_inherits.inhparent
                JOIN pg_class child ON child.oid = pg_inherits.inhrelid
                WHERE parent.relname = $1
                """,
                table,
            )
            for row in rows:
                upper = _upper_bound(str(row["bound"] or ""))
                decision = classify_partition(
                    non_terminal=False,
                    newest_update=None,
                    upper_bound=upper,
                    now=now,
                    retention_days=days,
                )
                if decision != "drop":
                    continue
                name = str(row["name"])
                if not name.startswith(f"{table}_"):
                    continue
                await conn.execute(f"DROP TABLE {name}")
                dropped += 1
    if dropped:
        logger.info("series partitions dropped=%s", dropped)
    return {"created": created, "dropped": dropped}


def _month_start(now: datetime, offset: int) -> datetime:
    year = now.year
    month = now.month + offset
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def _upper_bound(expr: str) -> datetime | None:
    # FOR VALUES FROM (...) TO ('timestamp')
    marker = "TO ("
    if marker not in expr:
        return None
    raw = expr.split(marker, 1)[1].split(")", 1)[0].strip().strip("'")
    if raw.upper() == "MAXVALUE":
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _lower_bound(expr: str) -> datetime | None:
    marker = "FROM ("
    if marker not in expr:
        return None
    raw = expr.split(marker, 1)[1].split(")", 1)[0].strip().strip("'")
    if raw.upper() == "MINVALUE":
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
