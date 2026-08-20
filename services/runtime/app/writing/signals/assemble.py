from __future__ import annotations

from typing import Any
from uuid import UUID

from app.writing.signals.prefs_loader import _module as _writing_prefs

normalize_fragment = _writing_prefs().normalize_fragment

from app.controller.session_context import load_session_owner_user_id, load_session_work
from app.writing.focus import infer_focus_section_id
from app.writing.manuscript import extract_section, list_section_ids, load_manuscript_doc
from app.writing.outline_arc import extract_outline_job
from app.writing.signals.persist import persist_fragment_evaluation
from app.writing.signals.bank import find_platform_exemplar
from app.writing.signals.prefs_store import load_account_prefs, platform_prefs_payload
from app.writing.signals.prose_path import is_prose_writing_path, section_id_from_path
from app.writing.signals.scorer import score_writing_fragment
from app.writing.signals.space import load_platform_space, space_stamp
from app.writing.signals.space_store import load_metric_space


async def maybe_attach_prose_writing_signals(
    result: dict[str, Any],
    *,
    tool_name: str,
    arguments: dict[str, Any],
    session_id: object | None = None,
    turn_id: object | None = None,
) -> None:
    """Attach writing_signals to prose patch tool results.

    Callers gate on Profile.attach_writing_signals — no scenario_id branch here.
    """
    if result.get("writing_signals"):
        return
    if result.get("error") or str(result.get("status") or "") == "error":
        return

    path = ""
    text = ""
    fragment: str | None = None

    if tool_name == "propose_patch":
        status = str(result.get("status") or "")
        if status == "pending" and not result.get("auto_applied"):
            return
        if status not in {"applied", "pending"}:
            return
        path = str(result.get("path") or arguments.get("path") or "")
        text = str(result.get("new_text") or arguments.get("new_text") or "")
        fragment = arguments.get("fragment")
    elif tool_name == "apply_patch":
        if str(result.get("status") or "") != "applied":
            return
        path = str(result.get("path") or arguments.get("path") or "")
        text = str(arguments.get("new_text") or result.get("new_text") or "")
        fragment = arguments.get("fragment")
    else:
        return

    if not is_prose_writing_path(path) or not text.strip():
        return

    section_id = section_id_from_path(path)
    signals = await build_writing_signals(
        text,
        fragment=fragment,
        section_id=section_id,
        session_id=session_id,
        turn_id=turn_id,
        persist=True,
    )
    result["writing_signals"] = signals
    frag = signals.get("fragment")
    if isinstance(frag, dict):
        result["fragment"] = frag.get("declared") or frag.get("detected")
    elif frag:
        result["fragment"] = frag


async def _resolve_owner_and_work(session_id: object | None) -> tuple[UUID | None, UUID | None]:
    if session_id is None:
        return None, None
    try:
        sid = session_id if isinstance(session_id, UUID) else UUID(str(session_id))
    except (TypeError, ValueError):
        return None, None
    work_id, _, owner_id, _ = await load_session_work(sid)
    if owner_id is None:
        owner_id = await load_session_owner_user_id(sid)
    return owner_id, work_id


def _chapter_duty(section_id: str) -> str:
    doc, _ = load_manuscript_doc()
    outline = ""
    try:
        from app.tools.core.paths import _resolve_path

        outline_path = _resolve_path("outline.md")
        if outline_path.is_file():
            outline = outline_path.read_text(encoding="utf-8")
    except OSError:
        outline = ""
    if outline.strip():
        job = extract_outline_job(outline, section_id)
        if job:
            return job[:200]
    if doc.strip() and section_id:
        ids = list_section_ids(doc)
        focus = section_id if section_id in ids else (ids[-1] if ids else "")
        if focus:
            chunk = extract_section(doc, focus)
            if chunk.strip():
                return f"章节 {focus}"
    return ""


