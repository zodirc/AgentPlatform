"""WN1 离线 continuity 候选（docs/30）。"""

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
        "临时",
        "安置",
        "语音",
        "十一",
        "夜里",
        "安置点",
    }
)
_NAME_PARTICLE_SUFFIX = frozenset("里上中下点时后前个了着过的地得")


@dataclass(frozen=True)
class ContinuityCandidate:
    """候选卡。
    
    参数:
        kind/title/body/source_hint。"""
    kind: str
    title: str
    body: str
    source_hint: str = ""


# Hard caps so post-turn heuristics stay millisecond-scale (docs/13 R3/R4).
_MAX_CHAPTER_CHARS = 12_000
_FALLBACK_SCAN_CHARS = 4_000
_ROSTER_SLOT = re.compile(
    r"(?:跟着谁|这本在写谁|角色)[*_]*[：:]\s*([^\n]{1,40})"
)


def _is_cjk(ch: str) -> bool:
    return bool(ch) and "\u4e00" <= ch <= "\u9fff"


def _inside_longer_token(name: str, text: str) -> bool:
    """True if every occurrence is glued to extra CJK on the left (compound, not 名+动作)."""
    if not name or not text:
        return False
    found = False
    for match in re.finditer(re.escape(name), text):
        found = True
        i = match.start()
        if i > 0 and _is_cjk(text[i - 1]):
            continue
        return False
    return found


def _looks_like_name(name: str) -> bool:
    token = (name or "").strip()
    if len(token) < 2 or len(token) > 4:
        return False
    if token in _STOP_NAMES:
        return False
    if not re.fullmatch(r"[\u4e00-\u9fff]+", token):
        return False
    if token[-1] in _NAME_PARTICLE_SUFFIX:
        return False
    return True


def extract_outline_roster(outline: str) -> set[str]:
    """从近池槽位抽出人名（跟着谁 / 这本在写谁）。"""
    names: set[str] = set()
    for match in _ROSTER_SLOT.finditer(outline or ""):
        blob = (match.group(1) or "").strip()
        token_match = re.match(r"^([\u4e00-\u9fff]{2,3})", blob)
        if not token_match:
            continue
        token = token_match.group(1)
        if len(token) == 3 and token[-1] in "在把的了是与和被从到向着过":
            token = token[:2]
        if _looks_like_name(token):
            names.add(token)
    return names


def extract_continuity_candidates(
    chapter_text: str,
    *,
    section_id: str = "",
    max_candidates: int = 5,
    outline: str = "",
) -> list[ContinuityCandidate]:
    """启发式抽取。假复合词（临时安置点 / 语音里说）不当人名。"""
    text = (chapter_text or "").strip()
    if not text:
        return []
    if len(text) > _MAX_CHAPTER_CHARS:
        text = text[:_MAX_CHAPTER_CHARS]

    verb_bound = re.compile(
        r"([\u4e00-\u9fff]{2,3})"
        r"(?:拔|点了|点头|决|说|道|问|笑|怒|离开|决定|答应|拒绝|阵亡|受伤|背叛|归来)"
    )
    counts: dict[str, int] = {}
    for match in verb_bound.finditer(text):
        name = match.group(1)
        if not _looks_like_name(name):
            continue
        if _inside_longer_token(name, text):
            continue
        counts[name] = counts.get(name, 0) + 1

    # Fallback: only tokens that appear twice and are not glued into a longer CJK compound.
    if not counts:
        scan = text[:_FALLBACK_SCAN_CHARS]
        raw: dict[str, int] = {}
        for length in (3, 2):
            i = 0
            while i + length <= len(scan):
                chunk = scan[i : i + length]
                if _looks_like_name(chunk):
                    raw[chunk] = raw.get(chunk, 0) + 1
                i += 1
            counts = {
                k: v
                for k, v in raw.items()
                if v >= 2 and not _inside_longer_token(k, text)
            }
            if counts:
                break

    roster = extract_outline_roster(outline)
    if roster:
        for name in roster:
            if name in text and _looks_like_name(name):
                counts[name] = max(counts.get(name, 0), 2)
        counts = {
            k: v
            for k, v in counts.items()
            if k in roster or any(k in r or r in k for r in roster)
        }

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
    """pending 目录。
    
    参数:
        workspace_root。
    
    返回:
        Path。"""
    root = Path(workspace_root or settings.workspace_root).resolve()
    return (root / "sources" / "cards" / "pending").resolve()


def write_pending_candidates(
    candidates: list[ContinuityCandidate],
    *,
    workspace_root: Path | None = None,
    turn_id: str = "",
) -> list[Path]:
    """写 pending 卡。
    
    参数:
        candidates/workspace/turn_id。
    
    返回:
        list[Path]。"""
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
