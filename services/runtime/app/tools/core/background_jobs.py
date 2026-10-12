"""``run_command(background=true)`` 的进程内任务表。

不新增工具名：用 ``job_id`` 读输出，用 ``kill`` 结束。
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

_JOBS: dict[str, dict[str, Any]] = {}


async def background_command(
    *,
    command: str,
    job_id: str,
    background: bool,
    kill: bool,
    cwd: Path,
    timeout_s: float,
    turn_id: object,
) -> dict[str, Any]:
    if job_id:
        job = _JOBS.get(job_id)
        if job is None:
            return {"error": "unknown job_id", "job_id": job_id, "status": "error"}
        task = job.get("task")
        if kill and isinstance(task, asyncio.Task) and not task.done():
            task.cancel()
            job["status"] = "cancelled"
        result = job.get("result")
        if isinstance(result, dict):
            return {**result, "job_id": job_id, "status": job.get("status") or result.get("status")}
        return {
            "job_id": job_id,
            "status": str(job.get("status") or "running"),
            "command": job.get("command") or command,
            "summary": "background command still running",
        }
    if not background:
        return {"error": "background or job_id required", "status": "error"}
    new_id = uuid.uuid4().hex[:12]
    job = {"command": command, "status": "running", "result": None, "task": None}
    _JOBS[new_id] = job

    async def _run() -> None:
        from app.tools.core.misc_tools import _make_cancel_checker
        from app.tools.core.shell import run_shell_command

        check_cancel = _make_cancel_checker(turn_id) if turn_id is not None else None
        try:
            result = await run_shell_command(
                command=command,
                cwd=cwd,
                timeout_s=timeout_s,
                check_cancel=check_cancel,
            )
        except asyncio.CancelledError:
            job["status"] = "cancelled"
            job["result"] = {
                "status": "cancelled",
                "command": command,
                "stdout": "",
                "stderr": "",
                "summary": "background command cancelled",
            }
            return
        job["result"] = result
        job["status"] = str(result.get("status") or "executed")

    job["task"] = asyncio.create_task(_run())
    return {
        "job_id": new_id,
        "status": "running",
        "command": command,
        "summary": f"background command started ({new_id})",
    }
