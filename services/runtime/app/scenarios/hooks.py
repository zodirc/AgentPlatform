"""命名场景钩子注册与分发。

固定槽位（``HOOK_SLOTS``）—— Profile.hooks 映射 slot → 实现名。
具体实现分散在 writing/collab 等模块；本模块是唯一 dispatch 面，
调用方不得 ``if scenario == …`` 分支。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

HOOK_SLOTS = frozenset(
    {
        "system_prompt_composer",
        "volatile_composer",
        "step_checkpoint",
        "post_turn",
        "compact_bookmark",
    }
)
"""Profile 可绑定的固定钩子槽位名集合。"""

# name → callable
_REGISTRY: dict[str, Callable[..., Any]] = {}


def register(name: str, fn: Callable[..., Any]) -> None:
    """注册具名钩子实现，供 Profile.hooks 引用。

    参数:
        name: 实现名（非空字符串）。
        fn: 可调用对象；签名因槽位而异。

    返回:
        None。

    抛出:
        ValueError: ``name`` 为空。
    """
    key = (name or "").strip()
    if not key:
        raise ValueError("hook implementation name required")
    _REGISTRY[key] = fn


def resolve(name: str | None) -> Callable[..., Any] | None:
    """按实现名查找已注册钩子。

    参数:
        name: Profile.hooks 中的实现名；空或仅空白时视为未绑定。

    返回:
        已注册的可调用对象；未绑定时为 None。

    抛出:
        RuntimeError: 名称非空但未注册。
    """
    key = (name or "").strip()
    if not key:
        return None
    fn = _REGISTRY.get(key)
    if fn is None:
        raise RuntimeError(
            f"unknown scenario hook implementation {key!r}; "
            f"known={sorted(_REGISTRY)}"
        )
    return fn


def validate_profile_hooks(hooks: dict[str, str]) -> None:
    """Profile 加载期 fail-fast：校验槽位合法且实现已注册。

    参数:
        hooks: YAML ``hooks`` 段解析后的 slot → 实现名映射。

    返回:
        None。

    抛出:
        ValueError: 未知槽位。
        RuntimeError: 实现名未 ``register``。
    """
    for slot, impl in (hooks or {}).items():
        if slot not in HOOK_SLOTS:
            raise ValueError(
                f"unknown hook slot {slot!r}; allowed={sorted(HOOK_SLOTS)}"
            )
        resolve(impl)  # raises if impl missing


def _writing_cards_composer(
    system_prompt: str, message: str
) -> tuple[str, str, list[tuple[str, dict[str, Any]]]]:
    from app.writing.cards import prepare_writing_system_prompt

    pin = prepare_writing_system_prompt(system_prompt, message)
    return pin.prompt, pin.volatile_block, [("cards.pinned", pin.event_payload())]


def _collab_orchestrator(
    _system_prompt: str, _message: str
) -> tuple[str | None, str, list[tuple[str, dict[str, Any]]]]:
    from app.scenarios.collab_hints import collab_orchestrator_block

    return None, collab_orchestrator_block(), []


def _collab_gap_hint(st: Any, engine_ref: list[Any]) -> None:
    from app.scenarios.collab_hints import apply_collab_gap_hint

    if not engine_ref:
        return
    refreshed = apply_collab_gap_hint(st.volatile_context, st.messages)
    st.volatile_context = refreshed
    engine_ref[0]._volatile_context = refreshed


async def _writing_continuity(state: Any, *, turn_id: Any) -> None:
    """WN1 continuity pending cards (was ``_maybe_write_continuity_pending`` body)."""
    import logging

    logger = logging.getLogger("app.scenarios.hooks")
    try:
        from pathlib import Path

        from app.settings import settings
        from app.writing.continuity import (
            extract_continuity_candidates,
            write_pending_candidates,
        )
        from app.writing.focus import infer_focus_section_id
        from app.writing.manuscript import extract_section, list_section_ids, load_manuscript_doc

        outline_text = ""
        outline_path = Path(settings.workspace_root) / "outline.md"
        if outline_path.is_file():
            try:
                outline_text = outline_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                outline_text = ""

        doc, _rel = load_manuscript_doc()
        if doc.strip():
            available = list_section_ids(doc)
            user_text = ""
            for msg in reversed(state.messages):
                if msg.get("role") != "user":
                    continue
                content = msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            user_text = str(block.get("text") or "")
                            break
                elif isinstance(content, str):
                    user_text = content
                if user_text:
                    break
            focus = infer_focus_section_id(user_text, available) or (
                available[-1] if available else ""
            )
            chapter_text = extract_section(doc, focus) if focus else doc
            if (chapter_text or "").strip():
                candidates = extract_continuity_candidates(
                    chapter_text,
                    section_id=focus or "",
                    outline=outline_text,
                )
                written = write_pending_candidates(
                    candidates,
                    turn_id=str(turn_id),
                )
                if written:
                    logger.info(
                        "wn1 pending continuity cards turn_id=%s count=%s",
                        turn_id,
                        len(written),
                    )
                try:
                    from app.writing.story_state import (
                        apply_mechanical_update,
                        chapter_num,
                        consistency_flags,
                        thread_stale_flags,
                        wild_card_without_consequence,
                    )
                    from app.writing.signals.surface import save_surface
                    from app.writing.editor_notes import (
                        build_editor_note_lines,
                        write_editor_notes,
                    )
                    from app.writing.author_notes import load_author_notes, note_repeats_delta
                    from app.writing.story_state import load_story_state
                    from app.writing.regime import is_author_regime

                    is_author = is_author_regime(
                        user_text, workspace_root=Path(settings.workspace_root)
                    )

                    apply_mechanical_update(
                        chapter_text,
                        section_id=focus or "",
                    )
                    measured = save_surface(focus or "ch", chapter_text)
                    ch_n = chapter_num(focus or "")
                    cons = consistency_flags(chapter_text, section_id=focus or "")
                    stale = thread_stale_flags(current_ch=ch_n)
                    unpaid = wild_card_without_consequence(current_ch=ch_n)
                    state = load_story_state()
                    deltas = []
                    if ch_n is not None:
                        deltas = list((state.get("deltas") or {}).get(str(ch_n)) or [])
                    notes_text = load_author_notes()
                    repeats = False
                    if deltas and notes_text:
                        from app.writing.author_notes import recent_author_notes

                        recents = recent_author_notes(n=1)
                        if recents:
                            repeats = note_repeats_delta(recents[-1], deltas)
                    lines = build_editor_note_lines(
                        section_id=focus or "",
                        measured=measured,
                        consistency=cons,
                        stale=stale,
                        wild_unpaid=unpaid,
                        author_note_repeats_delta=repeats,
                        include_surface=not is_author,
                    )
                    write_editor_notes(focus or "ch", lines)
                except Exception:
                    logger.exception(
                        "writing post_turn sidecars failed turn_id=%s", turn_id
                    )
        from app.writing.signals.beats import maybe_promote_local_beats

        session_id = getattr(state, "session_id", None)
        await maybe_promote_local_beats(turn_id=turn_id, session_id=session_id)
    except Exception:
        logger.exception("wn1 continuity pending failed turn_id=%s", turn_id)


def _writing_focus_bookmark(
    *,
    record: dict[str, Any],
    summary: Any,
    last_user_message: str,
    rows: list[dict[str, Any]],
) -> None:
    from pathlib import Path

    from app.settings import settings
    from app.writing.delivery_gate import (
        looks_like_delivery_playbook,
        manuscript_preview_for_compact,
        strip_delivery_playbook,
    )
    from app.writing.focus import (
        build_writing_bookmark,
        format_writing_bookmark,
        infer_focus_section_id,
        outline_toc_snippet,
    )
    from app.writing.manuscript import list_section_ids, load_manuscript_doc

    doc, _rel = load_manuscript_doc(Path(settings.workspace_root))
    sections = list_section_ids(doc) if doc else []
    focus = infer_focus_section_id(last_user_message, sections)
    if not focus and sections:
        focus = sections[-1]
    recent_user = last_user_message
    if (not recent_user or recent_user.strip() in {"/compact", "compact"}) and rows:
        recent_user = str(rows[0].get("user_input") or "")
        focus = infer_focus_section_id(recent_user, sections) or focus

    narrative = strip_delivery_playbook(getattr(summary, "narrative", "") or "")
    preview = manuscript_preview_for_compact()
    if not narrative or looks_like_delivery_playbook(narrative):
        narrative = preview or str(getattr(summary, "task", "") or "")
    summary.narrative = narrative
    cleaned_decisions = [
        item
        for item in list(getattr(summary, "decisions", None) or [])
        if item and not looks_like_delivery_playbook(str(item))
    ]
    summary.decisions = cleaned_decisions[:8]
    record["last_output_preview"] = (preview or narrative or str(summary.task or ""))[:500]
    record["decisions"] = list(summary.decisions)[:10]
    if preview and focus:
        land = f"稿已落盘 drafts/manuscript.md；focus={focus}"
        if land not in record["decisions"]:
            record["decisions"] = [land, *record["decisions"]][:10]
            summary.decisions = list(record["decisions"])

    bookmark = build_writing_bookmark(
        focus=focus,
        sections=sections,
        outline_toc=outline_toc_snippet(),
        notes=(summary.task or "")[:500],
        last_user=recent_user,
    )
    record["writing_bookmark"] = bookmark
    bookmark_text = format_writing_bookmark(bookmark)
    if summary.narrative:
        summary.narrative = f"{bookmark_text}\n\n{summary.narrative}"[:4000]
    else:
        summary.narrative = bookmark_text[:4000]


def ensure_builtins_registered() -> None:
    """幂等注册内置钩子实现（writing / collab 等）。

    参数:
        无。

    返回:
        None。
    """
    if _REGISTRY:
        return
    register("writing_cards", _writing_cards_composer)
    register("collab_orchestrator", _collab_orchestrator)
    register("collab_gap_hint", _collab_gap_hint)
    register("writing_continuity", _writing_continuity)
    register("writing_focus", _writing_focus_bookmark)


ensure_builtins_registered()
