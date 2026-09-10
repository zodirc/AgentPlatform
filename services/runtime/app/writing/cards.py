"""写作素材卡加载、预算 pin 与 system/volatile 拼装（docs/14 C1/C3）。"""

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
    """单张素材卡快照。
    
    参数:
        path/title/kind/body/mtime/truncated。"""
    path: str
    title: str
    kind: str
    body: str
    mtime: float
    truncated: bool = False


@dataclass(frozen=True)
class DroppedCard:
    """预算淘汰记录。
    
    参数:
        path/kind/reason。"""
    path: str
    kind: str
    reason: str


@dataclass(frozen=True)
class WritingCardsSelection:
    """完整 pin 结果。
    
    参数:
        cards/dropped/budget。"""
    cards: list[WritingCard]
    dropped: list[DroppedCard] = field(default_factory=list)
    budget: dict[str, object] = field(default_factory=dict)


def cards_root(*, workspace_root: Path | None = None) -> Path:
    """素材卡根目录。
    
    参数:
        workspace_root。
    
    返回:
        Path。"""
    root = Path(workspace_root or settings.workspace_root).resolve()
    rel = settings.writing_cards_dir.strip().lstrip("/")
    return (root / rel).resolve()


def is_cards_path(path: Path, *, workspace_root: Path | None = None) -> bool:
    """路径是否在 cards 树。
    
    参数:
        path/workspace_root。
    
    返回:
        bool。"""
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
    """扫描解析全部素材卡；跳过 pending。
    
    参数:
        workspace_root。
    
    返回:
        WritingCard 列表。"""
    root = cards_root(workspace_root=workspace_root)
    if not root.is_dir():
        return []
    base = Path(workspace_root or settings.workspace_root).resolve()
    cards: list[WritingCard] = []
    for fp in sorted(root.rglob("*.md")):
        if not fp.is_file() or fp.name.startswith("."):
            continue
        # WN1: pending continuity candidates must never auto-pin.
        try:
            rel_to_cards = fp.resolve().relative_to(root.resolve())
        except ValueError:
            rel_to_cards = Path()
        if rel_to_cards.parts and rel_to_cards.parts[0].lower() == "pending":
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
    """各 kind 字符上限。
    
    参数:
        style/character/plot/general_max。
    
    返回:
        dict。"""
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
    """确定性 pin（message 不影响）。
    
    参数:
        message/cards/预算参数。
    
    返回:
        WritingCard 列表。"""
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
    """完整 pin 含 dropped。
    
    参数:
        message/cards/预算参数。
    
    返回:
        WritingCardsSelection。"""
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
    """格式化为 Writing cards Markdown。
    
    参数:
        cards。
    
    返回:
        Markdown。"""
    if not cards:
        return ""
    parts = [
        "## Writing cards（本作品的写定）",
        "以下素材卡在导入时准备，本轮已固定注入。起草时以这些写定为准；",
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
    """cards 前缀 SHA-256（16 hex）。
    
    参数:
        text。
    
    返回:
        str。"""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest[:16]


def extract_cards_block(prompt: str) -> str:
    """从 prompt 截取 cards 段。
    
    参数:
        prompt。
    
    返回:
        str。"""
    markers = (
        "## Writing cards（本作品的写定）",
        "## Writing cards（必须遵守）",
    )
    idx = -1
    for candidate in markers:
        found = prompt.find(candidate)
        if found >= 0:
            idx = found
            break
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
    for stop in (
        "\n## Work index\n",
        "\n## Work surface\n",
        "\n## Writing spec\n",
        "\n## Story-machine reset",
    ):
        sidx = block.find(stop)
        if sidx >= 0:
            block = block[:sidx]
    return block.rstrip()


def parse_style_card_sections(body: str) -> dict[str, str]:
    """解析 style 卡分区。
    
    参数:
        body。
    
    返回:
        dict。"""
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
    """从章节抽 prose 段。
    
    参数:
        text/max_paragraphs/max_chars_per。
    
    返回:
        list。"""
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
    """合并 style ## 分区。
    
    参数:
        body/section_key/content。
    
    返回:
        str。"""
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
    """开关 Don't 清单。
    
    参数:
        body/enabled。
    
    返回:
        str。"""
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
            "- 三段式排比、空洞形容词堆叠\n"
            "- 整场三字问答连环、叙述全是碎句\n"
            "- 「我知道」「嗯」「懂」只应一声、没有新决定\n",
        )
    return body if "Don't" in sections else merge_style_section(body, "Don't", current or "（待填写）")


