"""Single-file manuscript helpers (docs/23 monofile default).

Visible files (`drafts/manuscript.md`, `manuscript.md`) use chapter H1s:

    # 第一章
    ...

HTML ``<!-- section:id -->`` fences are parse-only (legacy). Writes never emit them.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.settings import settings

_HTML_SECTION_RE = re.compile(
    r"<!--\s*section:(?P<id>[^\s>]+)\s*-->\s*(?P<body>.*?)\s*<!--\s*/section:(?P=id)\s*-->",
    re.DOTALL,
)
_HTML_MARK_RE = re.compile(r"<!--\s*/?section:[^>]+-->[ \t]*\n?")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
_CH_ID_RE = re.compile(r"^(?:ch|chapter|section)[_-]?0*(\d+)$", re.I)
_NUM_ID_RE = re.compile(r"^0*(\d+)$")
_CN_CHAPTER_RE = re.compile(
    r"^第\s*([0-9０-９]+|[一二三四五六七八九十百零两]+)\s*章"
)
_DIGITS = "零一二三四五六七八九"
_CN_NUM = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def manuscript_mode() -> str:
    mode = (getattr(settings, "writing_manuscript_mode", None) or "monofile").strip().lower()
    return mode if mode in {"monofile", "sections"} else "monofile"


def confirmed_manuscript_rel() -> str:
    rel = (getattr(settings, "writing_manuscript_path", None) or "manuscript.md").strip().lstrip("/")
    return rel or "manuscript.md"


def draft_manuscript_rel() -> str:
    """In-progress manuscript on the visible work surface (tree + double-click)."""
    return f"drafts/{Path(confirmed_manuscript_rel()).name}"


def legacy_draft_manuscript_rel() -> str:
    """Pre-visible-drafts path under harness tree (read/migrate only)."""
    return f".agent/work/drafts/{Path(confirmed_manuscript_rel()).name}"


def strip_section_html(text: str) -> str:
    """Drop legacy HTML section fences. Visible files must not keep them."""
    return _HTML_MARK_RE.sub("", text or "")


def human_section_title(section_id: str) -> str:
    """H1 text for a section id: ch3 → 第三章; otherwise the id itself."""
    sid = section_id.strip()
    match = _CH_ID_RE.fullmatch(sid) or _NUM_ID_RE.fullmatch(sid)
    if match:
        return f"第{_int_to_cn(int(match.group(1)))}章"
    return sid


def _int_to_cn(n: int) -> str:
    if n <= 0:
        return str(n)
    if n < 10:
        return _DIGITS[n]
    if n == 10:
        return "十"
    if n < 20:
        return "十" + _DIGITS[n - 10]
    if n < 100:
        ten, one = divmod(n, 10)
        return _DIGITS[ten] + "十" + (_DIGITS[one] if one else "")
    return str(n)


def _cn_to_int(token: str) -> int | None:
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    normalized = "".join(chr(ord(c) - 0xFEE0) if "０" <= c <= "９" else c for c in token)
    if normalized.isdigit():
        return int(normalized)
    if token in _CN_NUM:
        return _CN_NUM[token]
    if token.startswith("十"):
        rest = token[1:]
        return 10 + (_CN_NUM.get(rest, 0) if rest else 0)
    if "十" in token:
        left, _, right = token.partition("十")
        return _CN_NUM.get(left, 0) * 10 + _CN_NUM.get(right, 0)
    return None


def _section_id_from_heading(title: str) -> str:
    heading = title.strip()
    match = _CN_CHAPTER_RE.match(heading)
    if match:
        n = _cn_to_int(match.group(1))
        if n is not None:
            return f"ch{n}"
    match = _CH_ID_RE.fullmatch(heading)
    if match:
        return f"ch{int(match.group(1))}"
    return heading


def _same_section(left: str, right: str) -> bool:
    a, b = left.strip(), right.strip()
    if a == b:
        return True
    return human_section_title(a) == human_section_title(b) or (
        _section_id_from_heading(a) == _section_id_from_heading(b)
    )


def _prepare_body(content: str, title: str) -> str:
    body = strip_section_html(content or "").strip("\n")
    if not body:
        return ""
    match = re.match(r"^#\s+(.+?)\s*(?:\n|$)", body)
    if not match:
        return body
    heading = match.group(1).strip()
    rest = body[match.end() :].lstrip("\n")
    if heading.casefold() == title.casefold() or _same_section(heading, title):
        return rest
    demoted = f"## {heading}"
    return f"{demoted}\n{rest}" if rest else demoted


def format_section_block(section_id: str, content: str) -> str:
    sid = section_id.strip()
    title = human_section_title(sid)
    body = _prepare_body(content, title)
    if body:
        return f"# {title}\n\n{body}"
    return f"# {title}"


def parse_sections(doc: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (preamble, [(section_id, body), ...]). HTML fences or H1 chapters."""
    text = doc or ""
    html = list(_HTML_SECTION_RE.finditer(text))
    if html:
        preamble = text[: html[0].start()].rstrip()
        sections = [
            (m.group("id").strip(), strip_section_html(m.group("body")).strip("\n"))
            for m in html
        ]
        return preamble, sections

    headings = list(_H1_RE.finditer(text))
    if not headings:
        return text.rstrip(), []
    preamble = text[: headings[0].start()].rstrip()
    sections: list[tuple[str, str]] = []
    for i, match in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[match.end() : end].strip("\n")
        sections.append((_section_id_from_heading(match.group(1)), body))
    return preamble, sections


