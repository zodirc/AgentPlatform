"""网文子类型气质卡（W1）。与去 AI 化正交，只解决混搭割裂。"""

from __future__ import annotations

import re
from pathlib import Path

_FANREN = re.compile(r"凡人流|稳健|宗门杂役|散修")
_URBAN = re.compile(r"都市重生|重生|松弛|现代都市")
_MARTIAL = re.compile(r"武道|狠戾|江湖|刀|拳")

_CARDS: dict[str, str] = {
    "fanren": (
        "## 子类型气质：凡人流\n"
        "行文稳健，算计与消耗可见；不写天才顿悟。冲突可以慢半拍，但账要当场。"
    ),
    "urban_rebirth": (
        "## 子类型气质：都市重生\n"
        "口吻松弛，信息差写在对话里；不把现代生活写成修真说明书。"
    ),
    "martial": (
        "## 子类型气质：武道\n"
        "行文狠戾短促，力从手上过来；不把狠写成主题金句。"
    ),
}


def infer_serial_subtype(message: str = "", outline: str = "") -> str | None:
    blob = f"{message}\n{outline}"
    if _FANREN.search(blob):
        return "fanren"
    if _MARTIAL.search(blob) and not _URBAN.search(blob):
        return "martial"
    if _URBAN.search(blob):
        return "urban_rebirth"
    return None


def serial_subtype_block(message: str = "", outline: str = "") -> str:
    key = infer_serial_subtype(message, outline)
    if not key:
        return ""
    return _CARDS[key]


def subtype_template_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "scenarios" / "writing" / "templates"
