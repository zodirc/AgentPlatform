"""本 Work 已修好的拍：sidecar 进 volatile，签名进 overlay 原型。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from app.writing.signals.prefs_loader import _module as _writing_prefs
from app.writing.signals.repair import is_l0_weak, l0_penalty_hits, penalty_hits
from app.writing.signals.spec import infer_fragment_from_duty
from app.writing.signals.windows import TextWindow
from app.writing.text_metrics import visible_chars

normalize_fragment = _writing_prefs().normalize_fragment

logger = logging.getLogger(__name__)

BEAT_MIN_VISIBLE = 80
BEAT_MAX_VISIBLE = 360
BEATS_BLOCK_MAX = 420
OVERLAY_CAP_PER_FRAGMENT = 4
_SIDECAR = Path(".agent") / "work" / "local_beats.json"


def clip_visible(text: str, *, max_vis: int = BEAT_MAX_VISIBLE) -> str:
    """按实体文字截到 max_vis。"""
    acc: list[str] = []
    vis = 0
    for ch in text or "":
        nxt = vis + (0 if ch.isspace() else 1)
        if nxt > max_vis:
            break
        acc.append(ch)
        vis = nxt
    return "".join(acc).strip()


def beat_window_payload(
    text: str,
    *,
    window: TextWindow | None = None,
) -> dict[str, Any] | None:
    """从最弱窗或全文抽出可晋升拍（80–360 实体字）。"""
    src = (window.text if window is not None else text) or ""
    clipped = clip_visible(src.strip(), max_vis=BEAT_MAX_VISIBLE)
    vis = visible_chars(clipped)
    if vis < BEAT_MIN_VISIBLE:
        return None
    return {"text": clipped, "visible_chars": vis}


def local_beats_path(workspace_root: Path | None = None) -> Path:
    """sidecar 路径。"""
    from app.settings import settings

    root = Path(workspace_root or settings.workspace_root).resolve()
    return root / _SIDECAR


def load_local_beats(workspace_root: Path | None = None) -> list[dict[str, Any]]:
    """读本 Work 已晋升拍（StartTurn 冻结用）。"""
    path = local_beats_path(workspace_root)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("beats") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        body = str(item.get("text") or "").strip()
        if visible_chars(body) < BEAT_MIN_VISIBLE:
            continue
        out.append(
            {
                "fragment": normalize_fragment(str(item.get("fragment") or "mixed")),
                "section_id": str(item.get("section_id") or ""),
                "text": clip_visible(body),
            }
        )
    return out


def write_local_beats(
    beats: list[dict[str, Any]],
    *,
    workspace_root: Path | None = None,
) -> None:
    """写 sidecar。Turn 内不改；仅 post_turn。"""
    path = local_beats_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "beats": [
            {
                "fragment": str(b.get("fragment") or "mixed"),
                "section_id": str(b.get("section_id") or ""),
                "text": str(b.get("text") or ""),
            }
            for b in beats
            if str(b.get("text") or "").strip()
        ]
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def clear_local_beats(*, workspace_root: Path | None = None) -> None:
    """occupy=fresh 时丢掉上一篇 sidecar，避免灌进新篇 volatile。"""
    write_local_beats([], workspace_root=workspace_root)


def format_local_beats_block(
    message: str,
    *,
    workspace_root: Path | None = None,
    fragment: str | None = None,
) -> str:
    """volatile 块：Writing spec 之后。总帽 BEATS_BLOCK_MAX。新篇不灌上一篇的拍。"""
    from app.writing.occupy import wants_new_piece

    if wants_new_piece(message or ""):
        return ""
    beats = load_local_beats(workspace_root)
    if not beats:
        return ""
    wanted = normalize_fragment(
        fragment or infer_fragment_from_duty(message or "") or "mixed"
    )
    chosen = next((b for b in beats if b["fragment"] == wanted), None)
    if chosen is None:
        chosen = next((b for b in beats if b["fragment"] == "mixed"), beats[0])
    body = clip_visible(str(chosen.get("text") or ""), max_vis=280)
    if visible_chars(body) < BEAT_MIN_VISIBLE:
        return ""
    frag = chosen.get("fragment") or "mixed"
    section = chosen.get("section_id") or ""
    head = "## Local beats"
    lines = [
        head,
        "本作品已修好的拍（只学节奏/质地，禁止搬情节或整段抄）。",
        f"### {frag}" + (f" · `{section}`" if section else ""),
        body,
    ]
    text = "\n".join(lines)
    return text if len(text) <= BEATS_BLOCK_MAX else text[: BEATS_BLOCK_MAX - 1] + "…"


def pick_promote_payload(evaluations: list[dict[str, Any]]) -> dict[str, Any] | None:
    """同章：先有 L0 负例，再取第一次 L0 灭掉的拍。不含首稿直接当金标。"""
    by_section: dict[str, list[dict[str, Any]]] = {}
    for row in evaluations:
        sid = str(row.get("section_id") or "_")
        by_section.setdefault(sid, []).append(row)
    for section_id, rows in by_section.items():
        ordered = sorted(
            rows,
            key=lambda r: str(r.get("created_at") or ""),
        )
        had_l0 = False
        first_composite: float | None = None
        for row in ordered:
            signals = row.get("writing_signals")
            if not isinstance(signals, dict):
                continue
            composite = signals.get("composite")
            try:
                comp = float(composite) if composite is not None else None
            except (TypeError, ValueError):
                comp = None
            if first_composite is None and comp is not None:
                first_composite = comp
            length_short = bool((signals.get("length_fields") or {}).get("length_short"))
            if penalty_hits(signals.get("penalties")):
                if l0_penalty_hits(signals.get("penalties")):
                    had_l0 = True
                continue
            if is_l0_weak(
                net=signals.get("net_signal"),
                penalties=signals.get("penalties"),
                length_short=length_short,
            ):
                continue
            if not had_l0:
                continue
            beat = signals.get("beat_window")
            text = ""
            if isinstance(beat, dict):
                text = str(beat.get("text") or "").strip()
            text = clip_visible(text)
            if visible_chars(text) < BEAT_MIN_VISIBLE:
                continue
            delta = 0.0
            if first_composite is not None and comp is not None:
                delta = comp - first_composite
            if delta < 0:
                continue
            weight = max(0.5, min(2.0, 1.0 + delta))
            return {
                "section_id": section_id if section_id != "_" else "",
                "fragment": normalize_fragment(
                    str(row.get("fragment_declared") or "mixed")
                ),
                "text": text,
                "weight": round(weight, 4),
                "evaluation_id": row.get("id"),
                "delta_composite": round(delta, 4),
            }
    return None


async def maybe_promote_local_beats(*, turn_id: UUID, session_id: UUID | None) -> None:
    """Turn 收尾：L0 清掉的拍写入 sidecar + work overlay。不改本 Turn volatile。"""
    from app.tenant_context import current_ops_eval, current_owner_user_id, current_work_id

    if current_ops_eval():
        return
    work_id = current_work_id()
    owner_id = current_owner_user_id()
    if work_id is None:
        return
    rows = await _load_turn_evaluations(turn_id)
    picked = pick_promote_payload(rows)
    if picked is None:
        return
    logger.info(
        "promote local beat turn_id=%s session_id=%s section=%s fragment=%s",
        turn_id,
        session_id,
        picked.get("section_id"),
        picked.get("fragment"),
    )
    beats = [
        b
        for b in load_local_beats()
        if not (
            b.get("fragment") == picked["fragment"]
            and b.get("section_id") == picked["section_id"]
        )
    ]
    beats.insert(
        0,
        {
            "fragment": picked["fragment"],
            "section_id": picked["section_id"],
            "text": picked["text"],
        },
    )
    write_local_beats(beats[: OVERLAY_CAP_PER_FRAGMENT * 2])
    if owner_id is None:
        return
    try:
        from app.writing.signals.space_store import upsert_work_overlay_beat

        await upsert_work_overlay_beat(
            owner_user_id=owner_id,
            work_id=work_id,
            fragment=picked["fragment"],
            section_id=picked["section_id"],
            text=picked["text"],
            weight=float(picked["weight"]),
            promoted_from_eval_id=picked.get("evaluation_id"),
        )
    except Exception:
        logger.exception("promote overlay beat failed turn_id=%s", turn_id)


async def _load_turn_evaluations(turn_id: UUID) -> list[dict[str, Any]]:
    from app.db.pool import get_pool

    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, section_id, fragment_declared, writing_signals, created_at
        FROM writing_fragment_evaluations
        WHERE turn_id = $1
        ORDER BY created_at ASC
        """,
        turn_id,
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        signals = row["writing_signals"]
        if isinstance(signals, str):
            try:
                signals = json.loads(signals)
            except json.JSONDecodeError:
                signals = {}
        out.append(
            {
                "id": row["id"],
                "section_id": row["section_id"],
                "fragment_declared": row["fragment_declared"],
                "writing_signals": signals if isinstance(signals, dict) else {},
                "created_at": str(row["created_at"] or ""),
            }
        )
    return out
