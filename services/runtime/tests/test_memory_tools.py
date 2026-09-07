from __future__ import annotations

from uuid import uuid4

import pytest

from app.tenant_context import bind_tenant_context, reset_tenant_context
from app.tools.core import memory as memory_tools
from app.tools.core import memory_pg


@pytest.mark.asyncio
async def test_remember_and_recall(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.tools.core.memory.settings.data_dir", str(tmp_path))
    work_id = uuid4()
    tokens = bind_tenant_context(work_root=str(tmp_path / "w"), work_id=work_id)
    try:
        saved = await memory_tools.remember("Prefer concise Chinese prose", namespace="style", importance=0.9)
        assert saved["status"] == "remembered"
        hits = await memory_tools.recall("Chinese prose", namespace="style", limit=3)
        assert hits["hits"]
        assert "concise" in hits["hits"][0]["text"]
        gone = await memory_tools.forget(memory_id=str(saved["id"]))
        assert gone["deleted"] >= 1
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
async def test_remember_session_scope_hidden_from_other_session(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.tools.core.memory.settings.data_dir", str(tmp_path))
    work_id = uuid4()
    sid_a = uuid4()
    tokens = bind_tenant_context(work_root=str(tmp_path / "w"), work_id=work_id)
    try:
        await memory_tools.remember(
            "session only note xyzzy", namespace="style", scope="session", session_id=sid_a
        )
        hit = await memory_tools.recall("xyzzy", namespace="style", session_id=sid_a)
        assert hit["hits"]
        miss = await memory_tools.recall("xyzzy", namespace="style", session_id=uuid4())
        assert miss["hits"] == []
    finally:
        reset_tenant_context(tokens)


@pytest.mark.asyncio
async def test_remember_rejects_sources_namespace(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.tools.core.memory.settings.data_dir", str(tmp_path))
    result = await memory_tools.remember("x", namespace="sources")
    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_remember_rejects_explicit_retrieved_trust(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.tools.core.memory.settings.data_dir", str(tmp_path))
    result = await memory_tools.remember("a quote from sources", trust="retrieved")
    assert result["status"] == "failed"
    ok = await memory_tools.remember("a quote from sources", trust="user")
    assert ok["status"] == "remembered"


@pytest.mark.asyncio
async def test_remember_postgres_does_not_fallback_to_json(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.tools.core.memory.settings.memory_backend", "postgres")
    monkeypatch.setattr("app.tools.core.memory.settings.data_dir", str(tmp_path))

    async def _fail_insert(*_a, **_k):
        return False

    monkeypatch.setattr("app.tools.core.memory_pg.pg_insert", _fail_insert)
    tokens = bind_tenant_context(work_root=str(tmp_path / "w"), work_id=uuid4())
    try:
        result = await memory_tools.remember("do not land in json")
        assert result["status"] == "failed"
        assert not list(tmp_path.rglob("memories.json"))
    finally:
        reset_tenant_context(tokens)


@pytest.mark.asyncio
async def test_memory_pg_noop_when_json_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.tools.core.memory_pg.settings.memory_backend", "json")
    wid = uuid4()
    assert await memory_pg.pg_insert({"id": "m1"}, work_id=wid) is False
    assert await memory_pg.pg_load(work_id=wid, namespace="prefs") is None
    assert await memory_pg.pg_delete(work_id=wid, memory_id="m1", query=None) == -1
