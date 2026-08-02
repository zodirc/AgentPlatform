"""Trigger L1 (agent-path) official runs via Ops API (product Turn path)."""

from __future__ import annotations

import json
import os
import time
from typing import Any


def _ops_base() -> str:
    return (
        os.environ.get("BENCH_OPS_BASE")
        or os.environ.get("OPS_BASE_URL")
        or "http://localhost"
    ).rstrip("/")


def _ops_secret() -> str:
    secret = (os.environ.get("OPS_TEST_SECRET") or "").strip()
    if not secret:
        raise SystemExit(
            "L1 agent-path needs OPS_TEST_SECRET in the environment "
            "(same secret as /ops/<secret>/official)."
        )
    return secret


def start_and_wait(
    targets: list[str],
    *,
    model: dict[str, Any] | None = None,
    coding_tier: str = "n25",
    coding_n_instances: int | None = None,
    context_limit: int = 0,
    retrieval_query_limit: int = 0,
    poll_s: float = 2.0,
    timeout_s: float = 86_400.0,
) -> dict[str, Any]:
    """POST /api/v1/ops/official/start with eval_path=agent and poll until terminal."""
    try:
        import httpx
    except ImportError as exc:
        raise SystemExit(
            "L1 ops client needs httpx. pip install -r eval/official/requirements.txt"
        ) from exc

    secret = _ops_secret()
    base = _ops_base()
    headers = {"Authorization": f"Bearer {secret}"}
    body: dict[str, Any] = {
        "targets": targets,
        "eval_path": "agent",
        "context_dry": False,
        "coding_skip_api": False,
        "coding_tier": coding_tier,
        "coding_harness": False,
        "retrieval_prod": True,
        "context_limit": context_limit,
        "retrieval_query_limit": retrieval_query_limit,
        "force": True,
    }
    if coding_n_instances is not None:
        body["coding_n_instances"] = coding_n_instances
    if model and model.get("api_key"):
        body["model"] = model

    url = f"{base}/api/v1/ops/official/runs"
    with httpx.Client(timeout=60.0, headers=headers) as client:
        resp = client.post(url, json=body)
        resp.raise_for_status()
        run = resp.json()
        run_id = str(run.get("id") or "")
        if not run_id:
            raise SystemExit(f"ops start missing id: {run}")

        print(json.dumps({"started": run_id, "eval_path": "agent", "targets": targets}, indent=2))
        deadline = time.monotonic() + timeout_s
        last_log = 0
        while time.monotonic() < deadline:
            st = client.get(f"{base}/api/v1/ops/official/runs/{run_id}")
            st.raise_for_status()
            data = st.json()
            status = str(data.get("status") or "")
            logs = data.get("logs") or []
            if len(logs) > last_log:
                for item in logs[last_log:]:
                    msg = item.get("message") if isinstance(item, dict) else item
                    print(f"[L1] {msg}", flush=True)
                last_log = len(logs)
            if status in {"completed", "failed", "cancelled"}:
                print(json.dumps({"finished": run_id, "status": status}, indent=2))
                return data
            time.sleep(poll_s)
    raise SystemExit(f"L1 run timed out: {run_id}")


def model_from_env() -> dict[str, Any] | None:
    key = (
        os.environ.get("BENCH_MODEL_API_KEY")
        or os.environ.get("MODEL_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()
    if not key:
        return None
    return {
        "provider": (os.environ.get("BENCH_MODEL_PROVIDER") or "openai").strip(),
        "model_name": (
            os.environ.get("BENCH_MODEL_NAME") or os.environ.get("MODEL_NAME") or "model"
        ).strip(),
        "api_key": key,
        "base_url": (os.environ.get("BENCH_MODEL_BASE_URL") or "").strip() or None,
    }
