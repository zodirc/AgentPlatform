from __future__ import annotations

import pytest

from app.tools.core.records import search_records


@pytest.mark.asyncio
async def test_search_records_stub_empty_honest() -> None:
    result = await search_records("customer ACME")
    assert result["status"] == "unimplemented"
    assert result["hits"] == []
    assert "docs/18" in result.get("hint", "")
