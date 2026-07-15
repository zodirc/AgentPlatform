from __future__ import annotations

import asyncio
from typing import Any


async def search_records(
    query: str,
    channel: str = "auto",
    limit: int = 10,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Multi-table recall stub (docs/17 S3 A20 / docs/18).

    Deterministic rule router placeholder: no LLM routing, no graph node.
    Real channels will race with ≤300ms timeouts and ACL filters later.
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
        "hint": "No business record backends configured; see docs/18-a20-multitable-recall.md",
        "summary": "search_records: stub (0 hits)",
    }
