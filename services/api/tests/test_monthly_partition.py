"""切点上已有行时迁移停下；保留期内的分区不删。"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from app.db.monthly_partition import (
    SERIES_SPECS,
    attach_monthly_history,
    month_bounds,
)
from app.services.projection.event_partitions import maintain_series_partitions


def test_audit_log_partitions_on_ts_and_the_others_on_created_at() -> None:
    by_name = {spec.table: spec for spec in SERIES_SPECS}
    assert by_name["audit_log"].time_column == "ts"
    assert "PRIMARY KEY (id, ts)" in by_name["audit_log"].columns_sql
    assert by_name["audit_log"].sequence == "audit_log_id_seq"
    for name in ("session_raw_snapshots", "model_request_envelopes", "projection_log"):
        assert by_name[name].time_column == "created_at"
        assert "PRIMARY KEY (id, created_at)" in by_name[name].columns_sql
    assert "ON DELETE CASCADE" in by_name["session_raw_snapshots"].foreign_keys[0][1]


def test_month_partitions_start_at_the_cutover() -> None:
    cutover = datetime(2026, 11, 1, tzinfo=timezone.utc)
    bounds = month_bounds(cutover, 3)
    assert bounds[0] == (
        datetime(2026, 11, 1, tzinfo=timezone.utc),
        datetime(2026, 12, 1, tzinfo=timezone.utc),
    )
    assert bounds[-1][0] == datetime(2027, 1, 1, tzinfo=timezone.utc)


class _Result:
    def __init__(self, row) -> None:
        self._row = row

    def first(self):
        return self._row

    def scalar(self):
        return self._row


class _Bind:
    def __init__(self, future: bool) -> None:
        self.sql: list[str] = []
        self.future = future

    def execute(self, statement, params=None):
        sql = str(statement)
        self.sql.append(sql)
        if "date_trunc" in sql:
            return _Result(datetime(2026, 11, 1, tzinfo=timezone.utc))
        if ">=" in sql:
            return _Result((1,) if self.future else None)
        return _Result(None)


def test_future_rows_stop_before_attach() -> None:
    bind = _Bind(future=True)
    concurrent: list[str] = []
    with pytest.raises(RuntimeError, match="on or after the cutover"):
        attach_monthly_history(
            lambda: bind,
            concurrent.append,
            SERIES_SPECS[3],
        )
    joined = "\n".join(bind.sql)
    assert "ATTACH" not in joined
    assert "RENAME" not in joined
    assert concurrent
    assert "audit_log" in concurrent[0]
    assert "ts" in concurrent[0]


def test_empty_future_attaches_history_up_to_the_cutover() -> None:
    bind = _Bind(future=False)
    attach_monthly_history(lambda: bind, lambda _sql: None, SERIES_SPECS[0])
    joined = "\n".join(bind.sql)
    assert "ATTACH PARTITION session_raw_snapshots_history" in joined
    assert "TO (TIMESTAMPTZ '2026-11-01T00:00:00+00:00')" in joined
    assert "session_raw_snapshots_y2026m11" in joined
    assert "ON DELETE CASCADE" in joined


def _pool(conn):
    acquired = MagicMock()
    acquired.__aenter__ = AsyncMock(return_value=conn)
    acquired.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquired)
    return pool


class _FrozenNow(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 29, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_partition_inside_retention_is_not_dropped() -> None:
    conn = MagicMock()
    conn.fetchval = AsyncMock(side_effect=[True, True, False, False, False])
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "name": "session_raw_snapshots_y2026m11",
                "bound": "FOR VALUES FROM ('2026-11-01T00:00:00+00:00') TO ('2026-12-01T00:00:00+00:00')",
            }
        ]
    )
    with (
        patch(
            "app.services.projection.event_partitions.get_bypass_pool",
            new_callable=AsyncMock,
            return_value=_pool(conn),
        ),
        patch("app.services.projection.event_partitions.datetime", _FrozenNow),
    ):
        out = await maintain_series_partitions()
    assert out["dropped"] == 0
    dropped = [
        call.args[0]
        for call in conn.execute.await_args_list
        if "DROP TABLE" in str(call.args[0])
    ]
    assert dropped == []


@pytest.mark.asyncio
async def test_partition_past_retention_is_dropped() -> None:
    conn = MagicMock()
    conn.fetchval = AsyncMock(side_effect=[True, True, False, False, False])
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(
        return_value=[
            {
                "name": "session_raw_snapshots_y2020m01",
                "bound": "FOR VALUES FROM ('2020-01-01T00:00:00+00:00') TO ('2020-02-01T00:00:00+00:00')",
            }
        ]
    )
    with (
        patch(
            "app.services.projection.event_partitions.get_bypass_pool",
            new_callable=AsyncMock,
            return_value=_pool(conn),
        ),
        patch("app.services.projection.event_partitions.datetime", _FrozenNow),
    ):
        out = await maintain_series_partitions()
    assert out["dropped"] == 1
    dropped = [
        call.args[0]
        for call in conn.execute.await_args_list
        if "DROP TABLE" in str(call.args[0])
    ]
    assert dropped == ["DROP TABLE session_raw_snapshots_y2020m01"]


def test_revision_chain_is_one_migration_per_table() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    chain = [
        ("0037_session_raw_snapshots_partition.py", "0036_turn_events_partition", "0037_raw_snapshots_partition"),
        ("0038_model_request_envelopes_partition.py", "0037_raw_snapshots_partition", "0038_model_envelopes_partition"),
        ("0039_projection_log_partition.py", "0038_model_envelopes_partition", "0039_projection_log_partition"),
        ("0040_audit_log_partition.py", "0039_projection_log_partition", "0040_audit_log_partition"),
    ]
    for filename, previous, revision in chain:
        text_src = (root / filename).read_text()
        assert f'down_revision = "{previous}"' in text_src
        assert f'revision = "{revision}"' in text_src
        assert len(revision) <= 32


def test_text_roundtrip_keeps_the_predicate() -> None:
    assert ">=" in str(text("SELECT 1 FROM audit_log WHERE ts >= :cutover"))


def test_turn_events_notify_trigger_is_on_the_parent() -> None:
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0036_turn_events_partition.py"
    ).read_text()
    drop = src.index("DROP TRIGGER IF EXISTS turn_events_notify ON turn_events_history")
    create = src.index("CREATE TRIGGER turn_events_notify", drop)
    body = src[create:create + 200]
    assert "AFTER INSERT ON turn_events" in body
    assert "EXECUTE FUNCTION notify_turn_event()" in body
    assert "ON turn_events_history" not in body


def test_repack_is_not_invoked_when_free_space_is_under_1_2x(caplog) -> None:
    from app.db.table_repack import repack_argv

    with caplog.at_level("WARNING"):
        argv = repack_argv("audit_log", free_bytes=119, table_bytes=100)
    assert argv == []
    assert "disk_low" in caplog.text
    assert "pg_repack" not in " ".join(argv)


def test_repack_argv_when_free_space_covers_1_2x() -> None:
    from app.db.table_repack import repack_argv

    assert repack_argv("audit_log", free_bytes=120, table_bytes=100) == [
        "pg_repack",
        "--table",
        "audit_log",
    ]

