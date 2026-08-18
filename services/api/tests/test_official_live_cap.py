from __future__ import annotations

import pytest

from app.services.ops import official_runner as runner


@pytest.mark.asyncio
async def test_forget_live_runs_drops_finished() -> None:
    runner._RUNS.clear()
    live = runner.OfficialLiveRun(id="live-1", status="running")
    done = runner.OfficialLiveRun(id="done-1", status="completed")
    runner._RUNS[live.id] = live
    runner._RUNS[done.id] = done
    n = await runner.forget_live_runs()
    assert n == 1
    assert live.id in runner._RUNS
    assert done.id not in runner._RUNS
    runner._RUNS.clear()


def test_evict_finished_keeps_cap() -> None:
    runner._RUNS.clear()
    for i in range(25):
        rid = f"r{i:02d}"
        runner._RUNS[rid] = runner.OfficialLiveRun(
            id=rid, status="completed", created_at=f"2026-08-01T00:{i:02d}:00+00:00"
        )
    runner._RUNS["active"] = runner.OfficialLiveRun(id="active", status="running")
    runner._evict_finished_unlocked()
    assert "active" in runner._RUNS
    finished = [r for r in runner._RUNS.values() if r.status == "completed"]
    assert len(finished) == runner._MAX_FINISHED_LIVE
    runner._RUNS.clear()
