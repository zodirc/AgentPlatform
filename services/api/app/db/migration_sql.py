from __future__ import annotations

from pathlib import Path

from alembic import op

DDL_DIR = Path("/app/contracts/ddl")
if not DDL_DIR.exists():
    DDL_DIR = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "schemas" / "ddl"


def run_ddl(filename: str) -> None:
    sql = (DDL_DIR / filename).read_text()
    op.execute(sql)