async def build_writing_signals(
    text: str,
    *,
    fragment: str | None,
    section_id: str = "",
    session_id: object | None = None,
    turn_id: object | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    owner_id, work_id = await _resolve_owner_and_work(session_id)
    prefs = await load_account_prefs(owner_id)
    space = await load_metric_space(owner_user_id=owner_id, work_id=work_id)
    declared = normalize_fragment(fragment)
    scored = score_writing_fragment(
        text,
        fragment_declared=declared,
        section_id=section_id,
        prefs=prefs,
        space=space,
    )
    duty = _chapter_duty(section_id)
    duty_conflict = False
    if duty and scored["fragment"]["declared"] == "climax_beat":
        if any(k in duty for k in ("铺垫", "加压", "过日子")):
            duty_conflict = True

    block: dict[str, Any] = {
        "prefs_scope": "account",
        "preset": prefs.get("preset_label", "balanced"),
        "schema_version": prefs.get("schema_version", 1),
        "prefs_updated_at": prefs.get("updated_at"),
        "weight_set_version": (
            f"account:{owner_id or 'default'}:{prefs.get('schema_version', 1)}:"
            f"{space_stamp(space)}"
        ),
        "chapter_duty": duty,
        "duty_conflict": duty_conflict,
        **scored,
    }

    evaluation_id: str | None = None
    if persist and owner_id is not None and text.strip():
        try:
            sid = UUID(str(session_id)) if session_id is not None else None
            tid = UUID(str(turn_id)) if turn_id is not None else None
        except (TypeError, ValueError):
            sid, tid = None, None
        evaluation_id = await persist_fragment_evaluation(
            owner_user_id=owner_id,
            work_id=work_id,
            session_id=sid,
            turn_id=tid,
            section_id=section_id,
            fragment_declared=scored["fragment"]["declared"],
            fragment_detected=scored["fragment"]["detected"],
            writing_signals=block,
            text=text,
            feature_schema_id=str((scored.get("exemplar_fit") or {}).get("schema_id") or ""),
            signature=(scored.get("exemplar_fit") or {}).get("signature"),
            prototype_scope=str((scored.get("exemplar_fit") or {}).get("scope") or ""),
            nearest_exemplar_slug=str(
                ((scored.get("exemplar_fit") or {}).get("nearest") or {}).get("id") or ""
            )
            or None,
        )
    if evaluation_id:
        block["evaluation_id"] = evaluation_id
        block["persisted"] = True
    else:
        block["persisted"] = bool(persist and owner_id is not None)
    return block


async def writing_rubric(
    fragment: str,
    section_id: str = "",
    session_id: object | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    owner_id, work_id = await _resolve_owner_and_work(session_id)
    prefs = await load_account_prefs(owner_id)
    declared = normalize_fragment(fragment)
    weights = (prefs.get("fragment_weights") or {}).get(declared) or {}
    if not weights:
        weights = (prefs.get("fragment_weights") or {}).get("mixed") or {}
    flatten = _writing_prefs().flatten_fragment_signals
    duty = _chapter_duty(section_id)
    space = await load_metric_space(owner_user_id=owner_id, work_id=work_id)
    proto = space.prototype(declared)
    bank_titles = []
    if proto is not None:
        for s in proto.neighbors:
            bank_titles.append(
                {
                    "author": s.author,
                    "work": s.work,
                    "beat": s.beat,
                    "slug": s.slug,
                    "scope": s.scope,
                }
            )
    return {
        "fragment": declared,
        "chapter_duty": duty,
        "prefs_scope": "account",
        "preset": prefs.get("preset_label", "balanced"),
        "dimension_weights": weights,
        "signal_penalties": flatten(prefs.get("signal_penalties") or {}, declared),
        "signal_rewards": flatten(prefs.get("signal_rewards") or {}, declared),
        "feature_schema_id": space.schema_id,
        "exemplar_space": {
            "scope": proto.scope if proto else "platform",
            "n": proto.n if proto else 0,
            "medoid": (
                {
                    "author": proto.medoid.author,
                    "work": proto.medoid.work,
                    "beat": proto.medoid.beat,
                }
                if proto and proto.medoid
                else None
            ),
            "neighbors": bank_titles,
        },
        "obligations": [
            "成稿前可先读本工具；成稿后以 writing_signals 为准",
            f"本场片段类型：{declared}",
            "拟合该类范本原型的节奏与质地，禁止搬用其故事核",
            "低 net_signal 时同轮 propose_patch 修补 repair_span，勿整章再 draft_section，勿另开 Turn",
        ],
    }


async def evaluate_writing_fragment(
    fragment: str,
    text: str = "",
    section_id: str = "",
    session_id: object | None = None,
    turn_id: object | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    body = (text or "").strip()
    if not body and section_id:
        doc, _ = load_manuscript_doc()
        if doc.strip():
            ids = list_section_ids(doc)
            sid = section_id if section_id in ids else infer_focus_section_id("", ids) or ""
            if sid:
                body = extract_section(doc, sid)
                section_id = sid
    if not body:
        return {"error": "missing_text", "summary": "Provide text or a valid section_id"}
    signals = await build_writing_signals(
        body,
        fragment=fragment,
        section_id=section_id,
        session_id=session_id,
        turn_id=turn_id,
        persist=True,
    )
    return {"writing_signals": signals, "status": "evaluated"}


LAB_TEXT_MAX_CHARS = 50_000


class WritingLabError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def overlay_lab_prefs(overlay: dict[str, Any] | None) -> dict[str, Any]:
    """Platform defaults plus optional Ops trial knobs. Never persisted."""
    prefs = platform_prefs_payload()
    if not overlay or not isinstance(overlay, dict):
        return prefs
    wp = _writing_prefs()
    fw = overlay.get("fragment_weights")
    if isinstance(fw, dict) and fw:
        merged = dict(prefs["fragment_weights"])
        for frag in wp.FRAGMENT_TYPES:
            row = fw.get(frag)
            if isinstance(row, dict):
                merged[frag] = wp.normalize_row(row)
        prefs["fragment_weights"] = merged
        prefs["preset_label"] = "custom"
    if overlay.get("signal_penalties") is not None:
        prefs["signal_penalties"] = wp.coerce_signal_table(
            overlay.get("signal_penalties"),
            template=wp.PLATFORM_SIGNAL_PENALTIES,
            field="signal_penalties",
        )
        prefs["preset_label"] = "custom"
    if overlay.get("signal_rewards") is not None:
        prefs["signal_rewards"] = wp.coerce_signal_table(
            overlay.get("signal_rewards"),
            template=wp.PLATFORM_SIGNAL_REWARDS,
            field="signal_rewards",
        )
        prefs["preset_label"] = "custom"
    return prefs


async def score_writing_lab(
    *,
    text: str | None = None,
    fragment: str | None = None,
    slug: str | None = None,
    prefs_overlay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ops sandbox: platform prefs + platform prototypes; never persist."""
    source: dict[str, Any] = {"kind": "upload"}
    body = (text or "").strip()
    declared = fragment
    slug_key = (slug or "").strip()
    if slug_key:
        sample = find_platform_exemplar(slug=slug_key)
        if sample is None:
            raise WritingLabError("exemplar_not_found", "Unknown exemplar slug")
        if not body:
            body = sample.text
        if not declared:
            declared = sample.fragment
        source = {
            "kind": "exemplar",
            "fragment": sample.fragment,
            "slug": sample.slug,
            "author": sample.author,
            "work": sample.work,
            "beat": sample.beat,
            "license": sample.license,
        }
    if not body:
        raise WritingLabError("missing_text", "Provide text or an exemplar slug")
    if len(body) > LAB_TEXT_MAX_CHARS:
        raise WritingLabError("text_too_long", f"Text exceeds {LAB_TEXT_MAX_CHARS} characters")

    prefs = overlay_lab_prefs(prefs_overlay)
    space = load_platform_space()
    scored = score_writing_fragment(
        body,
        fragment_declared=declared,
        section_id="",
        prefs=prefs,
        space=space,
    )
    scope = "trial" if prefs.get("preset_label") == "custom" else "platform"
    return {
        "source": source,
        "persisted": False,
        "prefs_scope": scope,
        "preset": prefs.get("preset_label", "balanced"),
        "schema_version": prefs.get("schema_version", 1),
        "writing_signals": {
            "prefs_scope": scope,
            "preset": prefs.get("preset_label", "balanced"),
            "schema_version": prefs.get("schema_version", 1),
            "chapter_duty": "",
            "duty_conflict": False,
            "persisted": False,
            **scored,
        },
    }
