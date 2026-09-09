"""signals 组装与工具挂载。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.writing.signals.prefs_loader import _module as _writing_prefs

normalize_fragment = _writing_prefs().normalize_fragment

from app.controller.session_context import load_session_owner_user_id, load_session_work
from app.writing.focus import infer_focus_section_id
from app.writing.manuscript import (
    extract_section,
    is_manuscript_rel,
    list_section_ids,
    load_manuscript_doc,
    section_id_containing_span,
)
from app.writing.outline_arc import extract_outline_job
from app.writing.signals.persist import persist_fragment_evaluation
from app.writing.signals.bank import find_platform_exemplar
from app.writing.signals.prefs_store import platform_prefs_payload
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
    """patch 后挂 writing_signals。
    
    参数:
        result/tool_name/arguments/session/turn。
    
    返回:
        None（原地修改 result）。"""
    if result.get("writing_signals"):
        return
    if result.get("error") or str(result.get("status") or "") == "error":
        return

    path = ""
    old_text = ""
    new_text = ""
    arg_fragment: str | None = None

    if tool_name == "propose_patch":
        status = str(result.get("status") or "")
        if status == "pending" and not result.get("auto_applied"):
            return
        if status not in {"applied", "pending"}:
            return
        path = str(result.get("path") or arguments.get("path") or "")
        old_text = str(result.get("old_text") or arguments.get("old_text") or "")
        new_text = str(result.get("new_text") or arguments.get("new_text") or "")
        arg_fragment = arguments.get("fragment")
    elif tool_name == "apply_patch":
        if str(result.get("status") or "") != "applied":
            return
        path = str(result.get("path") or arguments.get("path") or "")
        old_text = str(arguments.get("old_text") or result.get("old_text") or "")
        new_text = str(arguments.get("new_text") or result.get("new_text") or "")
        arg_fragment = arguments.get("fragment")
    else:
        return

    if not is_prose_writing_path(path):
        return

    section_id, chapter = _chapter_text_for_patch(
        path,
        old_text=old_text,
        new_text=new_text,
        section_hint=str(arguments.get("section_id") or result.get("section_id") or ""),
    )
    if not chapter.strip():
        return

    fragment = _inherit_declared_fragment(
        turn_id=turn_id,
        session_id=session_id,
        section_id=section_id,
        argument=arg_fragment,
    )
    signals = await build_writing_signals(
        chapter,
        fragment=fragment,
        section_id=section_id,
        session_id=session_id,
        turn_id=turn_id,
        persist=True,
    )
    result["writing_signals"] = signals
    if section_id:
        result["section_id"] = section_id
        _upsert_section_signal_prior(
            turn_id=turn_id,
            session_id=session_id,
            section_id=section_id,
            signals=signals,
            chapter_text=chapter,
        )
    penalties = signals.get("penalties") if isinstance(signals, dict) else None
    hits = {
        str(item.get("key") or "")
        for item in (penalties or [])
        if isinstance(item, dict) and item.get("hit")
    }
    for key in (
        "staccato_uniform",
        "hinge_dense",
        "lore_dump",
        "opening_institution",
    ):
        if key in hits:
            result[key] = True
        else:
            result.pop(key, None)
    frag = signals.get("fragment")
    if isinstance(frag, dict):
        result["fragment"] = frag.get("declared") or frag.get("detected")
    elif frag:
        result["fragment"] = frag


def _read_workspace_text(path: str) -> str:
    from app.tools.core.paths import _resolve_path

    rel = (path or "").strip()
    if not rel:
        return ""
    target = _resolve_path(rel)
    if not target.is_file():
        return ""
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _chapter_text_for_patch(
    path: str,
    *,
    old_text: str,
    new_text: str,
    section_hint: str,
) -> tuple[str, str]:
    """Locate the chapter body on disk after apply. Never return isolated new_text."""
    disk = _read_workspace_text(path)
    sid = (section_hint or "").strip() or section_id_from_path(path)
    ids = list_section_ids(disk) if disk else []
    if not sid and (is_manuscript_rel(path) or ids):
        sid = section_id_containing_span(disk, new_text) or section_id_containing_span(
            disk, old_text
        )
    if sid and ids:
        body = extract_section(disk, sid)
        if body and body.strip():
            return sid, body
        return sid, ""
    if ids:
        # Monofile with chapters but span didn't uniquely map — do not score the book.
        return sid, ""
    if disk.strip():
        return sid, disk
    return sid, ""


def _inherit_declared_fragment(
    *,
    turn_id: object | None,
    session_id: object | None,
    section_id: str,
    argument: object,
) -> str | None:
    """Prefer the chapter's draft-time fragment over a patch-local guess."""
    stored = _manifest_section_row(turn_id, session_id, section_id)
    if stored:
        frag = stored.get("fragment")
        if isinstance(frag, dict):
            declared = frag.get("declared")
            if declared:
                return str(declared)
        elif frag:
            return str(frag)
    if argument is None or str(argument).strip() == "":
        return None
    return str(argument)


