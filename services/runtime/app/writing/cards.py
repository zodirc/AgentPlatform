from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
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
# Inventory pin order (docs/14 C1/C3): style first, then character / plot / general.
KIND_PRIORITY = {
    "style": 0,
    "character": 1,
    "plot": 2,
    "general": 3,
}
STYLE_SECTION_KEYS = ("Voice", "Do", "Don't", "Samples", "Format")
SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)


@dataclass(frozen=True)
class WritingCard:
    path: str
    title: str
    kind: str
    body: str
    mtime: float
    truncated: bool = False


@dataclass(frozen=True)
class DroppedCard:
    path: str
    kind: str
    reason: str


@dataclass(frozen=True)
class WritingCardsSelection:
    cards: list[WritingCard]
    dropped: list[DroppedCard] = field(default_factory=list)
    budget: dict[str, object] = field(default_factory=dict)


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
        kind = _infer_kind(fp, meta)
        if kind == "style":
            body = apply_style_meta_for_pin(body.strip(), meta)
        rel = str(fp.relative_to(base))
        cards.append(
            WritingCard(
                path=rel,
                title=_card_title(fp, meta, body),
                kind=kind,
                body=body.strip(),
                mtime=fp.stat().st_mtime,
            )
        )
    return cards


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    text = text.strip()
    if len(text) <= limit:
        return text, False
    return text[: max(0, limit - 1)].rstrip() + "…", True


def kind_budget_map(
    *,
    style_max: int | None = None,
    character_max: int | None = None,
    plot_max: int | None = None,
    general_max: int | None = None,
) -> dict[str, int]:
    return {
        "style": style_max if style_max is not None else settings.writing_cards_style_max_chars,
        "character": (
            character_max
            if character_max is not None
            else settings.writing_cards_character_max_chars
        ),
        "plot": plot_max if plot_max is not None else settings.writing_cards_plot_max_chars,
        "general": (
            general_max if general_max is not None else settings.writing_cards_general_max_chars
        ),
    }


def _card_cost(title: str, body: str) -> int:
    return len(title) + len(body) + 32


def select_writing_cards(
    message: str,
    cards: list[WritingCard],
    *,
    max_chars: int | None = None,
    per_card_chars: int | None = None,
    style_max: int | None = None,
    character_max: int | None = None,
    plot_max: int | None = None,
    general_max: int | None = None,
) -> list[WritingCard]:
    """Inventory-deterministic pin (docs/14 C1/C3).

    ``message`` is retained for API compatibility but does **not** affect selection.
    Pin set depends only on cards inventory + budgets + sort key (kind → path).
    """
    result = select_writing_cards_detailed(
        message,
        cards,
        max_chars=max_chars,
        per_card_chars=per_card_chars,
        style_max=style_max,
        character_max=character_max,
        plot_max=plot_max,
        general_max=general_max,
    )
    return result.cards


def select_writing_cards_detailed(
    message: str,
    cards: list[WritingCard],
    *,
    max_chars: int | None = None,
    per_card_chars: int | None = None,
    style_max: int | None = None,
    character_max: int | None = None,
    plot_max: int | None = None,
    general_max: int | None = None,
) -> WritingCardsSelection:
    del message  # Inventory pin: message must not affect selection (C3 corridor).
    if not cards:
        return WritingCardsSelection(cards=[], dropped=[], budget={})

    budget = max_chars if max_chars is not None else settings.writing_cards_max_chars
    per_card = per_card_chars if per_card_chars is not None else settings.writing_cards_per_card_chars
    by_kind = kind_budget_map(
        style_max=style_max,
        character_max=character_max,
        plot_max=plot_max,
        general_max=general_max,
    )
    budget_meta: dict[str, object] = {
        "max_chars": budget,
        "per_card_chars": per_card,
        "by_kind": dict(by_kind),
    }

    ordered = sorted(
        cards,
        key=lambda c: (KIND_PRIORITY.get(c.kind, 99), c.path),
    )
    selected: list[WritingCard] = []
    dropped: list[DroppedCard] = []
    used_global = 0
    used_by_kind: dict[str, int] = {k: 0 for k in by_kind}

    for card in ordered:
        kind_cap = by_kind.get(card.kind, by_kind["general"])
        kind_used = used_by_kind.get(card.kind, 0)
        remaining_kind = kind_cap - kind_used
        remaining_global = budget - used_global
        if remaining_kind <= 0:
            dropped.append(
                DroppedCard(path=card.path, kind=card.kind, reason="kind_budget_exhausted")
            )
            continue
        if remaining_global <= 0:
            dropped.append(
                DroppedCard(path=card.path, kind=card.kind, reason="global_budget_exhausted")
            )
            continue

        body_limit = min(per_card, remaining_kind, remaining_global)
        # Reserve title overhead inside the remaining budgets.
        body_limit = max(0, body_limit - len(card.title) - 32)
        if body_limit <= 0:
            dropped.append(
                DroppedCard(path=card.path, kind=card.kind, reason="budget_too_small")
            )
            continue

        body, truncated = _truncate(card.body, body_limit)
        cost = _card_cost(card.title, body)
        if used_global + cost > budget or kind_used + cost > kind_cap:
            # Shrink further to fit remaining budgets exactly once more.
            fit = min(budget - used_global, kind_cap - kind_used) - len(card.title) - 32
            if fit <= 0:
                dropped.append(
                    DroppedCard(path=card.path, kind=card.kind, reason="budget_too_small")
                )
                continue
            body, truncated = _truncate(card.body, fit)
            cost = _card_cost(card.title, body)
            if used_global + cost > budget or kind_used + cost > kind_cap:
                dropped.append(
                    DroppedCard(path=card.path, kind=card.kind, reason="budget_too_small")
                )
                continue

        selected.append(
            WritingCard(
                path=card.path,
                title=card.title,
                kind=card.kind,
                body=body,
                mtime=card.mtime,
                truncated=truncated,
            )
        )
        used_global += cost
        used_by_kind[card.kind] = kind_used + cost

    return WritingCardsSelection(cards=selected, dropped=dropped, budget=budget_meta)


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


