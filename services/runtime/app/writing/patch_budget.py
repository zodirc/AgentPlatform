"""Turn-scoped prose patch budget (count applied repairs, not proposals)."""

from __future__ import annotations

from typing import Any

MAX_PATCHES_PER_PENALTY_KEY = 5
MAX_PATCHES_PER_SECTION_TOTAL = 8
MAX_REWRITE_WINDOW_PER_SECTION = 2
MAX_APPLY_MISS_STREAK = 2
UNKNOWN_PENALTY_KEY = "__unknown__"
FALLBACK_SECTION_ID = "__prose__"


def _budget_root(manifest: dict[str, Any]) -> dict[str, Any]:
    row = manifest.setdefault("patch_budget", {})
    return row if isinstance(row, dict) else {}


def normalize_penalty_key(penalty_key: str) -> str:
    key = str(penalty_key or "").strip()
    return key if key else UNKNOWN_PENALTY_KEY


def normalize_section_id(section_id: str, *, path: str = "") -> str:
    sid = str(section_id or "").strip()
    if sid:
        return sid
    from app.writing.signals.prose_path import is_prose_writing_path, section_id_from_path

    if path:
        from_path = section_id_from_path(path)
        if from_path:
            return from_path
        if is_prose_writing_path(path):
            return FALLBACK_SECTION_ID
    return ""


