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
