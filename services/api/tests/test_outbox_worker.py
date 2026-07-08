from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.services.outbox import claim_jobs, enqueue_job, enqueue_turn_jobs, mark_done


@pytest.mark.asyncio
async def test_enqueue_and_claim_job(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = uuid4()
    captured: list[tuple] = []

    async def fake_execute(query: str, *args) -> None:
        captured.append((query.strip().split("\n")[0], args))

    pool = AsyncMock()
    pool.execute = fake_execute
    monkeypatch.setattr("app.services.outbox.get_pool", AsyncMock(return_value=pool))

    returned = await enqueue_job("sources.index_sync", {"turn_id": str(uuid4())})
    assert isinstance(returned, UUID)
    assert captured


@pytest.mark.asyncio
async def test_enqueue_turn_jobs_for_writing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    async def fake_enqueue(job_type: str, payload: dict, **kwargs) -> UUID:
        calls.append((job_type, payload))
        return uuid4()

    monkeypatch.setattr("app.services.outbox.enqueue_job", fake_enqueue)
    turn_id = uuid4()
    await enqueue_turn_jobs(turn_id=turn_id, scenario_id="writing")
    job_types = {name for name, _ in calls}
    assert "sources.index_sync" in job_types
    assert "projection.refresh" in job_types
    assert "session.summary" in job_types


@pytest.mark.asyncio
async def test_claim_jobs_returns_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = uuid4()
    row = {
        "id": job_id,
        "job_type": "sources.index_sync",
        "payload": json.dumps({"turn_id": str(uuid4())}),
        "attempts": 0,
        "max_attempts": 5,
    }

    class _AsyncCM:
        def __init__(self, obj: object) -> None:
            self._obj = obj

        async def __aenter__(self):
            return self._obj

        async def __aexit__(self, *args) -> None:
            return None

    class FakeConn:
        async def fetch(self, query: str, limit: int):
            return [row]

        async def execute(self, query: str, ids: list[UUID]) -> None:
            return None

        def transaction(self) -> _AsyncCM:
            return _AsyncCM(self)

    class FakePool:
        def acquire(self) -> _AsyncCM:
            return _AsyncCM(FakeConn())

    pool = FakePool()
    monkeypatch.setattr("app.services.outbox.get_pool", AsyncMock(return_value=pool))

    jobs = await claim_jobs(limit=1)
    assert jobs
    assert jobs[0]["job_type"] == "sources.index_sync"
    assert isinstance(jobs[0]["payload"], dict)


@pytest.mark.asyncio
async def test_mark_done_updates_status(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple] = []

    async def fake_execute(query: str, job_id: UUID) -> None:
        captured.append((query, job_id))

    pool = AsyncMock()
    pool.execute = fake_execute
    monkeypatch.setattr("app.services.outbox.get_pool", AsyncMock(return_value=pool))

    job_id = uuid4()
    await mark_done(job_id)
    assert captured
    assert captured[0][1] == job_id
