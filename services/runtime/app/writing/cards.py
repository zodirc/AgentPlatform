from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.settings import settings

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)
KIND_FROM_DIR = {
    "characters": "character",
    "character": "character",
    "plots": "plot",
    "plot": "plot",
    "style": "style",
    "styles": "style",
}


@dataclass(frozen=True)
class WritingCard:
    path: str
    title: str
    kind: str
    body: str
    mtime: float


def cards_root(*, workspace_root: Path | None = None) -> Path:
    root = Path(workspace_root or settings.workspace_root).resolve()
    rel = settings.writing_cards_dir.strip().lstrip("/")
    return (root / rel).resolve()


def is_cards_path(path: Path, *, workspace_root: Path | None = None) -> bool:
    try:
        rel = path.resolve().relative_to(Path(workspace_root or settings.workspace_root).resolve())
    except ValueError:
        return "cards" in path.parts
    return rel.parts[:2] == ("sources", "cards") or (len(rel.parts) >= 1 and rel.parts[0] == "cards")


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER_RE.match(text.strip())
    if not match:
        return {}, text.strip()
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta, match.group(2).strip()


def _infer_kind(path: Path, meta: dict[str, str]) -> str:
    raw = (meta.get("kind") or "").lower()
    if raw in {"character", "plot", "style"}:
        return raw
    for part in path.parts:
        mapped = KIND_FROM_DIR.get(part.lower())
        if mapped:
            return mapped
    return "general"


def _card_title(path: Path, meta: dict[str, str], body: str) -> str:
    if meta.get("title"):
        return meta["title"]
    for line in body.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip() or path.stem
    return path.stem


def load_writing_cards(*, workspace_root: Path | None = None) -> list[WritingCard]:
    root = cards_root(workspace_root=workspace_root)
    if not root.is_dir():
        return []
    base = Path(workspace_root or settings.workspace_root).resolve()
    cards: list[WritingCard] = []
    for fp in sorted(root.rglob("*.md")):
        if not fp.is_file() or fp.name.startswith("."):
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta, body = _parse_frontmatter(text)
        if not body.strip():
            continue
        rel = str(fp.relative_to(base))
        cards.append(
            WritingCard(
                path=rel,
                title=_card_title(fp, meta, body),
                kind=_infer_kind(fp, meta),
                body=body.strip(),
                mtime=fp.stat().st_mtime,
            )
        )
    return cards


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def select_writing_cards(
    message: str,
    cards: list[WritingCard],
    *,
    max_chars: int | None = None,
    per_card_chars: int | None = None,
) -> list[WritingCard]:
    if not cards:
        return []
    budget = max_chars if max_chars is not None else settings.writing_cards_max_chars
    per_card = per_card_chars if per_card_chars is not None else settings.writing_cards_per_card_chars
    lowered = message.lower()

    scored: list[tuple[int, WritingCard]] = []
    for card in cards:
        score = 0
        title = card.title.lower()
        stem = Path(card.path).stem.lower()
        if title and title in lowered:
            score += 100
        if stem and stem in lowered:
            score += 80
        # Prefer short token overlap for CJK names / Latin tokens.
        for token in re.findall(r"[a-zA-Z0-9_\u4e00-\u9fff]{2,}", title):
            if token.lower() in lowered:
                score += 20
        if card.kind == "style":
            score += 40
        if card.kind == "plot" and any(k in lowered for k in ("章", "情节", "大纲", "剧情", "chapter")):
            score += 30
        if card.kind == "character" and any(k in lowered for k in ("人物", "角色", "性格")):
            score += 15
        scored.append((score, card))

    scored.sort(key=lambda item: (-item[0], item[1].kind, item[1].path))
    selected: list[WritingCard] = []
    used = 0
    for score, card in scored:
        if score <= 0 and selected:
            continue
        # If nothing matched yet, still take style cards and highest general cards.
        if score <= 0 and card.kind not in {"style", "character", "plot", "general"}:
            continue
        if score <= 0 and card.kind == "plot" and selected:
            continue
        body = _truncate(card.body, per_card)
        cost = len(card.title) + len(body) + 32
        if selected and used + cost > budget:
            break
        if not selected and cost > budget:
            body = _truncate(card.body, max(200, budget - len(card.title) - 32))
            cost = len(card.title) + len(body) + 32
        selected.append(
            WritingCard(
                path=card.path,
                title=card.title,
                kind=card.kind,
                body=body,
                mtime=card.mtime,
            )
        )
        used += cost
        if used >= budget:
            break

    if not selected:
        # Fallback: pin style cards only, then inventory names.
        for card in cards:
            if card.kind != "style":
                continue
            body = _truncate(card.body, per_card)
            selected.append(
                WritingCard(
                    path=card.path,
                    title=card.title,
                    kind=card.kind,
                    body=body,
                    mtime=card.mtime,
                )
            )
            break
    return selected


def format_cards_block(cards: list[WritingCard]) -> str:
    if not cards:
        return ""
    parts = [
        "## Writing cards（必须遵守）",
        "以下素材卡在导入时准备，本轮已固定注入。起草时优先遵守这些写定；",
        "`search_sources` 只用于原文场面/细节，不要用检索替代这些卡片。",
        "",
    ]
    for card in cards:
        parts.append(f"### [{card.kind}] {card.title}")
        parts.append(f"来源: `{card.path}`")
        parts.append(card.body)
        parts.append("")
    return "\n".join(parts).strip()


@dataclass(frozen=True)
class WritingCardsPinResult:
    prompt: str
    cards: list[WritingCard]
    available_count: int

    def event_payload(self) -> dict[str, object]:
        cards_meta = [
            {"path": card.path, "kind": card.kind, "title": card.title}
            for card in self.cards
        ]
        chars = sum(len(card.title) + len(card.body) for card in self.cards)
        if self.cards:
            summary = f"pinned {len(self.cards)} writing card(s)"
        elif self.available_count:
            summary = f"no card auto-selected ({self.available_count} available)"
        else:
            summary = "no writing cards"
        return {
            "cards": cards_meta,
            "chars": chars,
            "available_count": self.available_count,
            "summary": summary,
        }


def prepare_writing_system_prompt(
    base_prompt: str,
    message: str,
    *,
    workspace_root: Path | None = None,
) -> WritingCardsPinResult:
    cards = load_writing_cards(workspace_root=workspace_root)
    selected = select_writing_cards(message, cards)
    block = format_cards_block(selected)
    if block:
        prompt = f"{base_prompt.rstrip()}\n\n{block}\n"
        return WritingCardsPinResult(prompt=prompt, cards=selected, available_count=len(cards))
    if cards:
        names = ", ".join(f"{c.title}({c.kind})" for c in cards[:12])
        hint = (
            "\n\n## Writing cards\n"
            f"资料库中有素材卡但未自动选中：{names}。\n"
            "若任务依赖人物/风格写定，先 `read_file` 对应 `sources/cards/` 路径。\n"
        )
        return WritingCardsPinResult(
            prompt=f"{base_prompt.rstrip()}\n{hint}",
            cards=[],
            available_count=len(cards),
        )
    return WritingCardsPinResult(
        prompt=base_prompt,
        cards=[],
        available_count=0,
    )


def build_writing_system_prompt(
    base_prompt: str,
    message: str,
    *,
    workspace_root: Path | None = None,
) -> str:
    return prepare_writing_system_prompt(
        base_prompt,
        message,
        workspace_root=workspace_root,
    ).prompt
