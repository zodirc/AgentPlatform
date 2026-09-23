"""作品候选：题材投影 + 卡片解析。不含采样循环。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from app.engine.state import user_message

_FLAVOR_MAX = 400
_OPENING_MAX = 800
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_LEAD_IN_RE = re.compile(r"^(请)?(帮我)?(写一篇|写一本|写一章|写部)\s*")
_LENGTH_RE = re.compile(r"^长篇\s*")
_TAIL_RE = re.compile(r"(小说|网文).*$")
_META_HEADS = (
    "我觉得",
    "我认为",
    "我先",
    "首先",
    "接下来",
    "这个故事可以",
    "这部小说可以",
    "分析：",
    "比较：",
    "创作过程",
    "先想",
    "先比较",
)

CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "pitch"],
    "properties": {
        "title": {"type": "string", "minLength": 2, "maxLength": 16},
        "pitch": {"type": "string", "minLength": 1},
    },
}

_FORM_SYSTEM = """根据用户原话，借题材参照交一本新书的书名和简介。

用户原话优先。题材只供参照，不是模板；另起人物、世界和故事，不要换名复述。

简介按书页上的作品介绍来写，让人知道这本书主要写什么。不要解释创作思路，不要罗列卖点，也不要写成预告片。

只交一本。"""


@dataclass(frozen=True)
class CandidateContext:
    genre: str
    fresh_work: bool = True


def _clip_draft(text: str, limit: int) -> str:
    body = (text or "").strip()
    if len(body) <= limit:
        return body
    return body[:limit].rstrip()


def genre_label(user_text: str) -> str:
    text = (user_text or "").strip()
    if not text:
        return ""
    text = _LEAD_IN_RE.sub("", text).strip()
    text = _LENGTH_RE.sub("", text).strip()
    text = _TAIL_RE.sub("", text).strip(" ，,。的")
    return text or (user_text or "").strip()


def genre_of(user_text: str) -> str:
    return genre_label(user_text) or (user_text or "").strip() or "都市修真"


# 换一组 / 再看看本身不是类型名。「我要其他的」剥掉尾字后会变成「我要其他」。
_CHOICE_ONLY = frozenset({"我看看", "看看", "先看", "我要其他的", "我要其他"})


def names_genre(user_text: str) -> bool:
    """这句话有没有点出一个类型。换卡令牌不算。"""
    label = genre_label(user_text)
    if not label or label in _CHOICE_ONLY:
        return False
    if (user_text or "").strip() in _CHOICE_ONLY:
        return False
    from app.writing.subject_pool import pool_for

    return label != (user_text or "").strip() or bool(pool_for(label))


def sample_user_text(current: str, prior: list[str] | None = None) -> str:
    """抽题材用的那句话。本句没点类型时，沿用会话里上一句点过名的。"""
    if names_genre(current):
        return current
    for text in prior or ():
        if names_genre(text):
            return text
    return current


def topic_of(user_text: str) -> str:
    genre = genre_of(user_text)
    if "长篇" in (user_text or "") and "长篇" not in genre:
        return f"长篇{genre}"
    return genre


def candidate_fingerprint(*parts: str) -> str:
    """作品指纹：空白折叠后的 sha256 前缀。不做关键词黑名单。"""
    blob = "".join(re.sub(r"\s+", "", str(part or "")) for part in parts)
    if not blob:
        return ""
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def project_candidate_context(
    user_text: str = "",
    *,
    workspace_root: Any = None,
) -> CandidateContext:
    """只抽出题材。不读 writing_context / ch1 / outline / draft / 旧卡。"""
    _ = workspace_root
    return CandidateContext(genre=genre_of(user_text), fresh_work=True)


def build_candidate_context(
    user_text: str = "",
    *,
    workspace_root: Any = None,
) -> dict[str, Any]:
    ctx = project_candidate_context(user_text, workspace_root=workspace_root)
    return {"genre": ctx.genre, "fresh_work": ctx.fresh_work}


def obvious_meta_text(text: str) -> bool:
    """格式错误：这是在分析，不是候选。不做文学判断。"""
    body = (text or "").strip()
    if not body:
        return True
    return any(body.startswith(head) for head in _META_HEADS)


def first_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    blobs: list[str] = []
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        blobs.append(fenced.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        blobs.append(text[start : end + 1])
    seen: set[str] = set()
    for blob in blobs:
        if blob in seen:
            continue
        seen.add(blob)
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def parse_card(raw: str) -> dict[str, str] | None:
    title = ""
    flavor = ""
    opening = ""
    data = first_json_object(raw)
    if data is not None:
        title = str(data.get("title") or data.get("书名") or "").strip()
        flavor = str(
            data.get("flavor")
            or data.get("这本书")
            or data.get("this_book")
            or data.get("book")
            or ""
        ).strip()
        opening = str(
            data.get("opening") or data.get("pitch") or data.get("简介") or ""
        ).strip()
    if not (title and opening):
        text = (raw or "").strip()
        title_m = re.search(r"(?:title|书名)\s*[:：]\s*(.+)", text)
        flavor_m = re.search(r"(?:这本书|flavor)\s*[:：]\s*(.+)", text)
        opening_m = re.search(r"(?:opening|简介|pitch)\s*[:：]\s*(.+)", text, re.S)
        if title_m:
            title = title or title_m.group(1).strip().strip("「」\"'").splitlines()[0]
        if flavor_m:
            flavor = flavor or flavor_m.group(1).strip().splitlines()[0]
        if opening_m:
            opening = opening or opening_m.group(1).strip()
    flavor = _clip_draft(flavor, _FLAVOR_MAX)
    opening = _clip_draft(opening, _OPENING_MAX)
    if not (2 <= len(title) <= 16 and opening):
        return None
    return {"title": title, "flavor": flavor, "opening": opening, "pitch": opening}


def parse_candidate(raw: str) -> dict[str, str] | None:
    parsed = parse_card(raw)
    if parsed is None:
        return None
    if obvious_meta_text(parsed["pitch"]):
        return None
    return parsed


def parse_title_pitch(raw: str) -> dict[str, str] | None:
    parsed = parse_candidate(raw)
    if parsed is None:
        return None
    return {"title": parsed["title"], "pitch": parsed["pitch"]}


def form_messages(
    user_text: str = "",
    *,
    subject: str = "",
) -> list[dict[str, Any]]:
    ctx = project_candidate_context(user_text)
    raw_request = (user_text or "").strip()
    lines = [f"用户原话：{raw_request}", f"类型参考：{ctx.genre}"]
    drawn = subject.strip()
    if drawn:
        lines.append(f"题材：{drawn}")
    lines.extend(["", "交这本书的书名和简介。"])
    return [
        {"role": "system", "content": [{"type": "text", "text": _FORM_SYSTEM}]},
        user_message("\n".join(lines)),
    ]
