from __future__ import annotations

import pytest

from app.tools.core import memory as memory_tools


@pytest.mark.asyncio
async def test_remember_and_recall(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.tools.core.memory.settings.data_dir", str(tmp_path))
    from app.tenant_context import bind_tenant_context, reset_tenant_context
    from uuid import uuid4

    work_id = uuid4()
    tokens = bind_tenant_context(work_root=str(tmp_path / "w"), work_id=work_id)
    try:
        saved = await memory_tools.remember("Prefer concise Chinese prose", namespace="style", importance=0.9)
        assert saved["status"] == "remembered"
        hits = await memory_tools.recall("Chinese prose", namespace="style", limit=3)
        assert hits["hits"]
        assert "concise" in hits["hits"][0]["text"]
    finally:
        reset_tenant_context(tokens)

    # Different work must not see the note.
    tokens2 = bind_tenant_context(work_root=str(tmp_path / "w2"), work_id=uuid4())
    try:
        other = await memory_tools.recall("Chinese prose", namespace="style", limit=3)
        assert other["hits"] == []
    finally:
        reset_tenant_context(tokens2)


@pytest.mark.asyncio
async def test_remember_rejects_sources_namespace(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.tools.core.memory.settings.data_dir", str(tmp_path))
    result = await memory_tools.remember("x", namespace="sources")
    assert result["status"] == "failed"