def _manifest_section_row(
    turn_id: object | None,
    session_id: object | None,
    section_id: str,
) -> dict[str, Any] | None:
    if not turn_id or not section_id:
        return None
    from app.tools.core.paths import _resolve_path

    tid = str(turn_id)
    candidates = [f".agent/work/turns/{tid}.json"]
    if session_id is not None:
        candidates.append(
            f".agent/sessions/{session_id}/turns/{tid}/manifest.json"
        )
    for rel in candidates:
        target = _resolve_path(rel)
        if not target.is_file():
            continue
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        row = (data.get("section_drafts") or {}).get(section_id)
        if isinstance(row, dict):
            return row
    return None


def _upsert_section_signal_prior(
    *,
    turn_id: object | None,
    session_id: object | None,
    section_id: str,
    signals: dict[str, Any],
    chapter_text: str = "",
) -> None:
    if not turn_id or not section_id or not isinstance(signals, dict):
        return
    del session_id
    from app.tools.core.paths import _resolve_path

    tid = str(turn_id)
    rel = f".agent/work/turns/{tid}.json"
    target = _resolve_path(rel)
    data: dict[str, Any]
    if target.is_file():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = {}
        data = loaded if isinstance(loaded, dict) else {}
    else:
        data = {}
    drafts = data.setdefault("section_drafts", {})
    row = drafts.get(section_id) if isinstance(drafts.get(section_id), dict) else {}
    if signals.get("repair_span"):
        row["repair_span"] = signals["repair_span"]
    else:
        row.pop("repair_span", None)
    if signals.get("rewrite_policy"):
        row["rewrite_policy"] = signals["rewrite_policy"]
    if signals.get("composite") is not None:
        row["composite"] = signals["composite"]
    frag = signals.get("fragment")
    declared = frag.get("declared") if isinstance(frag, dict) else frag
    if declared:
        row["fragment"] = declared
    from app.writing.signals.repair import process_l0_hits

    flags = {
        key: True
        for key in (
            "staccato_uniform",
            "hinge_dense",
            "lore_dump",
            "opening_institution",
        )
        if signals.get(key)
    }
    row["l0_hits"] = process_l0_hits(signals.get("penalties"), flags=flags)
    if signals.get("net_signal") is not None:
        row["net_signal"] = signals["net_signal"]
    from app.writing.text_metrics import draft_length_fields, visible_chars

    if chapter_text.strip():
        length = draft_length_fields(chapter_text, "")
        row["visible_chars"] = int(length.get("visible_chars") or visible_chars(chapter_text))
        row["length_short"] = bool(length.get("length_short"))
    drafts[section_id] = row
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


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
    return ""


