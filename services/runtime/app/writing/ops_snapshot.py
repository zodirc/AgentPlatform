"""Ops 只读快照：档位对照与本书原型对齐曲线。不进产品 Turn。"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def _report_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "eval" / "reports" / "writing"
        if cand.is_dir() or (parent / "eval").is_dir():
            return cand
    try:
        from app.settings import settings

        return Path(settings.workspace_root).resolve() / "eval" / "reports" / "writing"
    except Exception:
        return here.parents[min(2, len(here.parents) - 1)] / "eval" / "reports" / "writing"


def _workspace(workspace_root: Path | None = None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.settings import settings

    return Path(settings.workspace_root).resolve()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _choice_entropy(hist: dict[str, dict[str, int]]) -> float:
    ents: list[float] = []
    for bucket in hist.values():
        total = sum(int(v) for v in bucket.values())
        if total <= 0:
            continue
        ent = 0.0
        for n in bucket.values():
            p = n / total
            if p > 0:
                ent -= p * math.log2(p)
        ents.append(ent)
    return round(sum(ents) / len(ents), 4) if ents else 0.0


def collect_offline_metrics(*, workspace_root: Path | None = None) -> dict[str, Any]:
    """§5.12 离线指标。读现有 sidecar，不编造章节、不进产品 Turn。"""
    from app.writing.author_state import stance_is_stale
    from app.writing.commitment import choice_history
    from app.writing.manuscript import extract_section, list_section_ids, load_manuscript_doc
    from app.writing.reread import load_retcon_pending
    from app.writing.story_state import chapter_num, load_story_state, overdue_promises
    from app.writing.taste import load_taste_marks
    from app.writing.text_metrics import visible_chars

    root = _workspace(workspace_root)
    doc, _rel = load_manuscript_doc(root)
    ids = list_section_ids(doc) if doc else []
    total_chars = 0
    for sid in ids:
        total_chars += visible_chars(extract_section(doc or "", sid) or "")
    marks = [
        m
        for m in load_taste_marks(workspace_root=root)
        if m.get("source") != "editor"
    ]
    counts = {"yes": 0, "ai": 0, "off": 0, "cut": 0}
    for mark in marks:
        kind = str(mark.get("kind") or "")
        if kind in counts:
            counts[kind] += 1
    per_1k = {
        k: round((v * 1000.0 / total_chars), 4) if total_chars else 0.0
        for k, v in counts.items()
    }
    editor_dir = root / ".agent" / "work" / "editor"
    hard = soft = 0
    by_chapter: list[dict[str, Any]] = []
    if editor_dir.is_dir():
        for path in sorted(editor_dir.glob("*.json")):
            payload = _load_json(path) or {}
            flags = [f for f in (payload.get("flags") or []) if isinstance(f, dict)]
            n_hard = sum(1 for f in flags if f.get("severity") == "hard")
            n_soft = sum(1 for f in flags if f.get("severity") == "soft")
            hard += n_hard
            soft += n_soft
            by_chapter.append(
                {
                    "section_id": payload.get("section_id") or path.stem,
                    "hard": n_hard,
                    "soft": n_soft,
                }
            )
    state = load_story_state(workspace_root=root)
    nums = [chapter_num(i) for i in ids]
    now = max((n for n in nums if n is not None), default=None)
    overdue = overdue_promises(state, current_ch=now)
    deferred = [d for d in (state.get("deferred") or []) if isinstance(d, dict)]
    hist = choice_history(workspace_root=root)
    return {
        "chapter_count": len(ids),
        "visible_chars": total_chars,
        "taste": {"counts": counts, "per_1k_chars": per_1k, "n": len(marks)},
        "editor_flags": {"hard": hard, "soft": soft, "by_chapter": by_chapter},
        "promises_overdue": len(overdue),
        "deferred_alive": len(deferred),
        "author_state_stale": stance_is_stale(workspace_root=root),
        "choice_history_entropy": _choice_entropy(hist),
        "retcon_pending": len(load_retcon_pending(workspace_root=root)),
    }


def work_alignment_curve(*, workspace_root: Path | None = None) -> dict[str, Any]:
    """taste 构建的本书原型 vs 各章；样本 <4 则 ready=False。"""
    from app.writing.manuscript import extract_section, list_section_ids, load_manuscript_doc
    from app.writing.signals.space import fit_signature, load_work_taste_space
    from app.writing.taste import work_prototypes

    root = _workspace(workspace_root)
    samples = work_prototypes(workspace_root=root)
    space = load_work_taste_space(workspace_root=root)
    if space is None or not samples:
        return {
            "ok": True,
            "ready": False,
            "n_samples": len(samples),
            "points": [],
        }
    doc, _rel = load_manuscript_doc(root)
    ids = list_section_ids(doc) if doc else []
    points: list[dict[str, Any]] = []
    for sid in ids:
        body = extract_section(doc or "", sid) or ""
        if not body.strip():
            continue
        fit = fit_signature(body, "mixed", space=space)
        points.append(
            {
                "section_id": sid,
                "alignment": round(float(fit.get("score") or 0.0), 4),
                "scope": fit.get("scope"),
                "n": fit.get("n"),
            }
        )
    return {
        "ok": True,
        "ready": True,
        "n_samples": len(samples),
        "scope": "work",
        "points": points,
    }


def regime_ops_snapshot(*, workspace_root: Path | None = None) -> dict[str, Any]:
    """档位对照页数据：当前档 + 对齐曲线 + 已落盘的基线/利用率报告。"""
    from app.writing.regime import load_regime_override, resolve_regime
    from app.writing.signals.surface import chapter_shape_flags, load_surface_index

    root = _workspace(workspace_root)
    value, source = resolve_regime(workspace_root=root)
    stored = load_regime_override(workspace_root=root)
    return {
        "ok": True,
        "regime": {"value": value, "source": source, "stored": stored},
        "alignment": work_alignment_curve(workspace_root=root),
        "metrics": collect_offline_metrics(workspace_root=root),
        "surface": {
            "index": load_surface_index(workspace_root=root),
            "flags": chapter_shape_flags(workspace_root=root),
        },
        "reports": {
            "utilization": _load_json(_report_dir() / "latest_utilization.json"),
            "baseline": _load_json(_report_dir() / "regime_baseline.json"),
            "l2": _load_json(_report_dir() / "latest_l2.json"),
        },
    }
