"""Ops-eval thinking transcript on disk (not turn_events).

Eval Turns skip persisting ``turn.thinking.delta`` to Postgres; the same
text is appended here so a run can download reasoning on demand.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

_SIDECAR_REL = Path(".agent") / "thinking"


def thinking_sidecar_path(work_root: Path | str, turn_id: UUID | str) -> Path:
    return Path(work_root) / _SIDECAR_REL / f"{turn_id}.jsonl"


def sidecar_line(*, step_index: int, delta: str, ts: str | None = None) -> str:
    body = {
        "ts": ts or datetime.now(timezone.utc).isoformat(),
        "step_index": int(step_index),
        "delta": str(delta),
    }
    return json.dumps(body, ensure_ascii=False) + "\n"
