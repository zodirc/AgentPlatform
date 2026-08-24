"""业务记录多表检索占位（docs/13 S3 A20 / docs/17）。

``search_records`` 为确定性规则路由 stub：无 LLM 路由、无图节点；
真实通道后续将并行竞速（≤300ms 超时）并套 ACL 过滤。
"""

from __future__ import annotations

import asyncio
from typing import Any


async def search_records(
    query: str,
    channel: str = "auto",
    limit: int = 10,
    **_kwargs: Any,
) -> dict[str, Any]:
    """多表业务记录检索 stub（docs/13 / docs/17）。

    参数:
        query: 检索词。
        channel: ``auto`` 时并行 crm/orders 占位；否则单通道。
        limit: 命中上限（当前 stub 恒为 0）。

    返回:
        ``status=unimplemented`` 与 ``channels`` 并行 scaffold 结果；空 query 时 ``failed``。
    """
    q = (query or "").strip()
    if not q:
        return {
            "query": q,
            "channel": channel,
            "hits": [],
            "status": "failed",
            "error": "query is required",
            "summary": "search_records: empty query",
        }

    # Simulate parallel channel scaffold with hard timeout budget.
    async def _empty_channel(name: str) -> dict[str, Any]:
        """占位通道：立即返回空 hits（模拟 ≤300ms 并行 budget）。"""
        await asyncio.sleep(0)
        return {"channel": name, "hits": [], "degraded": False}

    channels = ["crm", "orders"] if channel in {"auto", ""} else [channel]
    tasks = [asyncio.wait_for(_empty_channel(name), timeout=0.3) for name in channels]
    results: list[dict[str, Any]] = []
    for task in asyncio.as_completed(tasks):
        try:
            results.append(await task)
        except asyncio.TimeoutError:
            results.append({"channel": "unknown", "hits": [], "degraded": True})

    return {
        "query": q,
        "channel": channel,
        "hits": [],
        "channels": results,
        "status": "unimplemented",
        "hint": "No business record backends configured; see docs/17-search-records.md",
        "summary": "search_records: stub (0 hits)",
    }
