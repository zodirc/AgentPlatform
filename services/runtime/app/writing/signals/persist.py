"""评分持久化。服务器走 Postgres 端口，宿主可绑定只写文件的实现。"""

from __future__ import annotations

from typing import Any
from uuid import UUID


async def persist_fragment_evaluation(
    *,
    owner_user_id: UUID,
    work_id: UUID | None,
    session_id: UUID | None,
    turn_id: UUID | None,
    section_id: str,
    fragment_declared: str,
    fragment_detected: str,
    writing_signals: dict[str, Any],
    text: str,
    feature_schema_id: str = "",
    signature: dict[str, Any] | None = None,
    prototype_scope: str = "",
    nearest_exemplar_slug: str | None = None,
) -> str | None:
    """写 writing_fragment_evaluations，或宿主绑定的文件存储。"""
    from app.ports import evaluation_store

    return await evaluation_store().persist_fragment(
        owner_user_id=owner_user_id,
        work_id=work_id,
        session_id=session_id,
        turn_id=turn_id,
        section_id=section_id,
        fragment_declared=fragment_declared,
        fragment_detected=fragment_detected,
        writing_signals=writing_signals,
        text=text,
        feature_schema_id=feature_schema_id,
        signature=signature,
        prototype_scope=prototype_scope,
        nearest_exemplar_slug=nearest_exemplar_slug,
    )