def _serialize(preamble: str, sections: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    if preamble.strip():
        parts.append(preamble.strip("\n"))
    for sid, body in sections:
        parts.append(format_section_block(sid, body))
    if not parts:
        return ""
    text = "\n\n".join(parts)
    return text if text.endswith("\n") else text + "\n"


def upsert_section(doc: str, section_id: str, content: str) -> str:
    """Replace an existing chapter, or append a new one. Always writes H1 form."""
    sid = section_id.strip()
    title = human_section_title(sid)
    body = _prepare_body(content, title)
    preamble, sections = parse_sections(doc)
    found = False
    updated: list[tuple[str, str]] = []
    for existing_id, existing_body in sections:
        if not found and _same_section(existing_id, sid):
            updated.append((sid, body))
            found = True
        else:
            updated.append((existing_id, existing_body))
    if not found:
        updated.append((sid, body))
    return _serialize(preamble, updated)


def extract_section(doc: str, section_id: str) -> str | None:
    sid = section_id.strip()
    _, sections = parse_sections(doc)
    for existing_id, body in sections:
        if _same_section(existing_id, sid):
            return body
    return None


def list_section_ids(doc: str) -> list[str]:
    return [sid for sid, _ in parse_sections(doc)[1]]


def clip_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Return (text, clipped). Visible omission marker when clipped."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    if max_chars < 120:
        return text[:max_chars] + "…[clipped]", True
    head = max(40, (max_chars - 80) // 2)
    tail = max(40, max_chars - head - 80)
    omitted = len(text) - head - tail
    return (
        f"{text[:head]}\n\n…[omitted {omitted} chars; edit in segments]…\n\n{text[-tail:]}",
        True,
    )


def is_manuscript_rel(path: str) -> bool:
    rel = path.strip().lstrip("/").replace("\\", "/")
    name = Path(rel).name
    confirmed = Path(confirmed_manuscript_rel()).name
    return name == confirmed or rel in {
        confirmed_manuscript_rel(),
        draft_manuscript_rel(),
        legacy_draft_manuscript_rel(),
    }


def previous_section_id(section_ids: list[str], focus: str) -> str | None:
    if focus not in section_ids:
        # focus may be new chapter — prev is last existing
        return section_ids[-1] if section_ids else None
    idx = section_ids.index(focus)
    return section_ids[idx - 1] if idx > 0 else None


def load_manuscript_doc(workspace_root: Path | None = None) -> tuple[str, str]:
    """Prefer draft manuscript, then legacy draft, then confirmed. Returns (text, rel_path)."""
    root = Path(workspace_root or settings.workspace_root).resolve()
    for rel in (
        draft_manuscript_rel(),
        legacy_draft_manuscript_rel(),
        confirmed_manuscript_rel(),
    ):
        path = root / rel
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="replace"), rel
            except OSError:
                continue
    return "", draft_manuscript_rel()
