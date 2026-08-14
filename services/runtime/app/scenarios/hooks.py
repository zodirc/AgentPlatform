"""Named scenario hooks.

Fixed slots only — Profile.hooks maps slot → implementation name.
Implementations live in writing/collab modules; this registry is the sole
dispatch surface (no ``if scenario == …`` at call sites).
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

# name → callable
_REGISTRY: dict[str, Callable[..., Any]] = {}


def register(name: str, fn: Callable[..., Any]) -> None:
    key = (name or "").strip()
    if not key:
        raise ValueError("hook implementation name required")
    _REGISTRY[key] = fn


def resolve(name: str | None) -> Callable[..., Any] | None:
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
    """Fail-fast at Profile load for unknown slots or missing implementations."""
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
        from app.writing.continuity import (
            extract_continuity_candidates,
            write_pending_candidates,
        )
        from app.writing.focus import infer_focus_section_id
        from app.writing.manuscript import extract_section, list_section_ids, load_manuscript_doc

        doc, _rel = load_manuscript_doc()
        if not doc.strip():
            return
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
        if not (chapter_text or "").strip():
            return
        candidates = extract_continuity_candidates(
            chapter_text,
            section_id=focus or "",
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
    if _REGISTRY:
        return
    register("writing_cards", _writing_cards_composer)
    register("collab_orchestrator", _collab_orchestrator)
    register("collab_gap_hint", _collab_gap_hint)
    register("writing_continuity", _writing_continuity)
    register("writing_focus", _writing_focus_bookmark)


ensure_builtins_registered()
