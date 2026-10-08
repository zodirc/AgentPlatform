"""本地断点、事件与评分的格式版本。只做向前迁移。"""

from __future__ import annotations

from app.writing_host.errors import ResumeIncompatible

CHECKPOINT_SCHEMA = 1
EVENT_SCHEMA = 1
EVAL_SCHEMA = 1
MEMORY_SCHEMA = 1
SIDECAR_SCHEMA = 1
EVENT_KEEP_TURNS = 32

SCHEMA_VERSIONS = {
    "checkpoint": CHECKPOINT_SCHEMA,
    "event": EVENT_SCHEMA,
    "evaluation": EVAL_SCHEMA,
    "memory": MEMORY_SCHEMA,
    "sidecar": SIDECAR_SCHEMA,
}


def migrate_checkpoint(data: dict) -> dict:
    """把旧断点升到当前格式。比当前新则拒绝。"""
    if not isinstance(data, dict):
        raise ResumeIncompatible(detail="checkpoint is not an object")
    version = int(data.get("schema_version") or 0)
    if version > CHECKPOINT_SCHEMA:
        raise ResumeIncompatible(detail=f"checkpoint schema {version}")
    if "state" not in data and data.get("turn_id"):
        return {
            "schema_version": CHECKPOINT_SCHEMA,
            "step_index": int(data.get("step_index") or data.get("step_count") or 0),
            "interrupt_payload": data.get("interrupt_payload"),
            "state": data,
        }
    if version < CHECKPOINT_SCHEMA:
        data = dict(data)
        data["schema_version"] = CHECKPOINT_SCHEMA
    return data


def migrate_memory(data: object) -> list:
    """旧文件是数组。比当前新的对象拒绝读取。"""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        raise ResumeIncompatible(detail="memory file is not an object")
    version = int(data.get("schema_version") or 0)
    if version > MEMORY_SCHEMA:
        raise ResumeIncompatible(detail=f"memory schema {version}")
    items = data.get("items")
    return list(items) if isinstance(items, list) else []


def migrate_sidecar(data: dict | None) -> dict:
    """侧车格式戳。缺文件视为第 0 版，可向前迁移。"""
    if not data:
        return {"schema_version": SIDECAR_SCHEMA}
    version = int(data.get("schema_version") or 0)
    if version > SIDECAR_SCHEMA:
        raise ResumeIncompatible(detail=f"sidecar schema {version}")
    return {"schema_version": SIDECAR_SCHEMA}
