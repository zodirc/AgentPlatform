"""写作场景工具：分章草稿、大纲、计划与 turn manifest 管理。

草稿默认写入可见 ``drafts/``；历史与 manifest 在 ``.agent/work/`` 下。
``draft_section`` 支持 monofile/sections 两种 layout、occupy 归档与 writing_signals；
``update_plan``/``update_outline`` 服务规划阶段与用户确认流程。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.settings import settings
from app.tools.core.paths import _resolve_path, workspace_not_writable_error
from app.writing.hinge import hinge_fields
from app.writing.lore import lore_fields
from app.writing.opening import opening_fields
from app.writing.outline_arc import outline_arc_fields
from app.writing.staccato import staccato_fields
from app.writing.text_metrics import draft_length_fields, outline_thin_fields

_LAST_PLAN_SIG: dict[str, tuple[tuple[str, str, str], ...]] = {}


def _mkdir_parent(target: Path, rel_path: str) -> dict[str, Any] | None:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        return workspace_not_writable_error(rel_path, exc)
    return None


def _plan_signature(items: list[dict[str, str]]) -> tuple[tuple[str, str, str], ...]:
    return tuple((row["id"], row["title"], row["status"]) for row in items)


def _draft_work_mode(turn_user_text: str = "") -> str:
    from app.writing.work_mode import resolve_work_mode

    outline = ""
    try:
        op = _resolve_path("outline.md")
        if op.is_file():
            outline = op.read_text(encoding="utf-8")
    except OSError:
        outline = ""
    mode, _ = resolve_work_mode(turn_user_text, outline=outline)
    return mode


def _draft_book_scope(turn_user_text: str = "", section_id: str = "") -> str:
    from app.writing.book_scope import resolve_book_scope

    outline = ""
    try:
        op = _resolve_path("outline.md")
        if op.is_file():
            outline = op.read_text(encoding="utf-8")
    except OSError:
        outline = ""
    scope, _src = resolve_book_scope(
        turn_user_text, outline=outline, section_id=section_id
    )
    return scope


def _section_filename(section_id: str) -> str:
    normalized = section_id.strip()
    if not normalized or normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError(f"Invalid section_id: {section_id!r}")
    return f"{normalized}.md"


def _turn_scope(turn_id: object | None) -> str:
    return str(turn_id) if turn_id is not None else "standalone"


def _session_scope(session_id: object | None) -> str | None:
    if session_id is None:
        return None
    return str(session_id)


# Visible work-surface drafts (tree + double-click). History/turns stay under .agent/.
_WORK_DRAFTS = "drafts"
_LEGACY_WORK_DRAFTS = ".agent/work/drafts"
_WORK_HISTORY = ".agent/work/history"
_WORK_TURNS = ".agent/work/turns"


def _draft_file_path(section_id: str) -> str:
    """Canonical in-progress draft path (work-scoped, not session-scoped)."""
    return f"{_WORK_DRAFTS}/{_section_filename(section_id)}"


def _legacy_draft_file_path(section_id: str) -> str:
    return f"{_LEGACY_WORK_DRAFTS}/{_section_filename(section_id)}"


def _history_file_path(section_id: str, turn_id: object | None) -> str:
    return f"{_WORK_HISTORY}/{section_id.strip()}/{_turn_scope(turn_id)}.md"


def _manifest_path(session_id: object | None, turn_id: object | None) -> str:
    """Primary turn touch-list (work-scoped). ``session_id`` kept for API compat."""
    del session_id  # work-scoped; session no longer owns manifests
    return f"{_WORK_TURNS}/{_turn_scope(turn_id)}.json"


def _manifest_candidate_paths(session_id: object | None, turn_id: object | None) -> list[str]:
    """Read order: work turn → session legacy → flat turn legacy."""
    paths: list[str] = [f"{_WORK_TURNS}/{_turn_scope(turn_id)}.json"]
    if session_id is not None and turn_id is not None:
        legacy_session = (
            f".agent/sessions/{_session_scope(session_id)}/turns/"
            f"{_turn_scope(turn_id)}/manifest.json"
        )
        paths.append(legacy_session)
    if turn_id is not None:
        legacy = f".agent/turns/{_turn_scope(turn_id)}/manifest.json"
        if legacy not in paths:
            paths.append(legacy)
    return paths


def _revision_file_path(
    section_id: str,
    *,
    session_id: object | None = None,
    turn_id: object | None = None,
) -> str:
    """Write target for ``draft_section`` — always work drafts."""
    del session_id, turn_id
    return _draft_file_path(section_id)


def _revision_candidate_paths(
    section_id: str,
    *,
    session_id: object | None = None,
    turn_id: object | None = None,
) -> list[str]:
    """Read order: work draft → legacy harness draft → session/turn legacy → flat legacy."""
    filename = _section_filename(section_id)
    paths: list[str] = [_draft_file_path(section_id), _legacy_draft_file_path(section_id)]
    if session_id is not None and turn_id is not None:
        session_path = (
            f".agent/sessions/{_session_scope(session_id)}/revisions/"
            f"{_turn_scope(turn_id)}/{filename}"
        )
        if session_path not in paths:
            paths.append(session_path)
    if turn_id is not None:
        turn_path = f".agent/revisions/{_turn_scope(turn_id)}/{filename}"
        if turn_path not in paths:
            paths.append(turn_path)
    legacy_flat = f".agent/revisions/{filename}"
    if legacy_flat not in paths:
        paths.append(legacy_flat)
    return paths


def _is_legacy_revision_rel(rel_path: str, filename: str) -> bool:
    """True for pre-work-model flat revision files (export warning)."""
    return rel_path == f".agent/revisions/{filename}"


def _section_drafts_occupied() -> bool:
    from app.writing.occupy import manuscript_is_occupied

    drafts = _resolve_path(_WORK_DRAFTS)
    if not drafts.is_dir():
        return False
    for path in drafts.iterdir():
        if not (path.is_file() and path.suffix == ".md"):
            continue
        try:
            if manuscript_is_occupied(path.read_text(encoding="utf-8")):
                return True
        except OSError:
            continue
    return False


def _prune_section_history(section_id: str, *, keep: int) -> None:
    if keep <= 0:
        return
    root = _resolve_path(f"{_WORK_HISTORY}/{section_id.strip()}")
    if not root.is_dir():
        return
    files = sorted(
        (p for p in root.iterdir() if p.is_file() and p.suffix == ".md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in files[keep:]:
        try:
            stale.unlink()
        except OSError:
            continue


def _read_manifest(
    turn_id: object | None,
    *,
    session_id: object | None = None,
) -> dict[str, Any] | None:
    for rel in _manifest_candidate_paths(session_id, turn_id):
        target = _resolve_path(rel)
        if not target.is_file():
            continue
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _write_manifest(
    turn_id: object | None,
    manifest: dict[str, Any],
    *,
    session_id: object | None = None,
) -> str:
    path = _manifest_path(session_id, turn_id)
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return path


def _parse_draft_mode(raw: object | None) -> str:
    token = str(raw or "upsert").strip().lower()
    if token in {"append", "thicken"}:
        return "append"
    if token in {"rewrite_window", "rewrite-window", "window"}:
        return "rewrite_window"
    return "upsert"


def _already_drafted_this_turn(manifest: dict[str, Any] | None) -> bool:
    """本 Turn 已写过章：禁止再因「写一篇」误触发 occupy=fresh（会清掉加厚门禁）。"""
    if not isinstance(manifest, dict):
        return False
    if str(manifest.get("occupy") or "") == "fresh":
        return True
    if manifest.get("sections"):
        return True
    drafts = manifest.get("section_drafts")
    return isinstance(drafts, dict) and bool(drafts)


def _replace_unique_span(text: str, old_text: str, new_text: str) -> str | None:
    from app.writing.span_replace import replace_span_in_manuscript

    return replace_span_in_manuscript(
        text,
        section_id="",
        old_text=old_text,
        new_text=new_text,
    )


def _replace_rewrite_window(
    existing: str,
    *,
    section_id: str,
    old_text: str,
    new_text: str,
) -> str | None:
    from app.writing.span_replace import replace_span_in_manuscript

    return replace_span_in_manuscript(
        existing,
        section_id=section_id,
        old_text=old_text,
        new_text=new_text,
    )


def _collapse_rewrite_result(
    document: str,
    *,
    section_id: str,
    monofile: bool,
) -> tuple[str, str, int]:
    """After rewrite_window, fold large exact paragraph duplicates.

    Returns ``(document, scored_body, removed_count)``.
    """
    from app.writing.manuscript import extract_section
    from app.writing.prose_dedupe import (
        collapse_duplicate_paragraphs,
        collapse_prose_duplicates,
    )

    if monofile:
        final, removed = collapse_prose_duplicates(document, section_id=section_id)
        scored = extract_section(final, section_id) or ""
        return final, scored, removed
    final, removed = collapse_duplicate_paragraphs(document)
    return final, final, removed


def _reject_rewrite_window(
    manifest: dict[str, Any],
    *,
    section_id: str,
    content: str,
    path: str,
    existing: str,
) -> dict[str, Any] | None:
    from app.writing.patch_budget import check_rewrite_window_allowed
    from app.writing.signals.repair import REWRITE_PATCH
    from app.writing.span_replace import span_replaceable_in_manuscript

    blocked_cap = check_rewrite_window_allowed(manifest, section_id=section_id)
    if blocked_cap:
        blocked_cap.setdefault("section_id", section_id)
        blocked_cap.setdefault("path", path)
        return blocked_cap

    prior = (manifest.get("section_drafts") or {}).get(section_id)
    if not isinstance(prior, dict):
        return {
            "section_id": section_id,
            "path": path,
            "status": "error",
            "error": "rewrite_window_no_prior",
            "summary": "mode=rewrite_window 需要本章已有 writing_signals.repair_span。",
        }
    span = prior.get("repair_span")
    if not isinstance(span, dict) or not str(span.get("old_text") or "").strip():
        return {
            "section_id": section_id,
            "path": path,
            "status": "error",
            "error": "rewrite_window_no_span",
            "rewrite_policy": REWRITE_PATCH,
            "summary": "repair_span 已清或不可定位；L0 清后在已有拍里写满，不要粘第二场。",
        }
    old = str(span["old_text"])
    from app.writing.patch_budget import island_untouched_error
    from app.writing.signals.repair import (
        REWRITE_STOP,
        island_untouched,
        span_allows_rewrite_window,
    )

    if not span_allows_rewrite_window(prior, old):
        return {
            "section_id": section_id,
            "path": path,
            "status": "error",
            "error": "rewrite_window_not_for_chip",
            "rewrite_policy": REWRITE_STOP,
            "summary": (
                "repair_span 不是小岛，禁止 mode=rewrite_window。"
                "不要重写开篇整窗。本章可交，这一窗留到下轮。"
            ),
            "repair_span": span,
        }
    penalty_key = str(span.get("key") or "staccato_uniform")
    if island_untouched(old, content, penalty_key=penalty_key):
        from app.writing.patch_budget import _long_form

        err = island_untouched_error(
            old_text=old,
            new_text=content,
            penalty_key=penalty_key,
            long_form=_long_form(manifest, prior),
        )
        err.setdefault("section_id", section_id)
        err.setdefault("path", path)
        return err
    if not span_replaceable_in_manuscript(existing, section_id=section_id, old_text=old):
        return {
            "section_id": section_id,
            "path": path,
            "status": "error",
            "error": "rewrite_window_span_miss",
            "repair_span": span,
            "summary": (
                "repair_span.old_text 须在本章正文中可定位；先 read_file 对齐 span，"
                "再一次写满替换窗（章内 duplicate 会一并替换）。"
            ),
        }
    del content
    return None


def _reject_full_redraft(
    manifest: dict[str, Any],
    *,
    section_id: str,
    occupy_fresh: bool,
    path: str,
    mode: str = "upsert",
) -> dict[str, Any] | None:
    if occupy_fresh or mode == "append" or mode == "rewrite_window":
        return None
    from app.writing.signals.repair import REWRITE_PATCH, should_reject_full_redraft

    prior = (manifest.get("section_drafts") or {}).get(section_id)
    if not isinstance(prior, dict) or not should_reject_full_redraft(prior):
        return None
    span = prior.get("repair_span")
    err: dict[str, Any] = {
        "section_id": section_id,
        "path": path,
        "status": "error",
        "error": "rewrite_via_patch",
        "rewrite_policy": REWRITE_PATCH,
        "summary": (
            "本章本轮已成稿。有 writing_signals.repair_span 则 propose_patch 只换 old_text；"
            "章级 L0（碎拍/铰链/开篇机构/身世）清掉后，若这场还没写满，在已有拍里补对白/反应；"
            "已经收住就不要 mode=append 粘第二场。不要整章 upsert。"
        ),
    }
    if span:
        err["repair_span"] = span
        err["writing_signals"] = {
            "repair_span": span,
            "rewrite_policy": REWRITE_PATCH,
        }
    return err


def _reject_append_gate(
    manifest: dict[str, Any],
    *,
    section_id: str,
    content: str,
    occupy_fresh: bool,
    path: str,
    mode: str,
    work_mode: str = "literary",
    turn_user_text: str = "",
) -> dict[str, Any] | None:
    """章级过程 L0 未清，或新切片自带碎拍 → 拒 append（不落盘）。长篇 L0 不挡加厚。"""
    if occupy_fresh or mode != "append":
        return None
    from app.writing.book_scope import resolve_book_scope
    from app.writing.signals.repair import (
        REWRITE_PATCH,
        prior_blocks_append,
        slice_blocks_append,
    )

    scope, _src = resolve_book_scope(turn_user_text, section_id=section_id)
    prior = (manifest.get("section_drafts") or {}).get(section_id)
    blocked = None
    if scope != "long":
        blocked = prior_blocks_append(
            prior if isinstance(prior, dict) else None,
            work_mode=work_mode,
        )
    if blocked:
        span = None
        if isinstance(prior, dict):
            span = prior.get("repair_span")
        from app.writing.patch_budget import patch_budget_exhausted, resolve_penalty_key

        penalty_key = resolve_penalty_key(prior if isinstance(prior, dict) else None)
        exhausted = patch_budget_exhausted(
            manifest,
            section_id=section_id,
            penalty_key=penalty_key,
        )
        from app.writing.patch_budget import _escalation_policy, _long_form, _stop_summary
        from app.writing.signals.repair import REWRITE_STOP

        long_form = _long_form(manifest, prior if isinstance(prior, dict) else None)
        old_for_span = ""
        if isinstance(span, dict):
            old_for_span = str(span.get("old_text") or "")
        escalate = _escalation_policy(
            prior if isinstance(prior, dict) else None,
            old_text=old_for_span,
            penalty_key=penalty_key,
            long_form=long_form,
        )
        rewrite_policy = REWRITE_PATCH
        window_hint = ""
        if exhausted:
            if escalate == "rewrite_window":
                rewrite_policy = "rewrite_window"
                window_hint = (
                    " patch 预算已尽：改 draft_section mode=rewrite_window 一次换小岛。"
                )
            else:
                rewrite_policy = escalate or REWRITE_STOP
                window_hint = " " + _stop_summary(long_form=long_form)
        patch_hint = (
            "改 draft_section mode=rewrite_window 清岛，"
            if rewrite_policy == "rewrite_window"
            else "先 propose_patch 清 writing_signals.repair_span，"
        )
        err: dict[str, Any] = {
            "section_id": section_id,
            "path": path,
            "status": "error",
            "error": "append_while_l0",
            "rewrite_policy": rewrite_policy,
            "l0_key": blocked,
            "summary": (
                f"章级过程门仍开（{blocked}）：{patch_hint}"
                f"不要 mode=append。{window_hint}"
                "岛清后再加厚；新切片也不要再写碎对拍/对拍三联。"
            ),
        }
        if isinstance(span, dict) and span.get("old_text"):
            err["repair_span"] = span
            err["writing_signals"] = {
                "repair_span": span,
                "rewrite_policy": REWRITE_PATCH,
            }
        return err
    slice_hit = slice_blocks_append(content, work_mode=work_mode)
    if slice_hit:
        return {
            "section_id": section_id,
            "path": path,
            "status": "error",
            "error": "append_slice_weak",
            "rewrite_policy": REWRITE_PATCH,
            "l0_key": slice_hit,
            "summary": (
                "加厚切片自身命中碎拍嗓（对拍/采访/主题金句等）：重写这一段再 mode=append，"
                "不要把新对拍灌进章。保留场面与「」，多轮空问收成一两句或用物件/停顿接。"
            ),
        }
    return None


async def draft_section(
    section_id: str,
    content: str,
    turn_id: object | None = None,
    session_id: object | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """写入或更新某一章节草稿，并更新 turn manifest 与 writing_signals。

    参数:
        section_id: 章节 ID（映射为 ``drafts/{section_id}.md`` 或 monofile 内区块）。
        content: 章节正文。
        turn_id: 可选 Turn ID，用于 manifest/history 作用域。
        session_id: 兼容参数，manifest 已 work-scoped。
        **_kwargs: ``layout``/``occupy``/``mode``/``fragment``/``turn_user_text`` 等写作控制项。

    返回:
        ``status=drafted`` 及 ``path``/``manifest_path``/``writing_signals`` 等；
        已成稿章节拒绝整章重写时返回 ``rewrite_via_patch`` 错误。

    说明:
        ``occupy_fresh`` 会归档旧 occupied 文档并重置 manifest sections；monofile 用
        ``upsert_section`` / ``append_section``。评分与篇幅看拼接后的整章。
    """
    from app.writing.manuscript import (
        append_section,
        draft_manuscript_rel,
        extract_section,
        legacy_draft_manuscript_rel,
        manuscript_mode,
        upsert_section,
    )

    layout = str(_kwargs.get("layout") or manuscript_mode()).strip().lower()
    if layout not in {"monofile", "sections"}:
        layout = manuscript_mode()

    from app.writing.occupy import (
        archive_occupied_writing_docs,
        manuscript_is_occupied,
        occupy_result_fields,
        should_occupy_fresh,
    )

    manifest = _read_manifest(turn_id, session_id=session_id) or {
        "turn_id": _turn_scope(turn_id),
        "session_id": _session_scope(session_id),
        "sections": [],
        "revisions": {},
        "layout": layout,
    }
    turn_user_text = str(_kwargs.get("turn_user_text") or "")
    work_mode = _draft_work_mode(turn_user_text)
    archived: list[str] = []
    occupy_fresh = False
    mode = _parse_draft_mode(_kwargs.get("mode"))
    from app.writing.commitment import fulfillment_facts, gate_draft_commitment

    blocked_commit, commit = gate_draft_commitment(
        content=content,
        mode=mode,
        work_mode=work_mode,
        section_id=section_id,
        raw=_kwargs.get("narrative_commitment"),
        workspace_root=Path(settings.workspace_root),
    )
    if blocked_commit:
        return blocked_commit
    scored = content
    dup_collapsed = 0

    if layout == "monofile":
        path = draft_manuscript_rel()
        target = _resolve_path(path)
        denied = _mkdir_parent(target, path)
        if denied:
            return denied
        if target.exists():
            existing = target.read_text(encoding="utf-8")
        else:
            legacy = _resolve_path(legacy_draft_manuscript_rel())
            existing = legacy.read_text(encoding="utf-8") if legacy.is_file() else ""
        occupy_fresh = should_occupy_fresh(
            occupy_arg=_kwargs.get("occupy"),
            user_text=str(_kwargs.get("turn_user_text") or ""),
            already_fresh_this_turn=_already_drafted_this_turn(manifest),
            occupied=manuscript_is_occupied(existing),
        )
        blocked = _reject_full_redraft(
            manifest,
            section_id=section_id,
            occupy_fresh=occupy_fresh,
            path=path,
            mode=mode,
        )
        if blocked:
            return blocked
        blocked_append = _reject_append_gate(
            manifest,
            section_id=section_id,
            content=content,
            occupy_fresh=occupy_fresh,
            path=path,
            mode=mode,
            work_mode=work_mode,
            turn_user_text=turn_user_text,
        )
        if blocked_append:
            return blocked_append
        if occupy_fresh:
            archived = archive_occupied_writing_docs(layout=layout)
            existing = ""
            manifest["occupy"] = "fresh"
        if mode == "rewrite_window":
            blocked_rw = _reject_rewrite_window(
                manifest,
                section_id=section_id,
                content=content,
                path=path,
                existing=existing,
            )
            if blocked_rw:
                if blocked_rw.get("error") == "patch_island_untouched" and turn_id is not None:
                    from app.writing.patch_budget import record_rewrite_window_attempt

                    record_rewrite_window_attempt(manifest, section_id=section_id)
                    _write_manifest(turn_id, manifest, session_id=session_id)
                return blocked_rw
            span = (manifest.get("section_drafts") or {}).get(section_id) or {}
            old = str((span.get("repair_span") or {}).get("old_text") or "")
            final = _replace_rewrite_window(
                existing,
                section_id=section_id,
                old_text=old,
                new_text=content,
            )
            if final is None:
                return {
                    "section_id": section_id,
                    "path": path,
                    "status": "error",
                    "error": "rewrite_window_span_miss",
                    "summary": "repair_span.old_text 须在本章正文中可定位。",
                }
            final, scored, dup_collapsed = _collapse_rewrite_result(
                final, section_id=section_id, monofile=True
            )
            target.write_text(final, encoding="utf-8")
            from app.writing.patch_budget import record_rewrite_window_attempt

            record_rewrite_window_attempt(manifest, section_id=section_id)
        elif mode == "append" and not occupy_fresh:
            final = append_section(existing, section_id, content)
            target.write_text(final, encoding="utf-8")
            scored = extract_section(final, section_id) or content
        else:
            final = upsert_section(existing, section_id, content)
            target.write_text(final, encoding="utf-8")
            scored = extract_section(final, section_id) or content
    else:
        path = _draft_file_path(section_id)
        target = _resolve_path(path)
        denied = _mkdir_parent(target, path)
        if denied:
            return denied
        occupy_fresh = should_occupy_fresh(
            occupy_arg=_kwargs.get("occupy"),
            user_text=str(_kwargs.get("turn_user_text") or ""),
            already_fresh_this_turn=_already_drafted_this_turn(manifest),
            occupied=_section_drafts_occupied(),
        )
        blocked = _reject_full_redraft(
            manifest,
            section_id=section_id,
            occupy_fresh=occupy_fresh,
            path=path,
            mode=mode,
        )
        if blocked:
            return blocked
        blocked_append = _reject_append_gate(
            manifest,
            section_id=section_id,
            content=content,
            occupy_fresh=occupy_fresh,
            path=path,
            mode=mode,
            work_mode=work_mode,
            turn_user_text=turn_user_text,
        )
        if blocked_append:
            return blocked_append
        if occupy_fresh:
            archived = archive_occupied_writing_docs(layout=layout)
            manifest["occupy"] = "fresh"
        elif not target.exists():
            legacy = _resolve_path(_legacy_draft_file_path(section_id))
            if legacy.is_file():
                target.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        section_text = target.read_text(encoding="utf-8") if target.exists() else ""
        if mode == "rewrite_window":
            blocked_rw = _reject_rewrite_window(
                manifest,
                section_id=section_id,
                content=content,
                path=path,
                existing=section_text,
            )
            if blocked_rw:
                if blocked_rw.get("error") == "patch_island_untouched" and turn_id is not None:
                    from app.writing.patch_budget import record_rewrite_window_attempt

                    record_rewrite_window_attempt(manifest, section_id=section_id)
                    _write_manifest(turn_id, manifest, session_id=session_id)
                return blocked_rw
            span = (manifest.get("section_drafts") or {}).get(section_id) or {}
            old = str((span.get("repair_span") or {}).get("old_text") or "")
            final = _replace_rewrite_window(
                section_text,
                section_id=section_id,
                old_text=old,
                new_text=content,
            )
            if final is None:
                return {
                    "section_id": section_id,
                    "path": path,
                    "status": "error",
                    "error": "rewrite_window_span_miss",
                    "summary": "repair_span.old_text 须在本章正文中可定位。",
                }
            final, scored, dup_collapsed = _collapse_rewrite_result(
                final, section_id=section_id, monofile=False
            )
            target.write_text(final, encoding="utf-8")
            from app.writing.patch_budget import record_rewrite_window_attempt

            record_rewrite_window_attempt(manifest, section_id=section_id)
        elif mode == "append" and not occupy_fresh and target.exists():
            prev = section_text or target.read_text(encoding="utf-8")
            addition = (content or "").strip()
            scored = (prev.rstrip() + "\n\n" + addition).strip() + "\n" if prev.strip() else addition
            target.write_text(scored if scored.endswith("\n") else scored + "\n", encoding="utf-8")
        else:
            target.write_text(content, encoding="utf-8")
            scored = content

    history_path: str | None = None
    keep = int(getattr(settings, "writing_draft_history_keep", 5) or 0)
    if keep > 0 and turn_id is not None:
        history_path = _history_file_path(section_id, turn_id)
        hist = _resolve_path(history_path)
        hist.parent.mkdir(parents=True, exist_ok=True)
        hist.write_text(scored, encoding="utf-8")
        _prune_section_history(section_id, keep=keep)

    if session_id is not None and not manifest.get("session_id"):
        manifest["session_id"] = _session_scope(session_id)
    manifest["layout"] = layout
    if occupy_fresh and turn_id is not None:
        manifest["occupy"] = "fresh"
        manifest["sections"] = []
        manifest["revisions"] = {}
        manifest["section_drafts"] = {}
    sections = manifest.setdefault("sections", [])
    revisions = manifest.setdefault("revisions", {})
    if section_id not in sections:
        sections.append(section_id)
    revisions[section_id] = path
    manifest_path = _write_manifest(turn_id, manifest, session_id=session_id)
    result: dict[str, Any] = {
        "section_id": section_id,
        "path": path,
        "manifest_path": manifest_path,
        "status": "drafted",
        "layout": layout,
    }
    if history_path:
        result["history_path"] = history_path
    result.update(
        draft_length_fields(
            scored,
            str(_kwargs.get("turn_user_text") or ""),
        )
    )
    result.update(hinge_fields(scored))
    result.update(lore_fields(scored, section_id))
    result.update(opening_fields(scored, section_id))
    result.update(staccato_fields(scored, work_mode=work_mode))
    if occupy_fresh:
        occupy_fields = occupy_result_fields(archived)
        archive_note = str(occupy_fields.pop("summary", "") or "").strip()
        result.update(occupy_fields)
        if archive_note:
            prev = str(result.get("summary") or "").strip()
            result["summary"] = f"{archive_note} {prev}".strip() if prev else archive_note
    if mode == "append":
        result["mode"] = "append"
    elif mode == "rewrite_window":
        result["mode"] = "rewrite_window"
        if dup_collapsed:
            result["duplicates_collapsed"] = dup_collapsed
            note = f"collapsed {dup_collapsed} duplicate paragraph(s)"
            prev = str(result.get("summary") or "").strip()
            result["summary"] = f"{note}; {prev}" if prev else note
    fragment = str(_kwargs.get("fragment") or "mixed").strip()
    try:
        from app.writing.signals.assemble import build_writing_signals

        signals = await build_writing_signals(
            scored,
            fragment=fragment,
            section_id=section_id,
            session_id=session_id,
            turn_id=turn_id,
            persist=True,
            turn_user_text=str(_kwargs.get("turn_user_text") or ""),
        )
        result["fragment"] = signals.get("fragment")
        result["writing_signals"] = signals
    except Exception:
        pass
    if commit:
        result["commitment_fulfillment"] = fulfillment_facts(scored, commit)
    drafts = manifest.setdefault("section_drafts", {})
    from app.writing.signals.repair import process_l0_hits

    entry: dict[str, Any] = {
        "visible_chars": int(result.get("visible_chars") or 0),
        "length_short": bool(result.get("length_short")),
        "book_scope": _draft_book_scope(
            str(_kwargs.get("turn_user_text") or ""), section_id=section_id
        ),
    }
    signals_block = result.get("writing_signals")
    penalties = None
    if isinstance(signals_block, dict):
        penalties = signals_block.get("penalties")
        if signals_block.get("repair_span"):
            entry["repair_span"] = signals_block["repair_span"]
        if signals_block.get("rewrite_policy"):
            entry["rewrite_policy"] = signals_block["rewrite_policy"]
        if signals_block.get("composite") is not None:
            entry["composite"] = signals_block["composite"]
        if signals_block.get("net_signal") is not None:
            entry["net_signal"] = signals_block["net_signal"]
        frag = signals_block.get("fragment")
        declared = frag.get("declared") if isinstance(frag, dict) else frag
        if declared:
            entry["fragment"] = declared
    entry["l0_hits"] = process_l0_hits(penalties, flags=result, work_mode=work_mode)
    drafts[section_id] = entry
    result["manifest_path"] = _write_manifest(turn_id, manifest, session_id=session_id)
    return result


async def update_plan(
    items: list[dict[str, Any]],
    summary: str = "",
    turn_id=None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """更新 Turn 进度/计划条目列表，规划阶段可强制全部 pending 等待用户确认。

    参数:
        items: 计划项 dict 列表（``id``/``title``/``status`` 等）。
        summary: 可选摘要；缺省时按 phase 生成。
        turn_id: 用于检测重复提交（unchanged 短路）。
        **_kwargs: ``plan_phase=planning`` 时全部 pending 并设 ``awaiting_consent``。

    返回:
        ``plan_id``/``items``/``summary``；未变化时 ``unchanged=True``。

    说明:
        软约束：至多一个 ``in_progress``，多余项 demote 为 pending。
    """
    plan_id = f"plan-{uuid4().hex[:8]}"
    normalized: list[dict[str, str]] = []
    in_progress_count = 0
    # Planning phase: force all pending so the consent CTA can appear (docs/25).
    force_pending = str(_kwargs.get("plan_phase") or "").strip().lower() == "planning"
    for i, item in enumerate(items):
        status = str(item.get("status", "pending")).strip().lower()
        if force_pending:
            status = "pending"
        elif status in {"done", "complete", "completed"}:
            # Wire value stays `done` for event schema / projector compatibility.
            status = "done"
        elif status in {"in-progress", "running", "in_progress"}:
            status = "in_progress"
            in_progress_count += 1
        elif status in {"cancelled", "canceled", "skipped"}:
            status = "cancelled"
        else:
            status = "pending" if status in {"", "todo", "open", "pending"} else status
        normalized.append(
            {
                "id": str(item.get("id", i + 1)),
                "title": str(item.get("title", item.get("text", "item")))[:512],
                "status": status,
            }
        )
    # Soft discipline: at most one in_progress (keep first; demote extras to pending).
    if in_progress_count > 1 and not force_pending:
        seen = False
        for row in normalized:
            if row["status"] != "in_progress":
                continue
            if not seen:
                seen = True
                continue
            row["status"] = "pending"
    result: dict[str, Any] = {
        "plan_id": plan_id,
        "items": normalized,
        "summary": summary
        or (
            f"Plan with {len(normalized)} item(s) — awaiting confirmation "
            "（请用户点「按此执行」后再开始）"
            if force_pending
            else f"Progress with {len(normalized)} item(s)"
        ),
    }
    if force_pending:
        result["plan_phase"] = "planning"
        result["awaiting_consent"] = True
        if summary:
            result["summary"] = summary
    sig = _plan_signature(normalized)
    key = str(turn_id) if turn_id is not None else ""
    if key and _LAST_PLAN_SIG.get(key) == sig:
        result["unchanged"] = True
        result["summary"] = "Plan unchanged"
        return result
    if key:
        if len(_LAST_PLAN_SIG) > 256:
            _LAST_PLAN_SIG.clear()
        _LAST_PLAN_SIG[key] = sig
    return result


async def propose_opening_ponds(
    items: list[dict[str, Any]],
    summary: str = "",
    **_kwargs: Any,
) -> dict[str, Any]:
    """交 2～3 个开篇近池，停下来等用户点选或说「我要其他的」。"""
    from app.writing.opening_ponds import (
        _MIN_ITEMS,
        load_opening_ponds,
        note_pond_reject,
        normalize_pond_items,
        ponds_reject_reason,
        rank_opening_ponds,
        save_opening_ponds,
        wants_more_ponds,
    )

    normalized = normalize_pond_items(items)
    if len(normalized) < _MIN_ITEMS:
        return {
            "status": "error",
            "error": "need_two_ponds",
            "summary": "至少交 2 个开篇候选，且 start_kind 不得重复。",
        }
    message = str(_kwargs.get("turn_user_text") or "")
    previous_kinds: set[str] | None = None
    previous_axes: set[str] | None = None
    if wants_more_ponds(message):
        prev = load_opening_ponds()
        if prev:
            previous_kinds = {
                str(it.get("start_kind") or "")
                for it in prev["items"]
                if it.get("start_kind")
            }
            previous_axes = {
                str(it.get("price_axis") or "")
                for it in prev["items"]
                if it.get("price_axis")
            }
    rejected = ponds_reject_reason(
        normalized,
        message=message,
        previous_kinds=previous_kinds,
        previous_axes=previous_axes,
        workspace_root=Path(settings.workspace_root),
    )
    exhausted = note_pond_reject(_kwargs.get("turn_id"), rejected)
    if exhausted:
        return exhausted
    ranked = rank_opening_ponds(normalized)
    saved = save_opening_ponds(ranked, summary="")
    from app.writing.ledger import append_ledger, pond_vector

    root = Path(settings.workspace_root)
    for item in saved["items"]:
        append_ledger(pond_vector(item), workspace_root=root, kind="pond")
    return {
        "status": "ok",
        "ponds_id": saved["ponds_id"],
        "items": saved["items"],
        "summary": saved.get("summary")
        or f"{len(normalized)} 个开篇候选，待你点选或说「我要其他的」",
        "awaiting_choice": True,
    }


async def update_outline(
    content: str,
    mode: str = "replace",
    **_kwargs: Any,
) -> dict[str, Any]:
    """写入 ``outline.md``：replace 或 append；replace 时对灾难性缩短做保护。

    参数:
        content: 大纲 Markdown 内容。
        mode: ``replace`` 或 ``append``（长大纲续写推荐 append）。
        **_kwargs: ``force=true`` 可绕过 replace 缩短拒绝；``turn_id``/``session_id``/``occupy`` 等同 draft。

    返回:
        写入结果 dict；replace 且新内容远小于旧文件时返回 error，除非 ``force``。

    说明:
        ``occupy_fresh`` 行为与 ``draft_section`` 一致，可归档旧 occupied 写作文档。
    """
    path = "outline.md"
    target = _resolve_path(path)
    denied = _mkdir_parent(target, path)
    if denied:
        return denied
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    mode_n = (mode or "replace").strip().lower()
    force = str(_kwargs.get("force", "")).lower() in {"1", "true", "yes"}

    from app.writing.occupy import (
        archive_occupied_writing_docs,
        manuscript_is_occupied,
        occupy_result_fields,
        should_occupy_fresh,
    )

    turn_id = _kwargs.get("turn_id")
    session_id = _kwargs.get("session_id")
    manifest = _read_manifest(turn_id, session_id=session_id) or {}

    occupy_fresh = should_occupy_fresh(
        occupy_arg=_kwargs.get("occupy"),
        user_text=str(_kwargs.get("turn_user_text") or ""),
        already_fresh_this_turn=_already_drafted_this_turn(manifest),
        occupied=manuscript_is_occupied(existing),
    )
    archived: list[str] = []
    if occupy_fresh:
        archived = archive_occupied_writing_docs(layout="monofile")
        existing = ""
        mode_n = "replace"
        force = True
        if turn_id is not None:
            manifest = {
                "turn_id": _turn_scope(turn_id),
                "session_id": _session_scope(session_id),
                "sections": list(manifest.get("sections") or []),
                "revisions": dict(manifest.get("revisions") or {}),
                "layout": str(manifest.get("layout") or "monofile"),
                "occupy": "fresh",
            }
            _write_manifest(turn_id, manifest, session_id=session_id)

    if mode_n == "append":
        if existing and not existing.endswith("\n"):
            sep = "\n\n"
        elif existing:
            sep = "\n" if not existing.endswith("\n\n") else ""
        else:
            sep = ""
        final = f"{existing}{sep}{content.lstrip()}" if existing else content
        summary = "Outline appended"
    else:
        if (
            not force
            and len(existing) >= 500
            and len(content) < max(200, int(len(existing) * 0.4))
        ):
            return {
                "status": "error",
                "path": path,
                "error": (
                    f"refusing outline replace that shrinks {len(existing)}→{len(content)} chars; "
                    "use mode=append for continuation, or force=true for intentional full rewrite"
                ),
                "outline_path": path,
                "existing_chars": len(existing),
            }
        final = content
        summary = "Outline updated"

    target.write_text(final, encoding="utf-8")
    scored = content if mode_n == "append" else final
    result: dict[str, Any] = {
        "path": path,
        "content": final,
        "summary": summary,
        "outline_path": path,
        "mode": "append" if mode_n == "append" else "replace",
    }
    thin = outline_thin_fields(scored, str(_kwargs.get("turn_user_text") or ""))
    suffix = thin.pop("summary_suffix", None)
    result.update(thin)
    arc = outline_arc_fields(final, str(_kwargs.get("turn_user_text") or ""))
    arc_suffix = arc.pop("summary_suffix", None)
    result.update(arc)
    from app.writing.outline_arc import (
        OPENING_TRILOGY_OUTLINE_TEMPLATE,
        opening_trilogy_fields,
        outline_style_committed,
        style_contract_fields,
    )

    tri = opening_trilogy_fields(final, str(_kwargs.get("turn_user_text") or ""))
    if tri.get("outline_opening_trilogy_missing"):
        result["opening_trilogy_template"] = OPENING_TRILOGY_OUTLINE_TEMPLATE
    style_tri = style_contract_fields(final, str(_kwargs.get("turn_user_text") or ""))
    if style_tri.get("style_contract_template"):
        result["style_contract_template"] = style_tri["style_contract_template"]
    style_suffix = style_tri.pop("summary_suffix", None)
    result.update({k: v for k, v in style_tri.items() if k != "summary_suffix"})
    from app.writing.outline_phase import (
        clear_style_lock,
        outline_contract_ready,
        resolve_outline_phase,
        style_lock_exists,
        write_style_lock,
    )

    user_text = str(_kwargs.get("turn_user_text") or "")
    scope_ready = outline_contract_ready(final, user_text=user_text)
    style_ready = outline_style_committed(final)
    phase = resolve_outline_phase(user_text, outline=final)
    result["outline_phase"] = phase.get("outline_phase")
    if scope_ready:
        if write_style_lock(final) is not None:
            result["style_lock"] = "writing/style.lock"
        result["outline_contract_ready"] = True
    elif style_ready:
        if write_style_lock(final) is not None:
            result["style_lock"] = "writing/style.lock"
        result["outline_style_committed"] = True
    elif style_lock_exists():
        clear_style_lock()
    notes = [part for part in (suffix, arc_suffix, style_suffix) if part]
    if occupy_fresh:
        occupy_fields = occupy_result_fields(archived)
        archive_note = str(occupy_fields.pop("summary", "") or "").strip()
        result.update(occupy_fields)
        if archive_note:
            notes.insert(0, archive_note)
    if notes:
        result["summary"] = f"{summary}；" + "；".join(notes)
    return result
