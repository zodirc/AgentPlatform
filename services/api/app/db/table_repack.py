"""非分区表在线重写前的空闲空间门。不够就不拼命令。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def repack_argv(table: str, *, free_bytes: int, table_bytes: int) -> list[str]:
    """空闲空间少于表大小的 1.2 倍时返回空列表并告警。"""
    if table_bytes > 0 and free_bytes * 5 < table_bytes * 6:
        logger.warning("pg_repack skipped table=%s reason=disk_low", table)
        return []
    if table_bytes <= 0:
        return []
    return ["pg_repack", "--table", table]
