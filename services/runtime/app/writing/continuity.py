"""WN1: offline continuity card candidates (docs/30).

Candidates land under ``sources/cards/pending/`` after a writing turn.
They are **never** auto-pinned — ``load_writing_cards`` already skips nothing
named pending if we keep them outside the cards tree OR under pending/ and
exclude that directory from pin selection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.settings import settings

_NAME_RE = re.compile(r"[\u4e00-\u9fff]{2,4}")  # retained for tests/diagnostics
_STATE_LINE_RE = re.compile(
    r"^.{0,80}(?:死了|阵亡|受伤|背叛|离开|归来|登基|退位|决定|答应|拒绝|拔枪|点了点头).{0,80}$",
    re.M,
)
_STOP_NAMES = frozenset(
    {
        "然后",
        "但是",
        "因为",
        "所以",
        "这个",
        "那个",
        "我们",
        "他们",
        "她们",
        "自己",
        "什么",
        "没有",
        "已经",
        "还是",
        "可是",
        "只是",
        "不是",
        "就是",
        "一个",
        "这里",
        "那里",
        "时候",
        "现在",
        "今夜",
        "古城",
    }
)


@dataclass(frozen=True)
class ContinuityCandidate:
    kind: str
    title: str
    body: str
    source_hint: str = ""


def extract_continuity_candidates(
    chapter_text: str,
    *,
    section_id: str = "",
    max_candidates: int = 5,
) -> list[ContinuityCandidate]:
    """Heuristic extraction only — no LLM. Offline / post-turn use (R4)."""
    text = (chapter_text or "").strip()
    if not text:
        return []

    # Prefer 2–3 char tokens before common action verbs (non-overlapping).
    verb_bound = re.compile(
        r"([\u4e00-\u9fff]{2,3})"
        r"(?:拔|点|决|说|道|问|笑|怒|离开|决定|答应|拒绝|阵亡|受伤|背叛|归来)"
    )
    counts: dict[str, int] = {}
    for match in verb_bound.finditer(text):
        name = match.group(1)
        if name in _STOP_NAMES:
            continue
        counts[name] = counts.get(name, 0) + 1

    # Fallback: standalone quoted speakers 「…」前的称呼较少；再扫 2–3 字重复串。
    if not counts:
        for length in (3, 2):
            i = 0
            while i + length <= len(text):
                chunk = text[i : i + length]
                if re.fullmatch(r"[\u4e00-\u9fff]+", chunk) and chunk not in _STOP_NAMES:
                    # Require repetition later via counts aggregation.
                    counts[chunk] = counts.get(chunk, 0) + 1
                i += 1
            # Keep only repeats for fallback noise control.
            counts = {k: v for k, v in counts.items() if v >= 2}
            if counts:
                break

    ranked = sorted(
        counts.items(),
        key=lambda item: (item[1], len(item[0])),
        reverse=True,
    )
    names = [name for name, _count in ranked][:max_candidates]

    state_lines = [ln.strip() for ln in _STATE_LINE_RE.findall(text)][: max_candidates * 2]
    out: list[ContinuityCandidate] = []
    for name in names:
        related = [ln for ln in state_lines if name in ln][:2]
        body_lines = ["## Status snapshot", f"角色：{name}"]
        if section_id:
            body_lines.append(f"章节：{section_id}")
        body_lines.append("## Events")
        if related:
            body_lines.extend(f"- {ln}" for ln in related)
        else:
            body_lines.append("- （待人工确认）")
        out.append(
            ContinuityCandidate(
                kind="character",
                title=name,
                body="\n".join(body_lines) + "\n",
                source_hint=section_id,
            )
        )
    return out


def pending_cards_dir(*, workspace_root: Path | None = None) -> Path:
    root = Path(workspace_root or settings.workspace_root).resolve()
    return (root / "sources" / "cards" / "pending").resolve()


def write_pending_candidates(
    candidates: list[ContinuityCandidate],
    *,
    workspace_root: Path | None = None,
    turn_id: str = "",
) -> list[Path]:
    """Write candidate markdown under pending/. Does not pin into live cards."""
    if not candidates:
        return []
    dest = pending_cards_dir(workspace_root=workspace_root)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    written: list[Path] = []
    for index, cand in enumerate(candidates):
        safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", cand.title).strip("_") or f"c{index}"
        name = f"{stamp}_{turn_id}_{safe}.md" if turn_id else f"{stamp}_{safe}.md"
        path = dest / name
        front = (
            f"---\nkind: {cand.kind}\ntitle: {cand.title}\n"
            f"status: pending\nsource: continuity\n---\n\n"
        )
        path.write_text(front + cand.body, encoding="utf-8")
        written.append(path)
    return written