def stable_cards_prefix_hash(text: str) -> str:
    """SHA-256 hex digest (truncated) for prefix stability assertions (docs/14 C3)."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest[:16]


def extract_cards_block(prompt: str) -> str:
    marker = "## Writing cards（必须遵守）"
    idx = prompt.find(marker)
    if idx < 0:
        # Hint-only / empty pin: hash the trailing Writing cards hint if present.
        hint = "\n\n## Writing cards\n"
        hidx = prompt.find(hint)
        if hidx < 0:
            return ""
        start = hidx + 2  # skip leading newlines for consistency
        block = prompt[start:]
    else:
        block = prompt[idx:]
    # Stop before work-index / work-surface / other post-card appendices (docs/24).
    for stop in ("\n## Work index\n", "\n## Work surface\n"):
        sidx = block.find(stop)
        if sidx >= 0:
            block = block[:sidx]
    return block.rstrip()


def parse_style_card_sections(body: str) -> dict[str, str]:
    """Extract Voice / Do / Don't / Samples / Format sections from a style card body."""
    matches = list(SECTION_HEADING_RE.finditer(body))
    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        raw_title = match.group(1).strip()
        # Normalize Don't / Dont
        key = raw_title
        if key.lower() in {"dont", "don't", "do not"}:
            key = "Don't"
        elif key.lower() == "voice":
            key = "Voice"
        elif key.lower() == "do":
            key = "Do"
        elif key.lower() == "samples":
            key = "Samples"
        elif key.lower() == "format":
            key = "Format"
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[key] = body[start:end].strip()
    return sections


def extract_sample_paragraphs(
    text: str,
    *,
    max_paragraphs: int = 3,
    max_chars_per: int = 400,
) -> list[str]:
    """Deterministically pull prose paragraphs from a chapter/draft (no LLM)."""
    cleaned = text.strip()
    if not cleaned:
        return []
    # Drop YAML frontmatter if present.
    if cleaned.startswith("---"):
        parts = cleaned.split("---", 2)
        if len(parts) >= 3:
            cleaned = parts[2].strip()
    blocks: list[str] = []
    for raw in re.split(r"\n\s*\n", cleaned):
        block = raw.strip()
        if not block:
            continue
        # Skip heading-only / list-only scaffolding.
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        if all(ln.lstrip().startswith(("#", "-", "*", ">")) for ln in lines) and len(lines) == 1:
            if lines[0].lstrip().startswith("#"):
                continue
        prose = "\n".join(lines).strip()
        if len(prose) < 12:
            continue
        if len(prose) > max_chars_per:
            prose = prose[: max_chars_per - 1].rstrip() + "…"
        blocks.append(prose)
        if len(blocks) >= max_paragraphs:
            break
    return blocks


def merge_style_section(body: str, section_key: str, content: str) -> str:
    """Replace or append a ## section; preserves Voice/Do/Don't/Samples/Format order."""
    canonical = section_key
    if canonical.lower() in {"dont", "don't"}:
        canonical = "Don't"
    elif canonical.lower() == "voice":
        canonical = "Voice"
    elif canonical.lower() == "do":
        canonical = "Do"
    elif canonical.lower() == "samples":
        canonical = "Samples"
    elif canonical.lower() == "format":
        canonical = "Format"

    sections = parse_style_card_sections(body)
    sections[canonical] = content.strip()
    # Preserve any unknown headings by keeping original non-standard keys at end.
    ordered: list[str] = []
    for key in STYLE_SECTION_KEYS:
        if key in sections:
            ordered.append(key)
    for key in sections:
        if key not in ordered:
            ordered.append(key)
    parts: list[str] = []
    for key in ordered:
        parts.append(f"## {key}")
        parts.append(sections[key])
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def set_dont_enabled(body: str, *, enabled: bool) -> str:
    """Toggle Don't list for a work: disabled → placeholder; enabled keeps/restores marker."""
    sections = parse_style_card_sections(body)
    current = sections.get("Don't", "").strip()
    if not enabled:
        return merge_style_section(body, "Don't", "（已关闭：本作品不启用禁词清单）")
    if current.startswith("（已关闭"):
        return merge_style_section(
            body,
            "Don't",
            "按作品定制的禁词与禁结构（去 AI 味）：\n"
            "- 「在这个时代」「不禁」「充满了」\n"
            "- 三段式排比、空洞形容词堆叠\n",
        )
    return body if "Don't" in sections else merge_style_section(body, "Don't", current or "（待填写）")


