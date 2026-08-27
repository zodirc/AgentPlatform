"""Manifest-based writing delivery gate (no「已完成」while process L0 open)."""

from __future__ import annotations

from typing import Any

from app.writing.patch_budget import MAX_PATCHES_PER_PENALTY_KEY

_COMPLETION_MARKERS = (
    "已完成",
    "写完了",
    "定稿",
    "第一章已完成",
    "本章已完成",
    "完稿",
)


def manifest_delivery_blockers(manifest: dict[str, Any] | None) -> list[str]:
    if not isinstance(manifest, dict):
        return []
    drafts = manifest.get("section_drafts")
    if not isinstance(drafts, dict):
        return []
    blockers: list[str] = []
    for section_id, row in drafts.items():
        if not isinstance(row, dict):
            continue
        l0 = row.get("l0_hits")
        if isinstance(l0, list) and l0:
            blockers.append(f"{section_id}: L0 {', '.join(str(x) for x in l0)}")
        if row.get("length_short"):
            blockers.append(f"{section_id}: length_short")
    return blockers


def manifest_delivery_ready(manifest: dict[str, Any] | None) -> bool:
    return not manifest_delivery_blockers(manifest)


def read_turn_manifest(turn_id: object | None, session_id: object | None) -> dict[str, Any] | None:
    if turn_id is None:
        return None
    from app.tools.core.writing_tools import _read_manifest

    data = _read_manifest(turn_id, session_id=session_id)
    return data if isinstance(data, dict) else None


def delivery_hold_notice(blockers: list[str]) -> str:
    lines = "\n".join(f"- {item}" for item in blockers) or "- （未知）"
    return (
        "【交付门】本章尚未交付，禁止向用户宣称「已完成 / 定稿 / 第一章写完了」。\n"
        f"turn manifest 仍开：\n{lines}\n"
        "下一步：L0 岛 → propose_patch（每 penalty_key 本 Turn 至多 "
        f"{MAX_PATCHES_PER_PENALTY_KEY} 次生效 patch）；"
        "碎拍预算尽 → draft_section mode=rewrite_window 一次换整窗；"
        "L0 清且 length_short → mode=append 加厚。如实说明进度。"
    )


def claims_delivery_complete(text: str) -> bool:
    body = str(text or "")
    return any(marker in body for marker in _COMPLETION_MARKERS)


def finalize_writing_turn_summary(
    *,
    turn_id: object | None,
    session_id: object | None,
    summary: str,
) -> str:
    # No scenario_id branch: a non-writing turn has no process-L0 manifest, so blockers is empty.
    manifest = read_turn_manifest(turn_id, session_id)
    blockers = manifest_delivery_blockers(manifest)
    if not blockers:
        return summary
    notice = delivery_hold_notice(blockers)
    if claims_delivery_complete(summary):
        return notice
    base = str(summary or "").strip()
    if not base:
        return notice
    if notice in base:
        return base
    return f"{base}\n\n{notice}"


def export_blocked_by_manifest(manifest: dict[str, Any] | None) -> list[str]:
    return manifest_delivery_blockers(manifest)
