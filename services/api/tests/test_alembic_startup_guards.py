from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

from app.db.migrate import widen_alembic_version_column

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
ENV_PY = Path(__file__).resolve().parents[1] / "alembic" / "env.py"
# Already stamped in production; env.py widens version_num to varchar(64).
_LONG_OK = {"0025_phase2_drop_dup_turn_events_idx"}
_REVISION_RE = re.compile(r'^revision\s*=\s*["\']([^"\']+)["\']', re.M)
_EXECUTE_RE = re.compile(
    r"op\.execute\(\s*(?:sql\s*=\s*)?[fr]?[\"']([^\"']+)[\"']",
    re.I,
)


def test_startup_migrations_do_not_emit_concurrent_ddl() -> None:
    for path in sorted(VERSIONS.glob("*.py")):
        for sql in _EXECUTE_RE.findall(path.read_text()):
            assert "CONCURRENTLY" not in sql.upper(), path.name


def test_new_revision_ids_fit_alembic_default_varchar32() -> None:
    for path in sorted(VERSIONS.glob("*.py")):
        match = _REVISION_RE.search(path.read_text())
        assert match, path.name
        rev = match.group(1)
        if rev in _LONG_OK:
            assert len(rev) <= 64, rev
            continue
        assert len(rev) <= 32, f"{path.name} revision {rev!r} is {len(rev)} chars"


def test_env_widens_version_num_before_upgrade() -> None:
    text = ENV_PY.read_text()
    assert "widen_alembic_version_column" in text


def test_widen_skips_non_postgres() -> None:
    conn = MagicMock()
    conn.dialect.name = "sqlite"
    widen_alembic_version_column(conn)
    conn.execute.assert_not_called()


def test_widen_alters_postgres_and_commits() -> None:
    conn = MagicMock()
    conn.dialect.name = "postgresql"
    conn.in_transaction.return_value = True
    widen_alembic_version_column(conn)
    clause = conn.execute.call_args.args[0]
    sql = str(getattr(clause, "text", clause)).lower()
    assert "varchar(64)" in sql
    conn.commit.assert_called_once()