def import_samples_into_style_body(
    style_body: str,
    chapter_text: str,
    *,
    max_paragraphs: int = 3,
    max_chars_per: int = 400,
) -> str:
    """Fill ## Samples from chapter prose (deterministic; loop-outside helper)."""
    samples = extract_sample_paragraphs(
        chapter_text,
        max_paragraphs=max_paragraphs,
        max_chars_per=max_chars_per,
    )
    if not samples:
        block = "（未从章节提取到可用段落）"
    else:
        block = "\n\n".join(f"> {p}" for p in samples)
    return merge_style_section(style_body, "Samples", block)


def apply_style_meta_for_pin(body: str, meta: dict[str, str]) -> str:
    """Apply frontmatter toggles before pin (dont_enabled=false strips Don't content)."""
    raw = (meta.get("dont_enabled") or "true").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return set_dont_enabled(body, enabled=False)
    return body


def style_card_template_path() -> Path:
    return Path(__file__).resolve().parents[1] / "scenarios" / "writing" / "templates" / "style_card.md"


@dataclass(frozen=True)
class WritingCardsPinResult:
    """Writing pin result.

    WN3 / WT5 layout:
    - ``prompt`` is the **stable** system prefix (``system.md`` / base only) for prompt cache.
    - ``volatile_block`` holds cards / work index / focus+prev — sent as a post-system user
      message, not welded into system.
    """

    prompt: str
    cards: list[WritingCard]
    available_count: int
    dropped: list[DroppedCard] = field(default_factory=list)
    budget: dict[str, object] = field(default_factory=dict)
    cards_block: str = ""
    volatile_block: str = ""

    @property
    def stable_prompt(self) -> str:
        return self.prompt

    def event_payload(self) -> dict[str, object]:
        cards_meta = [
            {
                "path": card.path,
                "kind": card.kind,
                "title": card.title,
                "truncated": card.truncated,
            }
            for card in self.cards
        ]
        chars = sum(len(card.title) + len(card.body) for card in self.cards)
        if self.cards:
            summary = f"pinned {len(self.cards)} writing card(s)"
        elif self.available_count:
            summary = f"no card auto-selected ({self.available_count} available)"
        else:
            summary = "no writing cards"
        payload: dict[str, object] = {
            "cards": cards_meta,
            "chars": chars,
            "available_count": self.available_count,
            "summary": summary,
        }
        if self.dropped:
            payload["dropped"] = [
                {"path": d.path, "kind": d.kind, "reason": d.reason} for d in self.dropped
            ]
        if self.budget:
            payload["budget"] = self.budget
        block = self.cards_block or extract_cards_block(self.volatile_block or self.prompt)
        if block:
            payload["prefix_hash"] = stable_cards_prefix_hash(block)
        return payload


def prepare_writing_system_prompt(
    base_prompt: str,
    message: str,
    *,
    workspace_root: Path | None = None,
) -> WritingCardsPinResult:
    from app.writing.work_index import format_work_index_block

    cards = load_writing_cards(workspace_root=workspace_root)
    selection = select_writing_cards_detailed(message, cards)
    block = format_cards_block(selection.cards)
    work_index = format_work_index_block(workspace_root=workspace_root)
    extras: list[str] = []
    if block:
        extras.append(block)
    elif cards:
        names = ", ".join(f"{c.title}({c.kind})" for c in cards[:12])
        extras.append(
            "## Writing cards\n"
            f"资料库中有素材卡但未自动选中：{names}。\n"
            "若任务依赖人物/风格写定，先 `read_file` 对应 `sources/cards/` 路径。"
        )
    if work_index:
        extras.append(work_index)
    if getattr(settings, "writing_token_economy_enabled", True):
        from app.writing.focus import build_work_surface_block

        surface = build_work_surface_block(message, workspace_root=workspace_root)
        if surface:
            extras.append(surface)

    volatile = "\n\n".join(extras) if extras else ""
    return WritingCardsPinResult(
        prompt=base_prompt,
        cards=selection.cards if block else [],
        available_count=len(cards),
        dropped=selection.dropped,
        budget=selection.budget,
        cards_block=block,
        volatile_block=volatile,
    )


def build_writing_system_prompt(
    base_prompt: str,
    message: str,
    *,
    workspace_root: Path | None = None,
) -> str:
    """Legacy welded string (stable + volatile). Prefer ``prepare_writing_system_prompt``."""
    pin = prepare_writing_system_prompt(
        base_prompt,
        message,
        workspace_root=workspace_root,
    )
    if pin.volatile_block:
        return f"{pin.prompt.rstrip()}\n\n{pin.volatile_block}\n"
    return pin.prompt
