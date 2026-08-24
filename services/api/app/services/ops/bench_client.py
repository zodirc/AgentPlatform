"""Ops Bench worker 的 HTTP 客户端（非 agent runtime）。

English: HTTP client for the dedicated Ops Bench worker (not agent runtime).
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import httpx


def bench_base_url() -> str:
    """读取 ``BENCH_URL`` 并去掉尾部斜杠。

    English: Return normalized BENCH_URL without trailing slash.

    返回:
        base URL 字符串；未配置时为 ``""``。
    """
    return (os.environ.get("BENCH_URL") or "").strip().rstrip("/")


def bench_enabled() -> bool:
    """是否配置了 bench worker 地址。

    English: True when BENCH_URL is set.

    返回:
        ``bool(bench_base_url())``。
    """
    return bool(bench_base_url())


def _headers() -> dict[str, str]:
    token = (os.environ.get("INTERNAL_SERVICE_TOKEN") or "").strip()
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def fetch_caps() -> dict[str, Any]:
    """拉取 bench worker ``/v1/caps``（sentence_transformers / retrieval_prod 等）。

    English: GET /v1/caps from the bench worker; failures return an error dict.

    返回:
        caps JSON；不可达或 HTTP 错误时含 ``error`` 键（不抛异常，避免 500 meta）。
    """
    base = bench_base_url()
    if not base:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base}/v1/caps", headers=_headers())
            if resp.status_code >= 400:
                return {"error": f"bench_caps_http_{resp.status_code}"}
            return resp.json()
    except Exception as exc:  # noqa: BLE001 — unreachable / reset must not 500 meta
        return {"error": f"bench_unreachable:{type(exc).__name__}"}


async def health() -> dict[str, Any]:
    """探测 bench worker ``/health``。

    English: GET /health; raises on HTTP error when BENCH_URL is set.

    返回:
        health JSON（通常含 ``ok``、embedding 配置等）。

    异常:
        RuntimeError 语义由 ``raise_for_status``；未配置时返回 ``{ok: False, error: ...}``。
    """
    base = bench_base_url()
    if not base:
        return {"ok": False, "error": "BENCH_URL unset"}
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{base}/health")
        resp.raise_for_status()
        return resp.json()


async def probe_model(model: dict[str, Any]) -> dict[str, Any]:
    """Ask the bench worker to ping the configured chat endpoint."""
    base = bench_base_url()
    if not base:
        raise RuntimeError("BENCH_URL unset — start the bench worker")
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(
            f"{base}/v1/model/probe",
            headers=_headers(),
            json=model,
        )
        if resp.status_code >= 400:
            raise RuntimeError(resp.text or f"bench_probe_http_{resp.status_code}")
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("bench_probe_invalid_response")
        return data


async def start_job(
    *,
    targets: list[str],
    context_dry: bool,
    coding_skip_api: bool,
    coding_tier: str,
    coding_n_instances: int | None,
    coding_harness: bool,
    retrieval_prod: bool,
    model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """在 bench worker 上启动 Official L1 评测 job。

    English: POST /v1/jobs to start an official bench job with suite targets and flags.

    参数:
        targets: 套件目标名列表（context/coding/retrieval 等）。
        context_dry / coding_skip_api / coding_tier / coding_n_instances: 各套件旋钮。
        coding_harness: 是否在 infer 后跑 SWE Docker harness。
        retrieval_prod: 是否用生产检索栈。
        model: 可选 chat 模型配置（probe/start 用）。

    返回:
        job 创建响应（含 ``job_id`` 等）。

    异常:
        RuntimeError: ``BENCH_URL`` 未设或 HTTP ≥400。
    """
    base = bench_base_url()
    if not base:
        raise RuntimeError("BENCH_URL unset — start the bench worker")
    payload: dict[str, Any] = {
        "targets": targets,
        "context_dry": context_dry,
        "coding_skip_api": coding_skip_api,
        "coding_tier": coding_tier,
        "coding_n_instances": coding_n_instances,
        "coding_harness": coding_harness,
        "retrieval_prod": retrieval_prod,
    }
    if model:
        payload["model"] = model
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{base}/v1/jobs",
            headers=_headers(),
            json=payload,
        )
        if resp.status_code >= 400:
            raise RuntimeError(resp.text or f"bench_start_http_{resp.status_code}")
        return resp.json()


async def stop_job(job_id: str) -> dict[str, Any]:
    """请求 bench worker 停止指定 job。

    English: POST /v1/jobs/{id}/stop.

    参数:
        job_id: bench job id。

    返回:
        stop 响应 JSON。

    异常:
        RuntimeError: HTTP ≥400。
    """
    base = bench_base_url()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{base}/v1/jobs/{job_id}/stop",
            headers=_headers(),
        )
        if resp.status_code >= 400:
            raise RuntimeError(resp.text or f"bench_stop_http_{resp.status_code}")
        return resp.json()


async def stream_job_lines(job_id: str) -> AsyncIterator[str]:
    """Yield log lines from bench SSE (data: …).

    Heartbeat lines yield ``\"\"`` so callers can poll cancel without waiting on
    the next real log line (indexing can be silent for a long time).
    """
    base = bench_base_url()
    timeout = httpx.Timeout(None, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "GET",
            f"{base}/v1/jobs/{job_id}/stream",
            headers=_headers(),
        ) as resp:
            resp.raise_for_status()
            async for raw in resp.aiter_lines():
                if not raw:
                    yield ""
                    continue
                if raw.startswith(":"):
                    yield ""
                    continue
                if raw.startswith("data:"):
                    yield raw[5:].lstrip()