async def build_writing_signals(
    text: str,
    *,
    fragment: str | None,
    section_id: str = "",
    session_id: object | None = None,
    turn_id: object | None = None,
    persist: bool = True,
    turn_user_text: str = "",
) -> dict[str, Any]:
    """构建完整 signals。"""
    from app.writing.chapter_role import cold_start_score_fragment, resolve_chapter_role
    from app.writing.work_mode import load_style_gains, resolve_work_mode, work_mode_label
    from app.writing.signals.prefs_loader import _module as _writing_prefs

    platform_prefs_payload = _writing_prefs().platform_prefs_payload

    owner_id, work_id = await _resolve_owner_and_work(session_id)
    outline = ""
    try:
        from app.tools.core.paths import _resolve_path

        op = _resolve_path("outline.md")
        if op.is_file():
            outline = op.read_text(encoding="utf-8")
    except OSError:
        outline = ""
    work_mode, mode_source = resolve_work_mode(turn_user_text, outline=outline)
    style_gains = load_style_gains(work_mode=work_mode)
    # Weights + signal gains live in writing tools (writing_prefs.json), not Settings.
    prefs = platform_prefs_payload(work_mode=work_mode, style_gains=style_gains)
    space = await load_metric_space(
        owner_user_id=owner_id, work_id=work_id, work_mode=work_mode
    )
    duty = _chapter_duty(section_id)
    role = resolve_chapter_role(
        section_id=section_id or "",
        message=turn_user_text,
        duty=duty,
        work_mode=work_mode,
    )
    declared = normalize_fragment(
        cold_start_score_fragment(
            fragment, duty=duty, role=role, work_mode=work_mode
        )
    )
    prior = _manifest_section_row(turn_id, session_id, section_id)
    scored = score_writing_fragment(
        text,
        fragment_declared=declared,
        section_id=section_id,
        prefs=prefs,
        space=space,
        prior=prior,
        chapter_position=str(role.get("chapter_position") or ""),
    )
    # 假高潮只跟纲上的这场，不跟发明的章类型。
    duty_conflict = bool(
        scored["fragment"]["declared"] == "climax_beat"
        and duty
        and any(k in duty for k in ("铺垫", "加压", "过日子", "立人"))
    )

    from app.writing.outline_arc import STYLE_CONTRACT_TEMPLATE_VERSION
    from app.settings import settings

    model_id = str(getattr(settings, "model_name", "") or "").strip()
    block: dict[str, Any] = {
        "prefs_scope": "platform",
        "work_mode": work_mode,
        "work_mode_source": mode_source,
        "work_mode_label": work_mode_label(work_mode),
        "chapter_position": role.get("chapter_position"),
        "chapter_kind": role.get("chapter_kind") if duty else None,
        "chapter_position_label": role.get("chapter_position_label"),
        "chapter_kind_label": role.get("chapter_kind_label") if duty else None,
        "style_gains": prefs.get("style_gains"),
        "preset": prefs.get("preset_label", "balanced"),
        "schema_version": prefs.get("schema_version", 1),
        "template_version": STYLE_CONTRACT_TEMPLATE_VERSION,
        "prefs_updated_at": None,
        "weight_set_version": (
            f"platform:{work_mode}:{prefs.get('schema_version', 1)}:"
            f"{space_stamp(space)}"
        ),
        "chapter_duty": duty,
        "duty_conflict": duty_conflict,
        **scored,
    }
    if model_id:
        block["model_id"] = model_id

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
    """rubric 工具：返回当前 work_mode 下平台维度权重与 signal 表。"""
    from app.writing.chapter_role import cold_start_score_fragment, resolve_chapter_role
    from app.writing.work_mode import (
        fragment_obligations,
        load_style_gains,
        resolve_work_mode,
        work_mode_label,
    )
    from app.writing.signals.prefs_loader import _module as _writing_prefs

    platform_prefs_payload = _writing_prefs().platform_prefs_payload
    owner_id, work_id = await _resolve_owner_and_work(session_id)
    turn_user_text = str(_kwargs.get("turn_user_text") or "")
    work_mode, mode_source = resolve_work_mode(turn_user_text)
    style_gains = load_style_gains(work_mode=work_mode)
    prefs = platform_prefs_payload(work_mode=work_mode, style_gains=style_gains)
    flatten = _writing_prefs().flatten_fragment_signals
    duty = _chapter_duty(section_id)
    role = resolve_chapter_role(
        section_id=section_id or "",
        message=turn_user_text,
        duty=duty,
        work_mode=work_mode,
    )
    declared = normalize_fragment(
        cold_start_score_fragment(
            fragment, duty=duty, role=role, work_mode=work_mode
        )
    )
    weights = (prefs.get("fragment_weights") or {}).get(declared) or {}
    if not weights:
        weights = (prefs.get("fragment_weights") or {}).get("mixed") or {}
    space = await load_metric_space(
        owner_user_id=owner_id, work_id=work_id, work_mode=work_mode
    )
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
    mode_label = work_mode_label(work_mode)
    obligations = fragment_obligations(work_mode)
    kind_obl = str(role.get("obligation") or "")
    return {
        "fragment": declared,
        "work_mode": work_mode,
        "work_mode_source": mode_source,
        "work_mode_label": mode_label,
        "chapter_position": role.get("chapter_position"),
        "chapter_kind": role.get("chapter_kind") if duty else None,
        "chapter_position_label": role.get("chapter_position_label"),
        "chapter_kind_label": role.get("chapter_kind_label") if duty else None,
        "style_gains": prefs.get("style_gains"),
        "chapter_duty": duty,
        "prefs_scope": "platform",
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
            "权重在写作工具内按 work_mode 切换，不在设置页",
            (
                f"work_mode={work_mode}（{mode_label}）· "
                f"fragment={declared}（评分切片，不是章职）"
            ),
            (kind_obl if duty else "")
            or obligations.get(declared, obligations["mixed"]),
            "拟合该类范本原型的节奏与质地，禁止搬用其故事核",
            "有 repair_span 时同轮 propose_patch；多轮空问收成一两句或动手，勿改成旁白",
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
    """evaluate 工具。
    
    参数:
        fragment/text/section等。
    
    返回:
        dict。"""
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
    if turn_id is not None:
        from app.tools.core.writing_tools import _read_manifest
        from app.writing.patch_budget import check_repair_tools_blocked

        manifest = _read_manifest(turn_id, session_id=session_id) or {}
        sid = str(section_id or "").strip()
        if not sid:
            drafts = manifest.get("section_drafts")
            if isinstance(drafts, dict) and drafts:
                sid = next(iter(drafts))
        row = None
        if sid:
            drafts = manifest.get("section_drafts")
            if isinstance(drafts, dict):
                raw = drafts.get(sid)
                row = raw if isinstance(raw, dict) else None
            blocked = check_repair_tools_blocked(
                manifest, section_id=sid, prior=row
            )
            if blocked:
                blocked.setdefault("status", "error")
                return blocked
    signals = await build_writing_signals(
        body,
        fragment=fragment,
        section_id=section_id,
        session_id=session_id,
        turn_id=turn_id,
        persist=True,
        turn_user_text=str(_kwargs.get("turn_user_text") or ""),
    )
    return {"writing_signals": signals, "status": "evaluated"}


LAB_TEXT_MAX_CHARS = 50_000


class WritingLabError(ValueError):
    """Lab 错误。
    
    参数:
        code/message。"""
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def overlay_lab_prefs(overlay: dict[str, Any] | None) -> dict[str, Any]:
    """Lab prefs 覆盖。
    
    参数:
        overlay。
    
    返回:
        dict。"""
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
    """Ops sandbox 评分。
    
    参数:
        text/fragment/slug/prefs。
    
    返回:
        dict。"""
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
    space = load_platform_space(str(prefs.get("work_mode") or "literary"))
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
