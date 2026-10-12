"""运行中的用户插话。与审批共用 run_commands，在下一步边界追加到同一 Turn。"""

from __future__ import annotations

from collections import defaultdict

_pending: dict[str, list[str]] = defaultdict(list)


def push_steer(run_id: object, text: str) -> None:
    message = (text or "").strip()
    if not message:
        return
    _pending[str(run_id)].append(message[:8000])


def drain_steers(run_id: object) -> list[str]:
    return _pending.pop(str(run_id), [])
