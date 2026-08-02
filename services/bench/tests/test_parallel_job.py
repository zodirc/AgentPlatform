"""Suite-level parallel execution for the Ops bench worker."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

BENCH_ROOT = Path(__file__).resolve().parents[1]
if str(BENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(BENCH_ROOT))

from app import main as bench_main  # noqa: E402


@pytest.fixture
def bench_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BENCH_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.delenv("BENCH_JOB_MAX_PARALLEL", raising=False)
    monkeypatch.setattr(bench_main, "_repo_root", lambda: tmp_path)
    bench_main._JOBS.clear()
    yield
    for job in list(bench_main._JOBS.values()):
        job.cancel_requested = True
        if job._task and not job._task.done():
            job._task.cancel()
    bench_main._JOBS.clear()


def _sleep_cmd(seconds: float, *, exit_code: int = 0) -> list[str]:
    return [
        sys.executable,
        "-c",
        (
            "import sys, time; "
            f"time.sleep({seconds}); "
            "print('[phase] done', flush=True); "
            f"sys.exit({exit_code})"
        ),
    ]


def test_job_max_parallel_defaults_to_target_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BENCH_JOB_MAX_PARALLEL", raising=False)
    assert bench_main._job_max_parallel(3) == 3
    monkeypatch.setenv("BENCH_JOB_MAX_PARALLEL", "1")
    assert bench_main._job_max_parallel(3) == 1
    monkeypatch.setenv("BENCH_JOB_MAX_PARALLEL", "99")
    assert bench_main._job_max_parallel(2) == 2


@pytest.mark.asyncio
async def test_targets_run_in_parallel_wall_clock(
    bench_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_cmd(target: str, **_kwargs: object) -> list[str]:
        return _sleep_cmd(0.45)

    monkeypatch.setattr(bench_main, "_cmd_for_target", fake_cmd)
    job = bench_main.Job(id="j-parallel", targets=["context", "coding_infer"])
    bench_main._JOBS[job.id] = job

    t0 = time.monotonic()
    await bench_main._run_job(job.id)
    elapsed = time.monotonic() - t0

    assert job.status == "completed"
    assert elapsed < 0.85  # serial would be ~0.9s+
    assert any("parallel=2" in line for line in job.lines)
    assert any("[bench] target_phase context" in line for line in job.lines)
    assert any("[bench] target_phase coding_infer" in line for line in job.lines)


@pytest.mark.asyncio
async def test_max_parallel_one_is_serial(
    bench_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BENCH_JOB_MAX_PARALLEL", "1")

    def fake_cmd(target: str, **_kwargs: object) -> list[str]:
        return _sleep_cmd(0.35)

    monkeypatch.setattr(bench_main, "_cmd_for_target", fake_cmd)
    job = bench_main.Job(id="j-serial", targets=["context", "coding_infer"])
    bench_main._JOBS[job.id] = job

    t0 = time.monotonic()
    await bench_main._run_job(job.id)
    elapsed = time.monotonic() - t0

    assert job.status == "completed"
    assert elapsed >= 0.65


@pytest.mark.asyncio
async def test_fail_waits_for_siblings(
    bench_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_cmd(target: str, **_kwargs: object) -> list[str]:
        if target == "context":
            return _sleep_cmd(0.05, exit_code=1)
        return _sleep_cmd(0.4, exit_code=0)

    monkeypatch.setattr(bench_main, "_cmd_for_target", fake_cmd)
    job = bench_main.Job(id="j-fail", targets=["context", "coding_infer"])
    bench_main._JOBS[job.id] = job

    t0 = time.monotonic()
    await bench_main._run_job(job.id)
    elapsed = time.monotonic() - t0

    assert job.status == "failed"
    assert "target_context_exit_1" in (job.error or "")
    assert elapsed >= 0.35  # waited for coding_infer
    assert any("target_end coding_infer status=pass" in line for line in job.lines)
    assert any("target_end context status=fail" in line for line in job.lines)


@pytest.mark.asyncio
async def test_cancel_kills_all_targets(
    bench_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_cmd(target: str, **_kwargs: object) -> list[str]:
        return _sleep_cmd(8.0)

    monkeypatch.setattr(bench_main, "_cmd_for_target", fake_cmd)
    job = bench_main.Job(id="j-cancel", targets=["context", "coding_infer"])
    bench_main._JOBS[job.id] = job

    task = asyncio.create_task(bench_main._run_job(job.id))
    # Wait until both procs are live.
    for _ in range(50):
        if len(job._procs) >= 2:
            break
        await asyncio.sleep(0.05)
    assert len(job._procs) >= 2

    job.cancel_requested = True
    await bench_main._kill_all(job)
    await asyncio.wait_for(task, timeout=5.0)

    assert job.status == "cancelled"
    assert all(p.returncode is not None for p in list(job._procs)) or not job._procs
    assert any("status=cancelled" in line for line in job.lines)