def import_samples_into_style_body(
    style_body: str,
    chapter_text: str,
    *,
    max_paragraphs: int = 3,
    max_chars_per: int = 400,
) -> str:
    """章节 prose 填 Samples。
    
    参数:
        style_body/chapter_text/限制。
    
    返回:
        str。"""
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
    """pin 前应用 meta。
    
    参数:
        body/meta。
    
    返回:
        str。"""
    raw = (meta.get("dont_enabled") or "true").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return set_dont_enabled(body, enabled=False)
    return body


def style_card_template_path() -> Path:
    """style 模板路径。

    参数:
        无。

    返回:
        Path。"""
    return Path(__file__).resolve().parents[1] / "scenarios" / "writing" / "templates" / "style_card.md"


BUILTIN_STYLE_PATH = "(builtin)/default_voice.md"
BUILTIN_WEB_SERIAL_PATH = "(builtin)/web_serial_voice.md"
_QUALITY_REJECT_RE = re.compile(
    r"没意思|立意不行|没激情|没特色|太幼稚|很幼稚|不像小说|看不下去|"
    r"AI化|AI\s*化|通病|换个核|重立"
)


def default_voice_card_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "scenarios"
        / "writing"
        / "templates"
        / "default_voice.md"
    )


def web_serial_voice_card_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "scenarios"
        / "writing"
        / "templates"
        / "web_serial_voice.md"
    )


def _load_builtin_voice(path: Path, builtin_path: str, fallback_title: str) -> WritingCard | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = _parse_frontmatter(text)
    if not body.strip():
        return None
    body = apply_style_meta_for_pin(body.strip(), meta)
    return WritingCard(
        path=builtin_path,
        title=_card_title(path, meta, body) or fallback_title,
        kind="style",
        body=body.strip(),
        mtime=path.stat().st_mtime,
    )


def load_builtin_default_voice() -> WritingCard | None:
    return _load_builtin_voice(
        default_voice_card_path(),
        BUILTIN_STYLE_PATH,
        "默认叙事声口",
    )


def load_builtin_web_serial_voice() -> WritingCard | None:
    return _load_builtin_voice(
        web_serial_voice_card_path(),
        BUILTIN_WEB_SERIAL_PATH,
        "连载网文声口",
    )


def with_builtin_style_if_missing(
    cards: list[WritingCard],
    message: str = "",
    *,
    workspace_root: Path | None = None,
) -> list[WritingCard]:
    """无 style 时补默认（网文 mode 用 web_serial 声口）。"""
    if any(c.kind == "style" for c in cards):
        return cards
    builtin = None
    try:
        from app.writing.work_mode import resolve_work_mode

        mode, _src = resolve_work_mode(message, workspace_root=workspace_root)
        if mode == "web_serial":
            builtin = load_builtin_web_serial_voice()
    except Exception:
        builtin = None
    if builtin is None:
        builtin = load_builtin_default_voice()
    if builtin is None:
        return cards
    return [builtin, *cards]


def quality_reject_steer(message: str) -> str:
    """否决故事核 volatile 块。
    
    参数:
        message。
    
    返回:
        str。"""
    if not _QUALITY_REJECT_RE.search(message or ""):
        return ""
    return (
        "## Story-machine reset（本轮用户否决了当前故事）\n"
        "用户否决的是故事核，不是润色。不要给现有人物换一件道具或换一个历史挂点再写同一本书。\n"
        "另起社会机器和人物。不要沿用本稿开场的常见核（特务踹门、人质换手艺、伪造证件当主线）。"
    )


