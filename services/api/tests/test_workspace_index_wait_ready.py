"""Tests for L1 ephemeral AST wait-ready gate."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_await_workspace_index_ready_returns_ready(monkeypatch) -> None:
    from app.services.ops.l1 import turn_driver as td

    calls: list[dict] = []

    async def fake_status(*, enqueue=False, tenant=None, timeout=15.0):  # noqa: ANN001
        del enqueue, tenant, timeout
        return {
            "status": "ready",
            "files_done": 10,
            "files_total": 10,
            "generation": 1,
            "ephemeral": True,
        }

    async def fake_emit(cb, kind, **extra):  # noqa: ANN001
        del cb, kind
        calls.append(extra)

    monkeypatch.setattr(
        "app.services.admin.workspace.ast_index_status", fake_status
    )
    monkeypatch.setattr(td, "_emit", fake_emit)

    out = await td._await_workspace_index_ready(
        iid="astropy__astropy-12907",
        tenant={"work_id": "w1", "work_root": "/tmp", "owner_user_id": "u"},
        on_progress=None,
        timeout_s=5.0,
        poll_s=0.01,
    )
    assert out == "ready"
    assert any("status=ready" in str(c.get("message", "")) for c in calls)


@pytest.mark.asyncio
async def test_enqueue_ephemeral_wait_ready_false_spawns_watch(monkeypatch) -> None:
    from app.services.ops.l1 import turn_driver as td

    created: list[str] = []

    async def fake_rebuild(*, memory_only=False, tenant=None):  # noqa: ANN001
        del memory_only, tenant
        return {"accepted": True}

    async def fake_emit(cb, kind, **extra):  # noqa: ANN001
        del cb, kind, extra

    def fake_create_task(coro, *, name=None):  # noqa: ANN001
        created.append(str(name or ""))
        coro.close()
        return None

    monkeypatch.setattr(
        "app.services.admin.workspace.ast_index_rebuild", fake_rebuild
    )
    monkeypatch.setattr(td, "_emit", fake_emit)
    monkeypatch.setattr(td.asyncio, "create_task", fake_create_task)

    out = await td._enqueue_ephemeral_workspace_index(
        iid="x",
        tenant={"work_id": "abcd1234", "work_root": "/tmp", "owner_user_id": "u"},
        on_progress=None,
        wait_ready=False,
    )
    assert out["accepted"] is True
    assert out["wait_status"] is None
    assert any(n.startswith("ast-watch-") for n in created)


@pytest.mark.asyncio
async def test_enqueue_ephemeral_wait_ready_awaits(monkeypatch) -> None:
    from app.services.ops.l1 import turn_driver as td

    async def fake_rebuild(*, memory_only=False, tenant=None):  # noqa: ANN001
        del memory_only, tenant
        return {"accepted": True}

    async def fake_await(**kwargs):  # noqa: ANN001
        del kwargs
        return "ready"

    async def fake_emit(cb, kind, **extra):  # noqa: ANN001
        del cb, kind, extra

    monkeypatch.setattr(
        "app.services.admin.workspace.ast_index_rebuild", fake_rebuild
    )
    monkeypatch.setattr(td, "_await_workspace_index_ready", fake_await)
    monkeypatch.setattr(td, "_emit", fake_emit)

    out = await td._enqueue_ephemeral_workspace_index(
        iid="x",
        tenant={"work_id": "abcd1234", "work_root": "/tmp", "owner_user_id": "u"},
        on_progress=None,
        wait_ready=True,
        wait_timeout_s=60.0,
    )
    assert out == {"accepted": True, "wait_status": "ready"}
