"""Ops-eval thinking 旁路落盘（不进 turn_events）。

Eval Turn 跳过把 ``turn.thinking.delta`` 写入 Postgres；同文追加到
``{work_root}/.agent/thinking/{turn_id}.jsonl``，便于按需下载推理轨迹。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

_SIDECAR_REL = Path(".agent") / "thinking"


def thinking_sidecar_path(work_root: Path | str, turn_id: UUID | str) -> Path:
    """拼 thinking sidecar 的绝对路径。

    参数:
        work_root: 工作区根。
        turn_id: Turn 主键。

    返回:
        ``.../.agent/thinking/{turn_id}.jsonl``。
    """
    return Path(work_root) / _SIDECAR_REL / f"{turn_id}.jsonl"


def sidecar_line(*, step_index: int, delta: str, ts: str | None = None) -> str:
    """序列化一行 JSONL（含换行），供追加写入 sidecar。

    参数:
        step_index: Engine 步骤序号。
        delta: thinking 增量文本。
        ts: 可选 ISO 时间；默认当前 UTC。

    返回:
        以 ``\\n`` 结尾的一行 JSON 字符串。
    """
    body = {
        "ts": ts or datetime.now(timezone.utc).isoformat(),
        "step_index": int(step_index),
        "delta": str(delta),
    }
    return json.dumps(body, ensure_ascii=False) + "\n"
