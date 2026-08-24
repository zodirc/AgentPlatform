"""Alembic revision 内嵌 DDL 执行辅助。

从 ``packages/contracts/schemas/ddl``（或容器内 ``/app/contracts/ddl``）读取
SQL 文件并在 migration 上下文中 ``op.execute``。
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

DDL_DIR = Path("/app/contracts/ddl")
if not DDL_DIR.exists():
    DDL_DIR = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "schemas" / "ddl"


def run_ddl(filename: str) -> None:
    """在 Alembic upgrade 事务中执行指定 DDL 文件。

    参数:
        filename: ``DDL_DIR`` 下的 SQL 文件名（如 ``001_sessions.sql``）。

    返回:
        无。

    异常:
        FileNotFoundError: DDL 文件不存在。
        数据库错误: ``op.execute`` 执行失败时由 Alembic/驱动抛出。
    """
    sql = (DDL_DIR / filename).read_text()
    op.execute(sql)
