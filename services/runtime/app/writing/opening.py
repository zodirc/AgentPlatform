"""Opening-chapter entry: institution name before a standable place.

Soft facts only. Callers never mutate disk. Not a ban on 宗门 in the book.
"""

from __future__ import annotations

import re
from typing import Any

from app.writing.lore import is_opening_section

_SENT_SPLIT = re.compile(r"[。！？!?\n]+")
_ORG = re.compile(
    r"(?<!祖)[\u4e00-\u9fff]{1,8}(?:宗|派)|仙门|教门|宗门"
)
_PLACE = re.compile(r"镇|村|街|巷|店|铺|渡口|集市|城门|酒家|客栈")
_MIN_VISIBLE = 80
_WINDOW = 180


def _opening_window(text: str) -> str:
    from app.writing.text_metrics import visible_chars

    sents = [part.strip() for part in _SENT_SPLIT.split(text or "") if part.strip()]
    blob = "".join(sents[:3]) if sents else (text or "")
    if visible_chars(blob) <= _WINDOW:
        return blob
    out: list[str] = []
    n = 0
    for ch in blob:
        out.append(ch)
        if not ch.isspace():
            n += 1
        if n >= _WINDOW:
            break
    return "".join(out)


def institution_before_place(text: str) -> bool:
    """True when 宗/派/仙门 lands before 镇/村/街/店 in the opening window."""
    window = _opening_window(text)
    org = _ORG.search(window)
    if org is None:
        return False
    place = _PLACE.search(window)
    if place is None:
        return True
    return org.start() < place.start()


def opening_fields(content: str, section_id: str = "") -> dict[str, Any]:
    """Attach to draft_section. Opening chapter only."""
    from app.writing.text_metrics import visible_chars

    if not is_opening_section(section_id):
        return {}
    text = content or ""
    if visible_chars(text) < _MIN_VISIBLE:
        return {}
    if not institution_before_place(text):
        return {}
    return {"opening_institution": True}
