"""Decision audit. The payload is the decision struct, never a quarantined body."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def append_security_log(payload: dict[str, Any]) -> None:
    """Durable line when no turn writer is bound. Failures stay in the process log."""
    import json
    from pathlib import Path

    from app.settings import settings

    path = Path(settings.data_dir) / "security" / "audit.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except OSError:
        logger.exception("security audit file write failed")


async def record_decision(
    *,
    state: Any,
    tool_name: str,
    arguments: dict[str, Any] | None,
    decision: str,
    reason: str,
    sink_class: str,
    window_taint: str,
    detector: str = "",
    approver_user_id: str = "",
) -> None:
    """Insert one security.decision event when a writer is bound. Failures are logged."""
    from app.policy.approval import POLICY_VERSION, canonical_args_hash

    from app.policy.scenario_policy import scenario_version

    payload = {
        "decision": decision,
        "reason": reason,
        "sink_class": sink_class,
        "window_taint": window_taint,
        "policy_version": POLICY_VERSION,
        "scenario_version": scenario_version(str(getattr(state, "scenario_id", "") or "")),
        "detector": detector,
        "approver_user_id": approver_user_id,
        "tool_name": tool_name,
        "args_hash": canonical_args_hash(arguments if isinstance(arguments, dict) else {}),
        "summary": reason[:200],
    }
    try:
        from app.ports import current_event_writer

        writer = current_event_writer()
    except Exception:
        writer = None
    try:
        from app.observability.metrics import metrics

        metrics.inc("security_decision_total", decision=decision, sink=sink_class)
    except Exception:
        pass
    if writer is None:
        append_security_log(payload)
        return
    try:
        await writer(event_type="security.decision", payload=payload)
    except Exception:
        logger.exception("security.decision write failed")
