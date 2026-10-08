"""稿树上的断点、事件、评分与偏好。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from app.engine.checkpoint_codec import deserialize_state, serialize_state
from app.engine.state import TurnState
from app.writing_host.schema import (
    CHECKPOINT_SCHEMA,
    EVAL_SCHEMA,
    EVENT_KEEP_TURNS,
    EVENT_SCHEMA,
    SIDECAR_SCHEMA,
    migrate_checkpoint,
    migrate_sidecar,
)


class FileCheckpointStore:
    def __init__(self, work_root: Path) -> None:
        self._dir = Path(work_root) / ".agent" / "checkpoints"

    def path_for(self, turn_id: UUID | str) -> Path:
        return self._dir / f"{turn_id}.json"

    async def save(
        self,
        *,
        state: TurnState,
        step_index: int,
        interrupt_payload: dict[str, Any] | None = None,
    ) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": CHECKPOINT_SCHEMA,
            "step_index": int(step_index),
            "interrupt_payload": interrupt_payload,
            "state": serialize_state(state),
        }
        target = self.path_for(state.turn_id)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(target)

    def load(self, turn_id: str) -> tuple[TurnState, dict[str, Any] | None, int]:
        raw = json.loads(self.path_for(turn_id).read_text(encoding="utf-8"))
        data = migrate_checkpoint(raw)
        state = deserialize_state(data["state"])
        interrupt = data.get("interrupt_payload")
        if not isinstance(interrupt, dict):
            interrupt = None
        return state, interrupt, int(data.get("step_index") or 0)

    def list_turns(self) -> list[dict[str, Any]]:
        if not self._dir.is_dir():
            return []
        rows = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                data = migrate_checkpoint(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
            rows.append(
                {
                    "turn_id": path.stem,
                    "step_index": int(data.get("step_index") or 0),
                    "schema_version": int(data.get("schema_version") or 0),
                }
            )
        return rows


class FileEventLog:
    def __init__(self, work_root: Path, turn_id: str) -> None:
        self._path = Path(work_root) / ".agent" / "events" / f"{turn_id}.jsonl"

    async def append(self, record: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = dict(record)
        line.setdefault("schema_version", EVENT_SCHEMA)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        _prune_event_logs(self._path.parent)


class FileEvaluationStore:
    """评分只追加。``load_turn`` 返回空，宿主上拍晋升保持关闭。"""

    def __init__(self, work_root: Path) -> None:
        self._root = Path(work_root) / ".agent" / "evaluations"

    async def persist_fragment(self, **kwargs: Any) -> str | None:
        turn_id = kwargs.get("turn_id") or "none"
        path = self._root / f"{turn_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"schema_version": EVAL_SCHEMA, **{k: _jsonable(v) for k, v in kwargs.items()}}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return None

    async def load_turn(self, turn_id: UUID) -> list[dict[str, Any]]:
        del turn_id
        return []


class PlatformPrefsSource:
    async def load_account(self, owner_user_id) -> None:
        del owner_user_id
        return None


class NullSummaryStore:
    async def load(self, session_id) -> None:
        del session_id
        return None

    async def save(self, session_id, record) -> None:
        del session_id, record


def ensure_sidecar_format(work_root: Path) -> None:
    """写入侧车格式版本。比当前新则拒绝恢复。"""
    path = Path(work_root) / ".agent" / "work" / "format.json"
    current = None
    if path.is_file():
        current = json.loads(path.read_text(encoding="utf-8"))
    payload = migrate_sidecar(current)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or int((current or {}).get("schema_version") or 0) != SIDECAR_SCHEMA:
        path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def _prune_event_logs(directory: Path) -> None:
    files = sorted(directory.glob("*.jsonl"), key=lambda item: item.stat().st_mtime)
    overflow = len(files) - EVENT_KEEP_TURNS
    for path in files[: max(0, overflow)]:
        path.unlink(missing_ok=True)


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    return value
