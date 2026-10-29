"""Alembic revision 内嵌 DDL 执行辅助。

从 ``packages/contracts/schemas/ddl``（或容器内 ``/app/contracts/ddl``）读取
SQL 文件并在 migration 上下文中 ``op.execute``。
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

def _ddl_dirs() -> list[Path]:
    here = Path(__file__).resolve()
    checkout = here.parents[4] / "packages" / "contracts" / "schemas" / "ddl"
    return [checkout, Path("/app/contracts/ddl")]


DDL_DIR = next(path for path in _ddl_dirs() if path.is_dir())


def run_ddl(filename: str) -> None:
    """在 Alembic upgrade 事务中执行指定 DDL 文件。

    参数:
        filename: DDL 目录下的 SQL 文件名（如 ``001_sessions.sql``）。

    返回:
        无。

    异常:
        FileNotFoundError: 检出目录和 ``/app/contracts/ddl`` 都没有该文件。
        数据库错误: ``op.execute`` 执行失败时由 Alembic/驱动抛出。
    """
    for directory in _ddl_dirs():
        path = directory / filename
        if path.is_file():
            op.execute(path.read_text())
            return
    raise FileNotFoundError(filename)
