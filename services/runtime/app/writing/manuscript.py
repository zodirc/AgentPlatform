"""Single-file manuscript helpers (docs/23 monofile default).

Chapters live as marked blocks inside one markdown file:

    <!-- section:ch1 -->
    ...
    <!-- /section:ch1 -->
"""

from __future__ import annotations

import re
from pathlib import Path

from app.settings import settings

_SECTION_START = "<!-- section:{id} -->"
_SECTION_END = "<!-- /section:{id} -->"
_SECTION_RE = re.compile(
    r"<!--\s*section:(?P<id>[^\s>]+)\s*-->\s*(?P<body>.*?)\s*<!--\s*/section:(?P=id)\s*-->",
    re.DOTALL,
)


def manuscript_mode() -> str:
    mode = (getattr(settings, "writing_manuscript_mode", None) or "monofile").strip().lower()
    return mode if mode in {"monofile", "sections"} else "monofile"


def confirmed_manuscript_rel() -> str:
    rel = (getattr(settings, "writing_manuscript_path", None) or "manuscript.md").strip().lstrip("/")
    return rel or "manuscript.md"


def draft_manuscript_rel() -> str:
    return f".agent/work/drafts/{Path(confirmed_manuscript_rel()).name}"


def section_start(section_id: str) -> str:
    return _SECTION_START.format(id=section_id.strip())


def section_end(section_id: str) -> str:
    return _SECTION_END.format(id=section_id.strip())


def format_section_block(section_id: str, content: str) -> str:
    body = content.strip("\n")
    return f"{section_start(section_id)}\n{body}\n{section_end(section_id)}"


def upsert_section(doc: str, section_id: str, content: str) -> str:
    """Replace an existing section block, or append a new one."""
    sid = section_id.strip()
    block = format_section_block(sid, content)
    start = section_start(sid)
    end = section_end(sid)
    if start in doc and end in doc:
        pattern = re.compile(
            re.escape(start) + r".*?" + re.escape(end),
            re.DOTALL,
        )
        updated, n = pattern.subn(block, doc, count=1)
        if n:
            return updated if updated.endswith("\n") else updated + "\n"
    base = doc.rstrip()
    if base:
        return f"{base}\n\n{block}\n"
    return f"{block}\n"


def extract_section(doc: str, section_id: str) -> str | None:
    sid = section_id.strip()
    start = section_start(sid)
    end = section_end(sid)
    if start not in doc or end not in doc:
        return None
    pattern = re.compile(
        re.escape(start) + r"\n?(.*?)\n?" + re.escape(end),
        re.DOTALL,
    )
    match = pattern.search(doc)
    if not match:
        return None
    return match.group(1).strip("\n")


def list_section_ids(doc: str) -> list[str]:
    return [m.group("id") for m in _SECTION_RE.finditer(doc)]


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
    return name == confirmed or rel in {confirmed_manuscript_rel(), draft_manuscript_rel()}


def previous_section_id(section_ids: list[str], focus: str) -> str | None:
    if focus not in section_ids:
        # focus may be new chapter — prev is last existing
        return section_ids[-1] if section_ids else None
    idx = section_ids.index(focus)
    return section_ids[idx - 1] if idx > 0 else None


def load_manuscript_doc(workspace_root: Path | None = None) -> tuple[str, str]:
    """Prefer draft manuscript, then confirmed. Returns (text, rel_path)."""
    root = Path(workspace_root or settings.workspace_root).resolve()
    for rel in (draft_manuscript_rel(), confirmed_manuscript_rel()):
        path = root / rel
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="replace"), rel
            except OSError:
                continue
    return "", draft_manuscript_rel()