def count_patch_attempts(
    manifest: dict[str, Any] | None,
    *,
    section_id: str,
    penalty_key: str,
) -> int:
    sid = normalize_section_id(section_id)
    key = normalize_penalty_key(penalty_key)
    if not manifest or not sid:
        return 0
    section = _budget_root(manifest).get(sid)
    if not isinstance(section, dict):
        return 0
    by_key = section.get("by_key")
    if not isinstance(by_key, dict):
        return 0
    try:
        return int(by_key.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def count_section_patch_total(manifest: dict[str, Any] | None, *, section_id: str) -> int:
    sid = normalize_section_id(section_id)
    if not manifest or not sid:
        return 0
    section = _budget_root(manifest).get(sid)
    if not isinstance(section, dict):
        return 0
    by_key = section.get("by_key")
    if not isinstance(by_key, dict):
        return 0
    total = 0
    for raw in by_key.values():
        try:
            total += int(raw or 0)
        except (TypeError, ValueError):
            continue
    return total


def count_rewrite_window_attempts(
    manifest: dict[str, Any] | None, *, section_id: str
) -> int:
    sid = normalize_section_id(section_id)
    if not manifest or not sid:
        return 0
    section = _budget_root(manifest).get(sid)
    if not isinstance(section, dict):
        return 0
    try:
        return int(section.get("rewrite_window") or 0)
    except (TypeError, ValueError):
        return 0


def patch_budget_exhausted(
    manifest: dict[str, Any] | None,
    *,
    section_id: str,
    penalty_key: str,
) -> bool:
    sid = normalize_section_id(section_id)
    if not sid:
        return False
    key = normalize_penalty_key(penalty_key)
    if count_section_patch_total(manifest, section_id=sid) >= MAX_PATCHES_PER_SECTION_TOTAL:
        return True
    return count_patch_attempts(manifest, section_id=sid, penalty_key=key) >= MAX_PATCHES_PER_PENALTY_KEY


def rewrite_window_exhausted(
    manifest: dict[str, Any] | None, *, section_id: str
) -> bool:
    return (
        count_rewrite_window_attempts(manifest, section_id=section_id)
        >= MAX_REWRITE_WINDOW_PER_SECTION
    )


def apply_miss_streak(manifest: dict[str, Any] | None, *, section_id: str) -> int:
    sid = normalize_section_id(section_id)
    if not manifest or not sid:
        return 0
    section = _budget_root(manifest).get(sid)
    if not isinstance(section, dict):
        return 0
    try:
        return int(section.get("apply_miss_streak") or 0)
    except (TypeError, ValueError):
        return 0


def record_patch_attempt(
    manifest: dict[str, Any],
    *,
    section_id: str,
    penalty_key: str,
    old_text: str,
) -> None:
    """Record a successfully applied prose patch."""
    sid = normalize_section_id(section_id)
    if not sid:
        return
    key = normalize_penalty_key(penalty_key)
    root = _budget_root(manifest)
    section = root.setdefault(
        sid,
        {"by_key": {}, "last": [], "apply_miss_streak": 0, "rewrite_window": 0},
    )
    if not isinstance(section, dict):
        section = {"by_key": {}, "last": [], "apply_miss_streak": 0, "rewrite_window": 0}
        root[sid] = section
    by_key = section.setdefault("by_key", {})
    if not isinstance(by_key, dict):
        by_key = {}
        section["by_key"] = by_key
    by_key[key] = int(by_key.get(key) or 0) + 1
    last = section.setdefault("last", [])
    if not isinstance(last, list):
        last = []
        section["last"] = last
    last.append({"key": key, "old_text": (old_text or "")[:160]})
    if len(last) > 12:
        section["last"] = last[-12:]
    section["apply_miss_streak"] = 0


def record_apply_miss(manifest: dict[str, Any], *, section_id: str) -> None:
    sid = normalize_section_id(section_id)
    if not sid:
        return
    root = _budget_root(manifest)
    section = root.setdefault(
        sid,
        {"by_key": {}, "last": [], "apply_miss_streak": 0, "rewrite_window": 0},
    )
    if not isinstance(section, dict):
        section = {"by_key": {}, "last": [], "apply_miss_streak": 0, "rewrite_window": 0}
        root[sid] = section
    try:
        streak = int(section.get("apply_miss_streak") or 0)
    except (TypeError, ValueError):
        streak = 0
    section["apply_miss_streak"] = streak + 1


def record_rewrite_window_attempt(manifest: dict[str, Any], *, section_id: str) -> None:
    sid = normalize_section_id(section_id)
    if not sid:
        return
    root = _budget_root(manifest)
    section = root.setdefault(
        sid,
        {"by_key": {}, "last": [], "apply_miss_streak": 0, "rewrite_window": 0},
    )
    if not isinstance(section, dict):
        section = {"by_key": {}, "last": [], "apply_miss_streak": 0, "rewrite_window": 0}
        root[sid] = section
    try:
        count = int(section.get("rewrite_window") or 0)
    except (TypeError, ValueError):
        count = 0
    section["rewrite_window"] = count + 1


def resolve_penalty_key(
    prior: dict[str, Any] | None,
    *,
    old_text: str = "",
) -> str:
    del old_text
    if not isinstance(prior, dict):
        return UNKNOWN_PENALTY_KEY
    span = prior.get("repair_span")
    if isinstance(span, dict):
        key = str(span.get("key") or "").strip()
        if key:
            return key
    return UNKNOWN_PENALTY_KEY


def resolve_section_for_prose_patch(
    path: str,
    *,
    old_text: str,
    new_text: str = "",
) -> str:
    from app.tools.core.paths import _resolve_path
    from app.writing.manuscript import (
        is_manuscript_rel,
        list_section_ids,
        section_id_containing_span,
    )
    from app.writing.signals.prose_path import is_prose_writing_path, section_id_from_path

    sid = section_id_from_path(path)
    if sid:
        return sid
    target = _resolve_path(path)
    if not target.is_file():
        return normalize_section_id("", path=path)
    try:
        disk = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return normalize_section_id("", path=path)
    ids = list_section_ids(disk) if disk else []
    if ids:
        return (
            section_id_containing_span(disk, old_text)
            or section_id_containing_span(disk, new_text)
            or normalize_section_id("", path=path)
        )
    if is_prose_writing_path(path) or is_manuscript_rel(path):
        return FALLBACK_SECTION_ID
    return ""


def _process_l0_open(prior: dict[str, Any] | None) -> bool:
    if not isinstance(prior, dict):
        return False
    raw = prior.get("l0_hits")
    if isinstance(raw, list) and raw:
        return True
    for key in (
        "staccato_uniform",
        "hinge_dense",
        "lore_dump",
        "opening_institution",
    ):
        if prior.get(key):
            return True
    span = prior.get("repair_span")
    if isinstance(span, dict):
        key = str(span.get("key") or "")
        if key in {
            "staccato_uniform",
            "hinge_dense",
            "lore_dump",
            "opening_institution",
        }:
            return True
    return False


def _repeat_against_last_applied(
    manifest: dict[str, Any] | None,
    *,
    section_id: str,
    penalty_key: str,
    old_text: str,
) -> bool:
    from app.writing.signals.repair import unproductive_repeat

    sid = normalize_section_id(section_id)
    if not manifest or not sid:
        return False
    section = _budget_root(manifest).get(sid)
    if not isinstance(section, dict):
        return False
    last = section.get("last")
    if not isinstance(last, list):
        return False
    key = normalize_penalty_key(penalty_key)
    for item in reversed(last):
        if not isinstance(item, dict):
            continue
        if normalize_penalty_key(str(item.get("key") or "")) != key:
            continue
        prev_old = str(item.get("old_text") or "")
        if unproductive_repeat(
            {"repair_span": {"old_text": prev_old, "key": key}},
            {"old_text": old_text, "key": key},
        ):
            return True
        break
    return False


def _budget_error(
    *,
    error: str,
    penalty_key: str,
    rewrite_policy: str,
    summary: str,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "error",
        "error": error,
        "penalty_key": penalty_key,
        "rewrite_policy": rewrite_policy,
        "summary": summary,
    }
    payload.update(extra)
    return payload


def check_propose_patch_allowed(
    manifest: dict[str, Any] | None,
    *,
    section_id: str,
    old_text: str,
    prior: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return error payload when patch must stop; None when allowed."""
    from app.writing.signals.repair import REWRITE_PATCH, unproductive_repeat

    sid = normalize_section_id(section_id)
    penalty_key = normalize_penalty_key(resolve_penalty_key(prior, old_text=old_text))

    if sid and apply_miss_streak(manifest, section_id=sid) >= MAX_APPLY_MISS_STREAK:
        return _budget_error(
            error="patch_apply_miss_streak",
            penalty_key=penalty_key,
            rewrite_policy=(
                "rewrite_window"
                if penalty_key == "staccato_uniform"
                else "append_or_stop"
            ),
            summary=(
                f"连续 {MAX_APPLY_MISS_STREAK} 次 patch 未能落盘/清岛：停止 propose_patch。"
                + (
                    "改 draft_section mode=rewrite_window 一次换整窗。"
                    if penalty_key == "staccato_uniform"
                    else "改 mode=append 写新场面，或如实说明本章未交付。"
                )
            ),
            patch_apply_miss_streak=apply_miss_streak(manifest, section_id=sid),
        )

    if isinstance(prior, dict):
        net_raw = prior.get("net_signal")
        if net_raw is not None:
            try:
                net = float(net_raw)
            except (TypeError, ValueError):
                net = None
            if net is not None and net >= 0.0 and not _process_l0_open(prior):
                return _budget_error(
                    error="patch_unnecessary",
                    penalty_key=penalty_key,
                    rewrite_policy="append_or_stop",
                    summary=(
                        "net_signal 已 ≥ 0 且无过程 L0：不要继续 patch。"
                        "篇幅不足用 mode=append；否则收工。"
                    ),
                    net_signal=net,
                )

    if sid and patch_budget_exhausted(
        manifest, section_id=sid, penalty_key=penalty_key
    ):
        attempts = count_patch_attempts(
            manifest, section_id=sid, penalty_key=penalty_key
        )
        total = count_section_patch_total(manifest, section_id=sid)
        if penalty_key == "staccato_uniform":
            policy = "rewrite_window"
            hint = (
                "draft_section mode=rewrite_window：一次替换 repair_span 整窗，"
                "勿再 chip patch。"
            )
        else:
            policy = "append_or_stop"
            hint = "停止 patch。L0 清后 mode=append 加厚；或如实告知未交付。"
        reason = (
            f"本 Turn 对 {penalty_key} 已生效 patch {attempts} 次"
            if attempts >= MAX_PATCHES_PER_PENALTY_KEY
            else f"本 Turn 本章累计生效 patch {total} 次"
        )
        return _budget_error(
            error="patch_budget_exhausted",
            penalty_key=penalty_key,
            rewrite_policy=policy,
            summary=(
                f"{reason}（per-key 上限 {MAX_PATCHES_PER_PENALTY_KEY}，"
                f"本章合计 {MAX_PATCHES_PER_SECTION_TOTAL}）。{hint}"
            ),
            patch_attempts=attempts,
            patch_total=total,
        )

    span = prior.get("repair_span") if isinstance(prior, dict) else None
    if sid and (
        _repeat_against_last_applied(
            manifest,
            section_id=sid,
            penalty_key=penalty_key,
            old_text=old_text,
        )
        or (
            isinstance(span, dict)
            and count_patch_attempts(manifest, section_id=sid, penalty_key=penalty_key) > 0
            and unproductive_repeat(
                prior,
                {"old_text": old_text, "key": penalty_key},
            )
        )
    ):
        policy = (
            "rewrite_window"
            if penalty_key == "staccato_uniform"
            else REWRITE_PATCH
        )
        return _budget_error(
            error="patch_repeat_blocked",
            penalty_key=penalty_key,
            rewrite_policy=policy,
            summary=(
                "同一 repair 岛仍在：old_text 与上轮相同或 overlap ≥12 可见字。"
                "禁止再 propose_patch。"
                + (
                    "改 draft_section mode=rewrite_window，一次写满 repair_span 窗口。"
                    if penalty_key == "staccato_uniform"
                    else "改 draft_section mode=append 写新场面，或收工留到下轮。"
                )
            ),
        )

    return None


def check_rewrite_window_allowed(
    manifest: dict[str, Any] | None,
    *,
    section_id: str,
) -> dict[str, Any] | None:
    sid = normalize_section_id(section_id)
    if not sid or not rewrite_window_exhausted(manifest, section_id=sid):
        return None
    attempts = count_rewrite_window_attempts(manifest, section_id=sid)
    return _budget_error(
        error="rewrite_window_exhausted",
        penalty_key="staccato_uniform",
        rewrite_policy="append_or_stop",
        summary=(
            f"本 Turn mode=rewrite_window 已用 {attempts} 次（上限 "
            f"{MAX_REWRITE_WINDOW_PER_SECTION}）。如实说明本章未交付，留到下轮。"
        ),
        rewrite_window_attempts=attempts,
    )


def note_prose_patch_applied(
    turn_id: object | None,
    session_id: object | None,
    *,
    path: str,
    old_text: str,
    prior: dict[str, Any] | None,
    section_id: str = "",
) -> None:
    if turn_id is None:
        return
    from app.tools.core.writing_tools import _read_manifest, _write_manifest

    manifest = _read_manifest(turn_id, session_id=session_id) or {}
    sid = normalize_section_id(section_id or resolve_section_for_prose_patch(path, old_text=old_text))
    if not sid:
        return
    record_patch_attempt(
        manifest,
        section_id=sid,
        penalty_key=resolve_penalty_key(prior, old_text=old_text),
        old_text=old_text,
    )
    _write_manifest(turn_id, manifest, session_id=session_id)


def note_prose_patch_apply_miss(
    turn_id: object | None,
    session_id: object | None,
    *,
    path: str,
    old_text: str = "",
    section_id: str = "",
) -> None:
    if turn_id is None:
        return
    from app.tools.core.writing_tools import _read_manifest, _write_manifest

    manifest = _read_manifest(turn_id, session_id=session_id) or {}
    sid = normalize_section_id(
        section_id or resolve_section_for_prose_patch(path, old_text=old_text)
    )
    if not sid:
        return
    record_apply_miss(manifest, section_id=sid)
    _write_manifest(turn_id, manifest, session_id=session_id)
