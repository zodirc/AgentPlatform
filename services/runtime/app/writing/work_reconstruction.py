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
    "required": ["premise", "title", "pitch", "intent"],
    "properties": {
        "premise": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "reader_pull",
                "genre_promise",
                "story_motion",
            ],
            "properties": {
                "reader_pull": {"type": "string", "minLength": 1},
                "genre_promise": {"type": "string", "minLength": 1},
                "story_motion": {"type": "string", "minLength": 1},
            },
        },
        "title": {"type": "string", "minLength": 2, "maxLength": 16},
        "pitch": {"type": "string", "minLength": 1},
        "intent": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "no_human_pull",
                "genre_decorative",
                "noun_graft",
                "moral_pre_solved",
                "no_serial_engine",
            ],
            "properties": {
                "no_human_pull": {"type": "boolean"},
                "genre_decorative": {"type": "boolean"},
                "noun_graft": {"type": "boolean"},
                "moral_pre_solved": {"type": "boolean"},
                "no_serial_engine": {"type": "boolean"},
            },
        },
    },
}

_FORM_SYSTEM = """根据用户原话交一本新书的书名和简介。

用户原话优先。用户点名的设定保持原样，不要改写成另一类故事。

先按读者通常理解校准用户点名的题材。宽泛题材不是设定改造题：先兑现它原本承诺的阅读体验，不要为了显得新奇，把日常职业、城市设施、行政登记或合同流程改名成一套超自然系统。题材可以按其传统形态进入现代生活，不必证明每个城市制度都被它重造。

再填写不展示给用户的 premise：
- reader_pull：读者为什么愿意进入这本书，可以来自人物位置、世界想象、能力、关系、气质或成长空间；
- genre_promise：这本书具体兑现用户所选题材的什么体验，而不是借用哪些名词；
- story_motion：长篇大致会向怎样的天地展开，不写第一卷步骤。

premise 只检查作品身份是否成立，不规定冲突形状。作品不必有深刻议题、亲属创伤、自我牺牲、道德两难、对称愿望或代价公式，也不必从冷门职业开场。

简介是网文书页上的作品介绍，不是大纲，也不是第一章梗概。目标抽象层级接近商业长篇开书文案：用几句话说清这个世界凭什么成立、主角大致站在何处、读者将进入怎样一片可延展的生活或天地。可以有一个鲜明钩子，但不要推进到连续场面、查案步骤、亲属嫌疑、能力代价清单或主题结论。

不要写“是……还是……”“必须决定”“作出选择”这类收束；不要用倒计时、牺牲公式或秘密机构硬造深度。数字、履历、日常职责、地点和异常清单不能只用来制造真实感。不要解释创作思路、罗列卖点或写成预告片。通常六十到一百四十个汉字。

书名要像该题材的一本书，命名世界、时代、区域、意象或核心概念，不用机构名、职业名或一句道德难题代替书名。

若 premise 任一项不成立，仍如实完成候选，并在 intent 中标 true；不要回头给简介打补丁。intent 只使用这些键：no_human_pull、genre_decorative、noun_graft、moral_pre_solved、no_serial_engine。

若给出已用书名，那个书名已经用过，这一本换一本。

只交一本。输出 premise、title、pitch 和 intent；界面只展示 title 和 pitch。"""


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
    raw = (user_text or "").strip()
    if not raw:
        return "都市修真"
    first = next((line.strip() for line in raw.splitlines() if line.strip()), raw)
    return genre_label(first) or first or "都市修真"


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


def _direction_line(text: str) -> str:
    body = (text or "").strip()
    if not body or body in _CHOICE_ONLY:
        return ""
    return body


def sample_user_text(current: str, prior: list[str] | None = None) -> str:
    """同一次选择里的用户原话按时间接在一起。换卡令牌不计入。

    ``prior`` 从新到旧。后一句里出现「都市」「异能」时，不把前面的话换掉。
    """
    lines: list[str] = []
    for text in reversed(list(prior or ())):
        line = _direction_line(text)
        if line and line not in lines:
            lines.append(line)
    current_line = _direction_line(current)
    if current_line and current_line not in lines:
        lines.append(current_line)
    if lines:
        return "\n".join(lines)
    return (current or "").strip()


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


_SAMPLE_RHETORIC_RES = (
    re.compile(r"是[^。！？\n]{0,24}还是"),
    re.compile(r"必须(决定|在|选择|弄清|面对)"),
    re.compile(r"他(将)?必须"),
    re.compile(r"(作出|做出)选择"),
    re.compile(r"(最终|终于).{0,12}(真相|凶手|幕后)"),
)


def obvious_sample_rhetoric(text: str) -> bool:
    """采样卡表层套话：结论式二选一、强制抉择、提前揭底。不做题材语义判断。"""
    body = (text or "").strip()
    if not body:
        return True
    return any(pattern.search(body) for pattern in _SAMPLE_RHETORIC_RES)


def obvious_sample_overplot(text: str) -> bool:
    """采样卡过细：句拍过多，像第一卷梗概而不像书页简介。"""
    body = (text or "").strip()
    if not body:
        return True
    beats = body.count("。") + body.count("！") + body.count("？")
    return beats >= 5 or len(body) > 180


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


def parse_card(raw: str) -> dict[str, Any] | None:
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
    out: dict[str, Any] = {
        "title": title,
        "flavor": flavor,
        "opening": opening,
        "pitch": opening,
    }
    if data is not None:
        premise = data.get("premise")
        if isinstance(premise, dict):
            out["premise"] = premise
        from app.writing.premise_gate import intent_codes_from_payload

        codes = intent_codes_from_payload(data)
        if codes:
            out["intent_codes"] = ",".join(codes)
    return out


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
    taken_title: str = "",
) -> list[dict[str, Any]]:
    ctx = project_candidate_context(user_text)
    raw_request = (user_text or "").strip()
    lines = [f"用户原话：{raw_request}", f"类型参考：{ctx.genre}"]
    drawn = subject.strip()
    if drawn:
        lines.append(f"题材：{drawn}")
    taken = taken_title.strip()
    if taken:
        lines.append(f"已用书名：{taken}")
    lines.extend(["", "交这本书的书名和简介。"])
    return [
        {"role": "system", "content": [{"type": "text", "text": _FORM_SYSTEM}]},
        user_message("\n".join(lines)),
    ]
