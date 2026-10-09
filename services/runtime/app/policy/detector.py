"""Detector client. It holds no Turn state and can only tighten.

Observe mode records the signal and leaves the body and the matrix alone.
Enforce mode quarantines a high-confidence injection and may turn an allow
into require_approval or deny. A timeout marks the window external and still
returns the read.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)

CANARY = "[[HIGH_CONFIDENCE_INJECT]]"
ISOLATION_NOTICE = "内容因疑似注入被隔离，已通知用户"
DETECTOR_ID = "canary/1"


def _observe_detector(seconds: float, kind: str) -> None:
    try:
        from app.observability.metrics import metrics

        metrics.observe("detector_latency_seconds", seconds, kind=kind)
    except Exception:
        return


def injection_mode() -> str:
    mode = str(getattr(settings, "detector_injection_mode", "observe") or "observe")
    return "enforce" if mode.strip().lower() == "enforce" else "observe"


async def inspect_body(text: str) -> str:
    """allow, deny, or unavailable. Observe still returns deny for the signal."""
    url = str(getattr(settings, "detector_url", "") or "").strip()
    if not url:
        return "deny" if CANARY in (text or "") else "allow"
    timeout = max(0.05, float(getattr(settings, "detector_timeout_ms", 300) or 300) / 1000.0)
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url.rstrip("/") + "/inspect", json={"text": text})
            response.raise_for_status()
            data = response.json()
        _observe_detector(time.monotonic() - started, "inspect")
    except Exception:
        logger.info("detector unavailable; window will be treated as external")
        try:
            from app.observability.metrics import metrics

            metrics.inc("detector_unavailable_total")
        except Exception:
            pass
        return "unavailable"
    verdict = str((data or {}).get("verdict") or "allow")
    if verdict in {"allow", "deny", "require_approval"}:
        return verdict
    return "unavailable"


async def check_deviation(goal: str, arguments: dict[str, Any] | None) -> str:
    """S3/S4 check. No classifier means require_approval. allow cannot loosen."""
    url = str(getattr(settings, "detector_url", "") or "").strip()
    if not url:
        blob = str(arguments or "")
        if CANARY in blob:
            return "deny"
        # No classifier signal is "unsure", which can only tighten.
        return "require_approval"
    timeout = max(0.05, float(getattr(settings, "detector_timeout_ms", 300) or 300) / 1000.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url.rstrip("/") + "/deviation",
                json={"goal": (goal or "")[:2000], "arguments": arguments or {}},
            )
            response.raise_for_status()
            data = response.json()
    except Exception:
        return "unavailable"
    verdict = str((data or {}).get("verdict") or "require_approval")
    if verdict in {"allow", "deny", "require_approval"}:
        return verdict
    return "unavailable"


def tighten(decision: str, signal: str, *, mode: str) -> str:
    """Apply a detector signal. Observe and allow leave the decision unchanged."""
    if mode != "enforce":
        return decision
    if signal == "unavailable":
        if decision == "allow":
            return "require_approval"
        return decision
    if signal == "deny":
        return "deny"
    if signal == "require_approval" and decision == "allow":
        return "require_approval"
    return decision