@dataclass(frozen=True)
class WritingCardsPinResult:
    """pin 结果；prompt 稳定，volatile 分离。
    
    参数:
        prompt/cards/available_count/dropped/budget/blocks。"""

    prompt: str
    cards: list[WritingCard]
    available_count: int
    dropped: list[DroppedCard] = field(default_factory=list)
    budget: dict[str, object] = field(default_factory=dict)
    cards_block: str = ""
    volatile_block: str = ""

    @property
    def stable_prompt(self) -> str:
        """与 ``prompt`` 相同，强调可缓存的稳定 system 段。

        返回:
            稳定 prompt 字符串。
        """
        return self.prompt

    def event_payload(self) -> dict[str, object]:
        """生成 turn 事件用的 cards pin 摘要载荷。

        返回:
            含 cards 元数据、chars、prefix_hash 等的 dict。
        """
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
        volatile = self.volatile_block or ""
        if volatile:
            payload["volatile_sha256"] = stable_cards_prefix_hash(volatile)
            payload["volatile_chars"] = len(volatile)
            payload["prohibition_counts"] = {
                "不要": volatile.count("不要"),
                "勿": volatile.count("勿"),
                "禁止": volatile.count("禁止"),
                "必须": volatile.count("必须"),
            }
        return payload


def prepare_writing_system_prompt(
    base_prompt: str,
    message: str,
    *,
    workspace_root: Path | None = None,
) -> WritingCardsPinResult:
    """组装 base+volatile。
    
    参数:
        base_prompt/message/workspace_root。
    
    返回:
        WritingCardsPinResult。"""
    from app.writing.work_index import format_work_index_block
    from app.writing.occupy import wants_new_piece
    from app.writing.signals.spec import build_writing_spec_block

    cards = with_builtin_style_if_missing(
        load_writing_cards(workspace_root=workspace_root),
        message=message,
        workspace_root=workspace_root,
    )
    starting_new = wants_new_piece(message)
    if starting_new:
        cards = [c for c in cards if c.kind == "style"]
    selection = select_writing_cards_detailed(message, cards)
    block = format_cards_block(selection.cards)
    work_index = format_work_index_block(
        workspace_root=workspace_root,
        message=message,
    )
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
    spec = build_writing_spec_block(message, workspace_root=workspace_root)
    if spec:
        extras.append(spec)
    from app.writing.work_mode import resolve_work_mode
    from app.writing.commitment import format_commitment_block
    from app.writing.subtype import serial_subtype_block

    outline_text = ""
    try:
        op = Path(workspace_root or settings.workspace_root).resolve() / "outline.md"
        if op.is_file():
            outline_text = op.read_text(encoding="utf-8", errors="replace")
    except OSError:
        outline_text = ""
    work_mode, _src = resolve_work_mode(message, workspace_root=workspace_root)
    extras.append(format_commitment_block(work_mode=work_mode))
    if work_mode == "web_serial":
        subtype = serial_subtype_block(message, outline_text)
        if subtype:
            extras.append(subtype)
    from app.writing.outline_phase import wants_opening_candidates
    from app.writing.opening_ponds import (
        format_committed_pond_block,
        format_opening_ponds_block,
    )

    if wants_opening_candidates(
        message, outline=outline_text, workspace_root=workspace_root
    ):
        ponds_block = format_opening_ponds_block(workspace_root=workspace_root)
        if ponds_block:
            extras.append(ponds_block)
    else:
        committed = format_committed_pond_block(
            message=message, workspace_root=workspace_root
        )
        if committed:
            extras.append(committed)
    from app.writing.signals.beats import format_local_beats_block

    spec_frag = None
    if spec:
        matched = re.search(r"fragment: `([^`]+)`", spec)
        if matched:
            spec_frag = matched.group(1)
    beats = format_local_beats_block(
        message, workspace_root=workspace_root, fragment=spec_frag
    )
    if beats:
        extras.append(beats)
    if getattr(settings, "writing_token_economy_enabled", True):
        from app.writing.focus import build_work_surface_block

        surface = build_work_surface_block(message, workspace_root=workspace_root)
        if surface:
            extras.append(surface)
    reset = quality_reject_steer(message)
    if reset:
        extras.append(reset)

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
    """Legacy 拼接 system。
    
    参数:
        同 prepare。
    
    返回:
        str。"""
    pin = prepare_writing_system_prompt(
        base_prompt,
        message,
        workspace_root=workspace_root,
    )
    if pin.volatile_block:
        return f"{pin.prompt.rstrip()}\n\n{pin.volatile_block}\n"
    return pin.prompt
