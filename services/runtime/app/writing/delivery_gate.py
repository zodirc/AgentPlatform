"""Manifest-based writing delivery gate (no「已完成」while process L0 open)."""

from __future__ import annotations

from typing import Any

from app.writing.patch_budget import MAX_PATCHES_PER_PENALTY_KEY

_COMPLETION_SOFTEN = (
    ("第一章已完成", "第一章已保存"),
    ("本章已完成", "本章已保存"),
    ("已完成", "已保存"),
    ("写完了", "已落盘"),
    ("定稿", "已保存"),
    ("完稿", "已落盘"),
)
_HOLD_MARK = "【交付门】"


def _row_book_scope(row: dict[str, Any]) -> str:
    from app.writing.book_scope import normalize_book_scope

    raw = row.get("book_scope")
    if raw:
        return normalize_book_scope(str(raw))
    return ""


def _manifest_book_scope(manifest: dict[str, Any]) -> str:
    from app.writing.book_scope import normalize_book_scope

    top = manifest.get("book_scope")
    if top:
        return normalize_book_scope(str(top))
    drafts = manifest.get("section_drafts")
    if isinstance(drafts, dict):
        for row in drafts.values():
            if isinstance(row, dict) and row.get("book_scope"):
                return normalize_book_scope(str(row.get("book_scope")))
    return "single"


def manifest_book_scope(manifest: dict[str, Any] | None) -> str:
    if not isinstance(manifest, dict):
        return "single"
    return _manifest_book_scope(manifest)


def manifest_delivery_blockers(manifest: dict[str, Any] | None) -> list[str]:
    """交卷门。短篇/单篇：L0 + 篇幅。长篇：只挡本章几乎没写（职务没做），不挡「全书没写完」。"""
    if not isinstance(manifest, dict):
        return []
    drafts = manifest.get("section_drafts")
    if not isinstance(drafts, dict):
        return []
    blockers: list[str] = []
    for section_id, row in drafts.items():
        if not isinstance(row, dict):
            continue
        scope = _row_book_scope(row) or _manifest_book_scope(manifest)
        if scope == "long":
            vis = 0
            try:
                vis = int(row.get("visible_chars") or 0)
            except (TypeError, ValueError):
                vis = 0
            # 800：成稿加厚门槛。写过一场就让本章落盘；配额未满只是 tool_result 提示 append。
            if row.get("length_short") and vis < 800:
                blockers.append(f"{section_id}: length_short")
            continue
        if row.get("length_short"):
            blockers.append(f"{section_id}: length_short")
        l0 = row.get("l0_hits")
        if isinstance(l0, list) and l0:
            blockers.append(f"{section_id}: L0 {', '.join(str(x) for x in l0)}")
    return blockers


def manifest_delivery_ready(manifest: dict[str, Any] | None) -> bool:
    return not manifest_delivery_blockers(manifest)


def read_turn_manifest(turn_id: object | None, session_id: object | None) -> dict[str, Any] | None:
    if turn_id is None:
        return None
    from app.tools.core.writing_tools import _read_manifest

    data = _read_manifest(turn_id, session_id=session_id)
    return data if isinstance(data, dict) else None


def delivery_hold_notice(blockers: list[str], *, book_scope: str = "single") -> str:
    lines = "\n".join(f"- {item}" for item in blockers) or "- （未知）"
    if book_scope == "long":
        return (
            "【交付门】这一章几乎还没写，不能把本章当落盘完成。\n"
            f"turn manifest 仍开：\n{lines}\n"
            "长篇本 Turn 只交一章：先把这场写出来；配额未满可以 mode=append 加厚，"
            "不要把「全书没写完」当成失败。"
        )
    return (
        "【交付门】本章尚未交付，禁止向用户宣称「已完成 / 定稿」。\n"
        f"turn manifest 仍开：\n{lines}\n"
        "下一步：L0 岛 → propose_patch（每 penalty_key 本 Turn 至多 "
        f"{MAX_PATCHES_PER_PENALTY_KEY} 次生效 patch）；"
        "碎拍预算尽 → draft_section mode=rewrite_window 一次换整窗；"
        "L0 清且 length_short → mode=append 加厚。如实说明进度。"
    )


def strip_delivery_playbook(text: str) -> str:
    """从摘要里剥掉交付门说明书，留给 compact 的应是作品状态。"""
    body = str(text or "")
    idx = body.find(_HOLD_MARK)
    if idx >= 0:
        body = body[:idx]
    return body.strip()


def looks_like_delivery_playbook(text: str) -> bool:
    body = str(text or "")
    if _HOLD_MARK in body:
        return True
    return "禁止向用户宣称" in body or "writing_delivery_hold" in body


def manuscript_preview_for_compact(
    *,
    max_chars: int = 220,
    workspace_root: Any = None,
) -> str:
    """稿面末尾一小段，给 compact 当 last_output_preview。"""
    from pathlib import Path

    from app.settings import settings
    from app.writing.manuscript import load_manuscript_doc

    root = Path(workspace_root or settings.workspace_root).resolve()
    doc, _rel = load_manuscript_doc(root)
    body = str(doc or "").strip()
    if not body:
        return ""
    lines = [ln for ln in body.splitlines() if not ln.startswith("#")]
    blob = "\n".join(lines).strip() or body
    if len(blob) <= max_chars:
        return blob
    return blob[-max_chars:]


def _soften_completion_claim(text: str) -> str:
    out = str(text or "")
    for old, new in _COMPLETION_SOFTEN:
        out = out.replace(old, new)
    return out


def claims_delivery_complete(text: str) -> bool:
    body = str(text or "")
    return any(old in body for old, _new in _COMPLETION_SOFTEN)


def finalize_writing_turn_summary(
    *,
    turn_id: object | None,
    session_id: object | None,
    summary: str,
) -> str:
    # No scenario_id branch: a non-writing turn has no process-L0 manifest, so blockers is empty.
    manifest = read_turn_manifest(turn_id, session_id)
    blockers = manifest_delivery_blockers(manifest)
    base = str(summary or "").strip()
    if not blockers:
        return base
    scope = manifest_book_scope(manifest) if isinstance(manifest, dict) else "single"
    notice = delivery_hold_notice(blockers, book_scope=scope)
    if claims_delivery_complete(base):
        base = _soften_completion_claim(base)
    if not base:
        return notice
    if notice in base:
        return base
    return f"{base}\n\n{notice}"


def export_blocked_by_manifest(manifest: dict[str, Any] | None) -> list[str]:
    return manifest_delivery_blockers(manifest)
