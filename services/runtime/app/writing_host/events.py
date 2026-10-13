"""本地接头事件：契约信封，先落盘再回调。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.contracts.event_validation import validate_event_payload
from app.writing_host.schema import EVENT_SCHEMA

_COMPLETED_REASONS = {
    "final",
    "max_steps",
    "budget_exceeded",
    "local_response",
    "plan_awaiting_consent",
    "opening_ponds_awaiting_choice",
    "opening_ponds_retry_exhausted",
    "retcon_awaiting_consent",
    "outline_awaiting_direction",
}

_FAILED_REASONS = {
    "fatal_error",
    "model_timeout",
    "step_timeout",
    "schema_validation_error",
    "approval_resume_timeout",
    "approval_state_lost",
    "budget_exceeded",
    "runner_restart",
    "runner_lost",
    "db_timeout",
    "start_timeout",
}


@dataclass
class EventEnvelope:
    type: str
    payload: dict[str, Any]
    event_id: str
    stream_id: str
    turn_id: str
    run_id: str
    trace_id: str
    sequence: int
    step_index: int
    ts: str
    live: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "stream_id": self.stream_id,
            "sequence": self.sequence,
            "type": self.type,
            "turn_id": self.turn_id,
            "run_id": self.run_id,
            "step_index": self.step_index,
            "trace_id": self.trace_id,
            "ts": self.ts,
            "payload": self.payload,
            "live": self.live,
        }


class TurnEventLog:
    """一个回合一份 jsonl。``sequence`` 是行号，从 1 起。"""

    def __init__(self, work_root: Path, turn_id: str) -> None:
        self.turn_id = turn_id
        self.path = Path(work_root) / ".agent" / "events" / f"{turn_id}.jsonl"
        self.sequence = _existing_lines(self.path)

    def append(self, envelope: EventEnvelope) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = envelope.as_dict()
        line["schema_version"] = EVENT_SCHEMA
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        self.sequence = envelope.sequence


def read_events(work_root: Path, turn_id: str, after_sequence: int = 0) -> list[EventEnvelope]:
    path = Path(work_root) / ".agent" / "events" / f"{turn_id}.jsonl"
    if not path.is_file():
        return []
    found: list[EventEnvelope] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        data = json.loads(raw)
        if "type" not in data or "sequence" not in data:
            continue
        sequence = int(data["sequence"])
        if sequence <= int(after_sequence):
            continue
        found.append(_envelope_from_dict(data))
    return found


def make_envelope(
    *,
    event_type: str,
    payload: dict[str, Any],
    turn_id: str,
    run_id: str,
    trace_id: str,
    sequence: int,
    step_index: int,
) -> EventEnvelope:
    body = dict(payload)
    if event_type not in {"turn.token", "tool.delta", "turn.thinking.delta", "section.draft.delta"}:
        validate_event_payload(event_type, body)
    return EventEnvelope(
        type=event_type,
        payload=body,
        event_id=str(uuid4()),
        stream_id=turn_id,
        turn_id=turn_id,
        run_id=run_id,
        trace_id=trace_id,
        sequence=sequence,
        step_index=int(step_index),
        ts=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        live=False,
    )


def completed_payload(state: Any, summary: str) -> dict[str, Any]:
    reason = str(getattr(state, "termination_reason", "") or "final")
    if reason not in _COMPLETED_REASONS:
        reason = "final"
    usage = getattr(state, "usage", None)
    token_usage = {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }
    return {
        "summary": (summary or "")[:4096],
        "termination_reason": reason,
        "step_count": int(getattr(state, "step_count", 0) or 0),
        "delivery_status": "ok",
        "token_usage": token_usage,
        "post_turn_jobs": [],
    }


def failed_payload(*, termination_reason: str, message: str, error_kind: str) -> dict[str, Any]:
    reason = termination_reason if termination_reason in _FAILED_REASONS else "fatal_error"
    return {
        "termination_reason": reason,
        "message": (message or "")[:1024],
        "error_kind": error_kind[:64],
    }


def publish(
    log: TurnEventLog,
    emit: Callable[[EventEnvelope], None],
    *,
    event_type: str,
    payload: dict[str, Any],
    turn_id: str,
    run_id: str,
    trace_id: str,
    step_index: int,
) -> EventEnvelope:
    envelope = make_envelope(
        event_type=event_type,
        payload=payload,
        turn_id=turn_id,
        run_id=run_id,
        trace_id=trace_id,
        sequence=log.sequence + 1,
        step_index=step_index,
    )
    log.append(envelope)
    emit(envelope)
    return envelope


def _existing_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    count = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            count += 1
    return count


def _envelope_from_dict(data: dict[str, Any]) -> EventEnvelope:
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    return EventEnvelope(
        type=str(data.get("type") or ""),
        payload=payload,
        event_id=str(data.get("event_id") or ""),
        stream_id=str(data.get("stream_id") or data.get("turn_id") or ""),
        turn_id=str(data.get("turn_id") or ""),
        run_id=str(data.get("run_id") or ""),
        trace_id=str(data.get("trace_id") or ""),
        sequence=int(data.get("sequence") or 0),
        step_index=int(data.get("step_index") or 0),
        ts=str(data.get("ts") or ""),
        live=bool(data.get("live") or False),
    )
