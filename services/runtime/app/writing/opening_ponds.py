"""开篇近池候选：结构化交卷，供聊天内点选（像 Plan 清单）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

OPENING_PONDS_REL = Path(".agent") / "work" / "opening_ponds.json"
# 勾选后发给下一回合的短令牌；聊天不画这条气泡。换皮约束在 format_opening_ponds_block。
MORE_PONDS_MESSAGE = "我要其他的"
OPENING_CHOICE_TOOL_ALLOWLIST = frozenset({"propose_opening_ponds", "stub_echo"})

START_KIND_LABELS: dict[str, str] = {
    "self_notice": "自己发觉能变强",
    "pulled_in": "被卷进已在运转的事",
    "granted_path": "系统/金手指落到身上",
    "world_already": "超凡已是这城的日常",
    "no_extraordinary": "先过日子，超凡往后放",
}
PROMISE_LABELS: dict[str, str] = {
    "power_steps": "变强台阶",
    "costly_truth": "查清会伤人的真相",
    "survive_relation": "在关系里活下去",
    "dread_decode": "解密/恐惧",
    "social_place": "社会位置改变",
}
SOURCE_TRUST_LABELS: dict[str, str] = {
    "trusted": "来源可信",
    "dubious": "来源不可信",
    "false": "来源是假的",
}
FIRST_CONFLICT_AT_LABELS: dict[str, str] = {
    "first_300": "前300字",
    "first_1000": "前1000字",
    "chapter_one": "第一章内",
    "later": "第一章之后",
}
_START_KIND_ALIASES: dict[str, tuple[str, ...]] = {
    "self_notice": (
        "自己发觉",
        "自己发觉能变强",
        "自己变强",
        "发觉能力",
        "自己发现",
        "身体异常",
        "发觉能做什么",
    ),
    "pulled_in": ("被卷进", "卷进", "已在运转", "拖进"),
    "granted_path": (
        "当场得到",
        "得到能用的路",
        "系统/金手指落到身上",
        "金手指落到",
        "开启系统",
        "系统",
    ),
    "world_already": (
        "一开始就不正常",
        "超凡已是这城的日常",
        "这城本来就在修真",
        "遍地修真",
        "世界已经",
        "机构内部的日常",
    ),
    "no_extraordinary": (
        "没有超凡",
        "本章没有超凡",
        "先过日子，超凡往后放",
        "先过日子",
        "平淡开局",
        "先不过超凡",
    ),
}
_PROMISE_ALIASES: dict[str, tuple[str, ...]] = {
    "power_steps": ("变强", "台阶", "升级"),
    "costly_truth": ("查清", "会伤人的真相", "真相会伤人"),
    "survive_relation": ("关系里活下去", "人情", "把债还上"),
    "dread_decode": ("解密", "恐惧", "克系"),
    "social_place": ("社会位置", "位置改变", "位子"),
}
_SOURCE_TRUST_ALIASES: dict[str, tuple[str, ...]] = {
    "false": ("来源是假的", "虚假", "是假的"),
    "dubious": ("来源不可信", "不可信", "来源可疑", "骗子师父"),
    "trusted": ("来源可信", "可信"),
}
_FIRST_CONFLICT_AT_ALIASES: dict[str, tuple[str, ...]] = {
    "later": ("第一章之后", "第一章后", "更后"),
    "first_300": ("前300字", "前 300 字"),
    "first_1000": ("前1000字", "前 1000 字"),
    "chapter_one": ("第一章内", "本章内"),
}

_OPENING_CHOICE_BLOCK = """## Opening choice (platform)
This turn is a Plan-like picker. Call `propose_opening_ponds` once with 2–3 items.
Each item needs title, flavor (这本书), opening, start_kind, promise,
source_trust, first_conflict_at.
The UI card the user reads is only: 书名 / 这本书 / 开篇.
Do not split a book into 账单 / 走向 / 气味. Those four slots make every card
a tax mechanic + a promotion catalog + the tax repeated as smell.
Do not sell the book as 系统 or 关系 labels. start_kind/promise/source_trust/
first_conflict_at are contrast only; they are not on the card.
Do not list the ponds in the assistant message. Do not call draft_section or
update_outline. The user checks a card (no chat bubble) or 我要其他的.

title = 连载书名, the name of the game that still holds at chapter 400
(《夜的命名术》《请勿高考时渡劫》《深空彼岸》).
Not a lyrical sketch, not a finite stack of props (七张收据、三次拒签).
工种+风雨+楼道 is not a title.
flavor = 这本书: who you follow on the board + the unfair rule of this world,
in a few sentences. Not weather. Not「每做一次就永久扣 X」as the whole pitch.
Not a career ladder (命席→盘外行→命庭). The rule can have a cost, but the
book is the game, not the invoice.
opening = how THAT game starts tonight. First sentence is the accident
（第一句写事故）.
opening and 这本书 are the same book: if opening is a tribulation-head and
the pitch is delivering a key, you glued two books.
who/where/want are optional and only if they are already inside 这本书/开篇.
Do not invent a civic countdown errand (换证、送钥匙、手术押金) as a fourth slot.
Do not stamp a 修真 bureau onto 窗口办事.

At least one book must be 都市异能, not a civic fable: a concrete ability on the
person that can be used on people tonight (看见、复制、暂停、强化、夺走).
The fight is other people (家族、组织、同类、黑市), not repairing the city's
power grid. 地铁阵法供能 / 天命维修 / 城市的根 / 命运故障 is a children's
municipal allegory, not 异能.
world_already = ability-users already live among people (地下场、家族、公司里
混着觉醒者). It is NOT 地铁用阵法供能、学校按灵压分班.
Do not open two books on 地铁/电梯/高架. Opening is at most two sentences.

Novelty is the game played straight, not a quirky vignette.
《修仙从替班开始》《我在药铺见过神仙》are exhausted gimmick titles.
鉴书/药铺/便利店 as the whole book is still 工种小品.
Opening starts the game, not 猎奇: 药柜滚出死人、表盘钻出手指、关东煮喷火.
At least one book is straight 都市修真 or 异能: 觉醒、能力、组织、当场能用在人身上.
Different start_kind is not a different book if all three are odd jobs with a grotesque prop.

For 都市修真 / 都市异能, think like a Qidian click, not a dock sketch.
Title sells the fantasy that still holds at chapter 400: the power, the
identity mismatch, or the board that will get bigger
(《一人万法》《请勿高考时渡劫》《夜的命名术》).
Not tonight's workplace number (《猎杀修士的第七码头》).
Prefer 3 cards so three hit engines each get one book — do not write two
dock-and-bridge stories:
1. 身份错位: 考生/职员/凡人的面子底下是渡劫、下凡、隐世家族.
2. 异能组织: 人身上的能力 + 立刻有人来收编或来杀, 街会放大成组织.
3. 金手指有阴谋: 系统/传法/师父不可信, 但力当场是真的、能打人.
Do not copy those books' plots. Opening must light up THIS book's power
(截留还回去、得法、觉醒), not 吊臂砸人 / 跳桥救人 / 浑身是血的人把信物按进掌心.

Three cards cannot all be 家人时限 + 一张会修真的纸 (收据/借据/灵契).
Three cards cannot all be 本市把修真做成公共服务 (考籍补录 / 巡天出勤 /
窗口办证). At least one book must not be a city bureau.
Three cards cannot all be the same tax-system (每坐一次忘一张脸 / 每次施术
丢一段记忆 / 每出门加一公里). Different start_kind is not a different book
if the engine is the same 永久扣费.

start_kind (required, unique): self_notice | pulled_in | granted_path |
world_already | no_extraordinary
promise (required, not all identical): power_steps | costly_truth |
survive_relation | dread_decode | social_place
source_trust (required): trusted | dubious | false. At least one of three must
not be trusted.
first_conflict_at (required): first_300 | first_1000 | chapter_one | later.
At most one later.
price and arc are optional leftovers; do not write them as the card, do not
fill 走向 with 院/司/宫 directories.

Job changes are not distinct. The handler rejects a set with no 这本书/开篇,
duplicate start_kind, all-same promise, reused previous start_kinds,
all-trusted source_trust (items≥3), more than one later first_conflict_at,
or (for 修真) no 自己变强/系统, 过日子 over quota, mood titles (title_is_mood),
long titles with no stake object (title_needs_stake), finite-count titles
(title_is_season: 七张收据、三次拒签), an opening whose first sentence is a
job bio with no accident (opening_no_accident), more than one family-deadline
errand (family_errand_collision), more than one civic countdown errand
(countdown_errand_collision: 零点前换证、封站前送钥匙), more than one
收据/借据/灵契 paper skin (paper_skin_collision), more than one job-bio who
(job_who_over_quota: 调货/陪护/上班族), more than one city-bureau cultivation
skin (bureau_over_quota: 考籍/巡天司/外院办证), or more than one
「每做一次永久扣一笔」tax engine (tax_engine_over_quota), more than one
civic fable (civic_fable_over_quota: 地铁阵法/天命维修/城市的根), or more
than one transit opening (transit_over_quota: 地铁/电梯), gimmick titles
(title_is_gimmick: 修仙从X开始、我在X见过神仙), workplace-number titles
(title_is_workplace: 第七码头), more than one quirk shop
(quirk_shop_over_quota: 便利店/药铺/鉴书), more than one grotesque
opening (grotesque_opening_over_quota: 药柜滚尸/表盘钻手指), or an opening
that is only a drop-in setpiece (opening_is_setpiece: 吊臂砸人/信物按进掌心).
dread_decode is for 灵异/克系.
Do not write a unifying summary (「三条都市修真」).
"""


def opening_choice_block() -> str:
    """volatile：开篇点选纪律（不焊进 system 前缀）。"""
    return _OPENING_CHOICE_BLOCK.strip()


def should_gate_opening_choice(
    message: str,
    *,
    outline: str | None = None,
    tool_names: list[str] | tuple[str, ...] | None = None,
    workspace_root: Path | None = None,
) -> bool:
    """Profile 有开篇工具、且本轮只要候选时，闸成只剩 propose_opening_ponds。"""
    if tool_names is not None and "propose_opening_ponds" not in tool_names:
        return False
    text = outline
    if text is None:
        path = _workspace(workspace_root) / "outline.md"
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
        else:
            text = ""
    from app.writing.outline_phase import wants_opening_candidates

    return wants_opening_candidates(message, outline=text)

_TITLE_MAX = 80
_FIELD_MAX = 240
_SUMMARY_MAX = 160
_PLAN_MAX = 400
_FLAVOR_MAX = 400
_PRICE_MAX = 160
_PLAN_MIN = 18
_FLAVOR_MIN = 8
_MIN_ITEMS = 2
_MAX_ITEMS = 4


def _workspace(workspace_root: Path | None = None) -> Path:
    if workspace_root is not None:
        return Path(workspace_root).resolve()
    from app.tenant_context import current_work_root_path

    return current_work_root_path()


def opening_ponds_path(workspace_root: Path | None = None) -> Path:
    return _workspace(workspace_root) / OPENING_PONDS_REL


def _clip(value: Any, max_len: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _normalize_enum(
    raw: Any,
    labels: dict[str, str],
    aliases: dict[str, tuple[str, ...]],
) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    key = text.lower().replace("-", "_").replace(" ", "_")
    if key in labels:
        return key
    for token, zh in labels.items():
        if text == zh:
            return token
    lowered = text.lower()
    for token, extra in aliases.items():
        for alias in extra:
            if alias.lower() == lowered or alias in text:
                return token
    return ""


def normalize_start_kind(raw: Any) -> str:
    return _normalize_enum(raw, START_KIND_LABELS, _START_KIND_ALIASES)


def normalize_promise(raw: Any) -> str:
    return _normalize_enum(raw, PROMISE_LABELS, _PROMISE_ALIASES)


def normalize_source_trust(raw: Any) -> str:
    return _normalize_enum(raw, SOURCE_TRUST_LABELS, _SOURCE_TRUST_ALIASES)


def normalize_first_conflict_at(raw: Any) -> str:
    return _normalize_enum(raw, FIRST_CONFLICT_AT_LABELS, _FIRST_CONFLICT_AT_ALIASES)


def start_kind_label(token: str) -> str:
    return START_KIND_LABELS.get(token, token)


def promise_label(token: str) -> str:
    return PROMISE_LABELS.get(token, token)


def source_trust_label(token: str) -> str:
    return SOURCE_TRUST_LABELS.get(token, token)


def first_conflict_at_label(token: str) -> str:
    return FIRST_CONFLICT_AT_LABELS.get(token, token)


def ponds_contrast_summary(items: list[dict[str, str]]) -> str:
    """对照用书名，不把整段这本书糊在顶栏。"""
    bits: list[str] = []
    for it in items:
        title = str(it.get("title") or "").strip()
        if title:
            bits.append(title)
    return " ｜ ".join(bits)


def normalize_pond_item(raw: dict[str, Any], index: int) -> dict[str, str]:
    """一条近池：书名 + 这本书 + 开篇。"""
    title = _clip(raw.get("title") or raw.get("name") or f"候选 {index + 1}", _TITLE_MAX)
    item_id = _clip(raw.get("id") or f"pond-{index + 1}", 32) or f"pond-{index + 1}"
    start_kind = normalize_start_kind(
        raw.get("start_kind") or raw.get("超凡怎么开始") or ""
    )
    promise = normalize_promise(raw.get("promise") or raw.get("读者买什么") or "")
    source_trust = normalize_source_trust(
        raw.get("source_trust") or raw.get("来源可信") or raw.get("力的来源") or ""
    )
    first_conflict_at = normalize_first_conflict_at(
        raw.get("first_conflict_at") or raw.get("第一场冲突") or ""
    )
    opening = _clip(raw.get("opening") or raw.get("开篇") or "", _PLAN_MAX)
    arc = _clip(
        raw.get("arc") or raw.get("走向") or raw.get("全篇走向") or "",
        _PLAN_MAX,
    )
    flavor = _clip(
        raw.get("flavor")
        or raw.get("这本书")
        or raw.get("book")
        or raw.get("风格")
        or raw.get("全篇风格")
        or "",
        _FLAVOR_MAX,
    )
    chapter_job = _clip(
        raw.get("chapter_job") or raw.get("这一章干什么") or opening,
        _FIELD_MAX,
    )
    return {
        "id": item_id,
        "title": title or f"候选 {index + 1}",
        "who": _clip(raw.get("who") or raw.get("跟着谁") or "", _FIELD_MAX),
        "where": _clip(raw.get("where") or raw.get("站在哪") or "", _FIELD_MAX),
        "want": _clip(raw.get("want") or raw.get("眼下要什么") or "", _FIELD_MAX),
        "chapter_job": chapter_job,
        "opening": opening,
        "arc": arc,
        "flavor": flavor,
        "price": _clip(raw.get("price") or raw.get("代价") or raw.get("账单") or "", _PRICE_MAX),
        "start_kind": start_kind,
        "promise": promise,
        "source_trust": source_trust,
        "first_conflict_at": first_conflict_at,
        "summary": _clip(raw.get("summary") or flavor, _SUMMARY_MAX),
    }


def normalize_pond_items(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        out.append(normalize_pond_item(item, i))
        if len(out) >= _MAX_ITEMS:
            break
    return out


def pond_item_event_fields(raw: dict[str, Any], index: int) -> dict[str, str] | None:
    """投影到 opening.ponds 事件：只留 schema 允许的字段。"""
    item = normalize_pond_item(raw, index)
    title = item.get("title") or ""
    if not title.strip():
        return None
    row = {"id": item["id"], "title": title}
    for key in (
        "who",
        "where",
        "want",
        "chapter_job",
        "opening",
        "arc",
        "flavor",
        "price",
        "summary",
    ):
        val = item.get(key) or ""
        if val:
            row[key] = val
    if item.get("start_kind") in START_KIND_LABELS:
        row["start_kind"] = item["start_kind"]
    if item.get("promise") in PROMISE_LABELS:
        row["promise"] = item["promise"]
    if item.get("source_trust") in SOURCE_TRUST_LABELS:
        row["source_trust"] = item["source_trust"]
    if item.get("first_conflict_at") in FIRST_CONFLICT_AT_LABELS:
        row["first_conflict_at"] = item["first_conflict_at"]
    return row


_FANTASY_HINT = re.compile(r"修真|玄幻|仙侠|爽文")
_OCCULT_HINT = re.compile(r"灵异|克系|恐怖|惊悚")
_PLAIN_LEAK = re.compile(r"秘密|盯上|灵异|失踪|无名尸|殡仪|冷藏")
_GIFT_HINT = re.compile(r"系统|金手指|功法|面板|异能|能力|觉醒")
_WORLD_HINT = re.compile(
    r"修真|灵气|功法|坊市|境界|灵石|宗门|工分|灵脉|"
    r"异能|能力者|觉醒"
)
_EARLY_KINDS = frozenset({"self_notice", "granted_path"})
_TITLE_WRAP = re.compile(r"^[《「『]+|[》」』]+$")
_TITLE_MOOD = re.compile(
    r"雨水|潮湿|风里|烟火气|楼道|旧楼|高架桥|慢慢|这座城|学会了打坐"
)
_TITLE_STAKE = re.compile(
    r"系统|金手指|功法|面板|山|劫|账|命|印|柜|债|米|牢|钟|雷|"
    r"骨|魂|妖|仙|神|帝|渡|死|修|力|证|单|窗|汤|班|据|契|丹"
)
_TITLE_STAKE_MIN = 7
_TITLE_SEASON = re.compile(
    r"[一二三四五六七八九十两\d]+\s*张|"
    r"[一二三四五六七八九十两\d]+\s*次拒"
)
_TITLE_GIMMICK = re.compile(
    r"修仙从|修真从|从.{0,8}开始$|我在.{0,12}见过"
)
_TITLE_WORKPLACE = re.compile(
    r"第[一二三四五六七八九十两\d]+(码头|号仓|工区|卸货)|"
    r"(码头|拳馆|卸货区)$"
)
_QUIRK_SHOP = re.compile(r"便利店|药铺|关东煮|旧书市场|鉴书|替班")
_GROTESQUE_OPEN = re.compile(
    r"浑身是血|钻出.{0,8}手指|关东煮|药柜.{0,16}滚"
)
_OPENING_SETPIECE = re.compile(
    r"吊臂|集装箱.{0,16}(脱钩|砸穿|砸)|"
    r"(宗门)?信物.{0,12}(按进|塞进|塞入)|"
    r"染血的(宗门)?信物"
)
_HERO_JUMP = re.compile(r"跳桥|跳江")
_TITLE_GAME = re.compile(r"劫|序列|彼岸|万族|星门|渡劫|命名|灵境|模拟|万法")
_BOARD_WHO = re.compile(r"囚犯|考生|打更|干员|执事|弟子|哨兵|学员|囚徒|序列")
_JOB_WHO = re.compile(r"调货|陪护|上班族|跑腿|代驾|合租|冷链")
_COUNTDOWN_ERRAND = re.compile(
    r"(赶在|在).{0,16}(零点|封站|关门|下班|截止|天亮).{0,24}(换|送|交|取|领|还)"
    r"|(换回|送到|交还|取回|换回来).{0,20}(准考证|钥匙|工牌|证件|包裹)"
)
_BUREAU_SKIN = re.compile(
    r"巡天司|考籍|外院考生|巡天吏|公共服务|教育体系|补证|市民服务"
)
_TAX_ENGINE = re.compile(
    r"每.{0,12}(一次|一回|一趟).{0,24}永久|"
    r"永久(忘掉|失去|增加|忘记)"
)
_CIVIC_FABLE = re.compile(
    r"地铁.{0,16}(阵法|灵脉)|天命维修|天命维护|命运故障|"
    r"城市的根|护城阵|第二轮太阳|印记.{0,12}认主|"
    r"替这座城|维修程序|灵网.{0,12}停电"
)
_TRANSIT_OPEN = re.compile(r"地铁|电梯|高架|末班车|站台")
_PERSONAL_ABILITY = re.compile(
    r"异能|觉醒|透视|复制|暂停|强化|精神力|截留|万法|"
    r"能看见|能停|能复制|能夺走|能控制|能力落在"
)
_OPENING_ACCIDENT = re.compile(
    r"失控|死|撞|裂|没有|只有|签收|少了|扣|逼|爆|血|劫|雷|灭|"
    r"停|柜门|系统|功法|面板|金手指|发现自己|亮了|空了|"
    r"一只手|那只手|铜印"
)
_FAMILY_ERRAND = re.compile(
    r"(母亲|父亲|爸|妈|妹妹|弟弟).{0,32}(手术|押金|尾款|解约|强拆|药|病房|调货)"
    r"|(手术|押金|尾款|解约|强拆).{0,24}(母亲|父亲|爸|妈|妹妹|弟弟)"
)
_PAPER_SKIN = re.compile(r"收据|借据|发票|合同|灵契|契据")
_ARC_WORLD_LAYER = re.compile(
    r"境界|序列|职阶|隐世|秘境|第二世界|星域|深空|位面|诸天|"
    r"模拟器|灵境|教会|万族|星门|渡劫|副本|宗门"
)


def _pond_blob(item: dict[str, str]) -> str:
    return "".join(
        str(item.get(key) or "")
        for key in (
            "title",
            "who",
            "where",
            "want",
            "chapter_job",
            "opening",
            "arc",
            "flavor",
            "summary",
        )
    )


def _title_core(title: str) -> str:
    return _TITLE_WRAP.sub("", (title or "").strip())


def _opening_lead(opening: str) -> str:
    text = (opening or "").strip()
    if not text:
        return ""
    return re.split(r"[。！？\n]", text, maxsplit=1)[0][:80]


def ponds_reject_reason(
    items: list[dict[str, str]],
    *,
    message: str = "",
    previous_kinds: set[str] | frozenset[str] | None = None,
) -> tuple[str, str] | None:
    """拒共线集合。旧 sidecar 缺字段时不走这条（只在 propose 时调用）。"""
    if len(items) < _MIN_ITEMS:
        return (
            "need_two_ponds",
            "至少交 2 个开篇候选，且 start_kind 不得重复。",
        )
    kinds = [str(it.get("start_kind") or "") for it in items]
    promises = [str(it.get("promise") or "") for it in items]
    if any(not k or not p for k, p in zip(kinds, promises)):
        return (
            "need_start_kind_and_promise",
            "每份都要有 start_kind 和 promise。"
            f" start_kind∈{tuple(START_KIND_LABELS)}；"
            f" promise∈{tuple(PROMISE_LABELS)}。",
        )
    if (
        _FANTASY_HINT.search(message or "")
        and len(items) >= 3
        and sum(1 for k in kinds if k == "no_extraordinary") > 1
    ):
        return (
            "plain_over_quota",
            "先过日子至多一份，三份里不要两份都在过普通日子。",
        )
    if len(set(kinds)) < len(kinds):
        return (
            "start_kind_collision",
            "start_kind 不得重复。换职业地点不算分开。"
            f" 已交：{kinds}。",
        )
    if len(set(promises)) == 1:
        return (
            "promise_collision",
            "promise 不得全员相同。"
            f" 已交：{promises[0]}。",
        )
    trusts = [str(it.get("source_trust") or "") for it in items]
    if any(t not in SOURCE_TRUST_LABELS for t in trusts):
        return (
            "need_source_trust",
            (
                "每份都要有 source_trust。"
                f" source_trust∈{tuple(SOURCE_TRUST_LABELS)}。"
            ),
        )
    if len(items) >= 3 and all(t == "trusted" for t in trusts):
        return (
            "trust_all_clean",
            "三份里至少一份的力来源不可信（source_trust 为 dubious 或 false）。",
        )
    conflicts = [str(it.get("first_conflict_at") or "") for it in items]
    if any(c not in FIRST_CONFLICT_AT_LABELS for c in conflicts):
        return (
            "need_first_conflict_at",
            (
                "每份都要写清第一场冲突位置（first_conflict_at）。"
                f" first_conflict_at∈{tuple(FIRST_CONFLICT_AT_LABELS)}。"
            ),
        )
    if sum(1 for c in conflicts if c == "later") > 1:
        return (
            "later_over_quota",
            "first_conflict_at=later 至多一份，不要把冲突都放到第一章之后。",
        )
    if previous_kinds:
        overlap = sorted(set(kinds) & set(previous_kinds))
        if overlap:
            unused = [
                start_kind_label(k)
                for k in START_KIND_LABELS
                if k not in previous_kinds
            ]
            hint = "、".join(unused) if unused else "（五种都用过了，改 promise 和场面）"
            return (
                "kinds_repeat",
                "上一组已经用过这些 start_kind，换还没用过的。"
                f" 重复：{overlap}。还没用过：{hint}。",
            )
    axis_names = set(START_KIND_LABELS.values()) | set(PROMISE_LABELS.values())
    for it in items:
        opening = str(it.get("opening") or "").strip()
        flavor = str(it.get("flavor") or "").strip()
        if flavor in axis_names:
            return (
                "plan_is_axis",
                "这本书不要直接填变强台阶/在关系里活下去这类对照标签。",
            )
        if len(opening) < _PLAN_MIN or len(flavor) < _FLAVOR_MIN:
            return (
                "need_book_plan",
                "每份都要有这本书和开篇：这本书在玩什么、开篇怎么进。"
                "不要拆成账单/走向/气味，不要只填系统/关系标签。",
            )
    for it in items:
        blob = _pond_blob(it)
        kind = str(it.get("start_kind") or "")
        if kind == "no_extraordinary" and _PLAIN_LEAK.search(blob):
            return (
                "plain_not_plain",
                "no_extraordinary 必须是先过日子，不能写成殡仪馆/失踪/城市秘密。",
            )
    if _FANTASY_HINT.search(message or ""):
        kind_set = set(kinds)
        if not (kind_set & _EARLY_KINDS):
            return (
                "need_normal_opening",
                "修真/玄幻候选要有至少一份自己变强或系统/金手指。",
            )
        if not _OCCULT_HINT.search(message or ""):
            if any(p == "dread_decode" for p in promises):
                return (
                    "dread_not_cultivation",
                    "修真/玄幻默认买变强台阶或社会位置，解密/恐惧留给用户点名灵异、克系时。",
                )
        family_n = 0
        paper_n = 0
        job_who_n = 0
        countdown_n = 0
        bureau_n = 0
        tax_n = 0
        civic_n = 0
        transit_n = 0
        quirk_n = 0
        grotesque_n = 0
        for it in items:
            if str(it.get("start_kind") or "") == "no_extraordinary":
                continue
            if _FAMILY_ERRAND.search(str(it.get("want") or "")):
                family_n += 1
            paper_blob = _title_core(str(it.get("title") or "")) + str(
                it.get("flavor") or ""
            )
            if _PAPER_SKIN.search(paper_blob):
                paper_n += 1
            if _JOB_WHO.search(str(it.get("who") or "")):
                job_who_n += 1
            if _COUNTDOWN_ERRAND.search(str(it.get("want") or "")):
                countdown_n += 1
            if _BUREAU_SKIN.search(_pond_blob(it)):
                bureau_n += 1
            tax_blob = str(it.get("flavor") or "") + str(it.get("price") or "")
            if _TAX_ENGINE.search(tax_blob):
                tax_n += 1
            if _CIVIC_FABLE.search(_pond_blob(it)):
                civic_n += 1
            if _TRANSIT_OPEN.search(
                str(it.get("opening") or "") + str(it.get("where") or "")
            ):
                transit_n += 1
            if _QUIRK_SHOP.search(_pond_blob(it)):
                quirk_n += 1
            if _GROTESQUE_OPEN.search(str(it.get("opening") or "")):
                grotesque_n += 1
        if family_n > 1:
            return (
                "family_errand_collision",
                "至多一份可以是今晚为家人凑药费/押金/解约。其余几本的问题必须是已经在运转的规则，不要三本都靠孝心时限撑着。",
            )
        if countdown_n > 1:
            return (
                "countdown_errand_collision",
                "至多一份可以是窗口倒计时办事（零点前换证、封站前送钥匙）。眼下要什么应是这场事故上的第一步，不要两本都靠公务时限进场。",
            )
        if paper_n > 1:
            return (
                "paper_skin_collision",
                "收据/借据/灵契这种文书皮至多一份。不要三本都把今晚的急事盖成一张会修真的纸。",
            )
        if job_who_n > 1:
            return (
                "job_who_over_quota",
                "跟着谁至多一份可以是工种自我介绍。其余几本要是棋盘上可晋升的位置（囚犯/考生/打更人/干员），不要三本都是调货、陪护、上班族。",
            )
        if bureau_n > 1:
            return (
                "bureau_over_quota",
                "本市公务修真（考籍补录、巡天出勤、窗口办证）至多一份。其余几本换引擎，不要两本都是这座城的两个局。",
            )
        if tax_n > 1:
            return (
                "tax_engine_over_quota",
                "「每做一次就永久扣一笔」这种扣费引擎至多一份。其余几本换玩法，不要三本都靠记忆税/公里税把书撑起来。",
            )
        if civic_n > 1:
            return (
                "civic_fable_over_quota",
                "地铁阵法、天命维修、城市的根这种市政寓言至多一份。至少一本要是人身上能当场用的异能，对手是人不是给城市修电路。",
            )
        if transit_n > 1:
            return (
                "transit_over_quota",
                "地铁/电梯/高架开场至多一份。异能小说的第一句是能力落在人身上，不要两本都从公共交通进场。",
            )
        if quirk_n > 1:
            return (
                "quirk_shop_over_quota",
                "鉴书、药铺、便利店、替班这种脑洞工种至多一份。新意在游戏规则写直，不要三本都靠奇葩职业撑着。",
            )
        if grotesque_n > 1:
            return (
                "grotesque_opening_over_quota",
                "药柜滚尸、表盘钻手指、关东煮喷火这种猎奇开场至多一份。事故是这盘游戏开始，不是小品道具。",
            )
        for it in items:
            blob = _pond_blob(it)
            kind = str(it.get("start_kind") or "")
            if kind == "granted_path" and not _GIFT_HINT.search(blob):
                return (
                    "gift_not_gift",
                    "granted_path 请写成系统、金手指、功法或异能落到身上，不要收雷/灵异物件。",
                )
            if kind == "world_already" and not _WORLD_HINT.search(blob):
                return (
                    "world_not_cultivation",
                    "world_already 请写成超凡已经混在人群里（异能者/修士），不是灵异出事，也不是地铁在供能。",
                )
        for it in items:
            kind = str(it.get("start_kind") or "")
            if kind == "no_extraordinary":
                continue
            core = _title_core(str(it.get("title") or ""))
            if _TITLE_SEASON.search(core):
                return (
                    "title_is_season",
                    "书名要是四百章还站得住的游戏名，不要写成七张收据、三次拒签这种一季道具。",
                )
            if _TITLE_GIMMICK.search(core):
                return (
                    "title_is_gimmick",
                    "书名要是这盘游戏的名字，不要写成修仙从替班开始、我在药铺见过神仙这种脑洞小品。",
                )
            if _TITLE_WORKPLACE.search(core):
                return (
                    "title_is_workplace",
                    "书名要卖能力、身份错位或会变大的局，不要写成猎杀修士的第七码头这种今晚的工作地点。",
                )
            if _TITLE_MOOD.search(core) and not _TITLE_STAKE.search(core):
                return (
                    "title_is_mood",
                    "书名要是连载钩子（不可能物件或可数的账），不要写成风雨楼道散文诗。",
                )
            if len(core) >= _TITLE_STAKE_MIN and not _TITLE_STAKE.search(core):
                return (
                    "title_needs_stake",
                    "书名要点出这本书后几百章还在用的那件东西（山/劫/柜/账/系统），不要只写今晚的地方。",
                )
            lead = _opening_lead(str(it.get("opening") or ""))
            if lead and not _OPENING_ACCIDENT.search(lead):
                return (
                    "opening_no_accident",
                    "开篇第一句写事故（少了、撞上、柜门、力亮了），不要写成工种小传。",
                )
            if _OPENING_SETPIECE.search(str(it.get("opening") or "")):
                return (
                    "opening_is_setpiece",
                    "开篇要让这本书广告的那股力亮起来，不要吊臂砸人、集装箱脱钩、把染血信物按进掌心。",
                )
    return None


def pond_serial_scale(item: dict[str, str]) -> int:
    """连载体量：游戏名 / 这本书的棋盘；一季道具、工种、扣费口号减分。"""
    title = _title_core(str(item.get("title") or ""))
    who = str(item.get("who") or "")
    want = str(item.get("want") or "")
    flavor = str(item.get("flavor") or "")
    pitch = title + who + flavor
    score = 0
    if _TITLE_GAME.search(pitch):
        score += 2
    if _ARC_WORLD_LAYER.search(flavor):
        score += 1
    if _BOARD_WHO.search(who) or _BOARD_WHO.search(flavor):
        score += 2
    if _TITLE_STAKE.search(title):
        score += 1
    if _JOB_WHO.search(who):
        score -= 3
    if _TITLE_SEASON.search(title):
        score -= 4
    if _TITLE_MOOD.search(title):
        score -= 2
    if _FAMILY_ERRAND.search(want):
        score -= 2
    if _COUNTDOWN_ERRAND.search(want):
        score -= 2
    if _TAX_ENGINE.search(flavor + str(item.get("price") or "")):
        score -= 2
    if _CIVIC_FABLE.search(pitch + str(item.get("opening") or "")):
        score -= 3
    if _TRANSIT_OPEN.search(str(item.get("opening") or "")):
        score -= 1
    if _TITLE_GIMMICK.search(title):
        score -= 3
    if _TITLE_WORKPLACE.search(title):
        score -= 3
    if _QUIRK_SHOP.search(pitch + str(item.get("opening") or "")):
        score -= 2
    if _GROTESQUE_OPEN.search(str(item.get("opening") or "")):
        score -= 2
    if _OPENING_SETPIECE.search(str(item.get("opening") or "")):
        score -= 2
    if _HERO_JUMP.search(str(item.get("opening") or "")):
        score -= 1
    if _PERSONAL_ABILITY.search(pitch):
        score += 2
    if _BUREAU_SKIN.search(title + who + str(item.get("where") or "") + want):
        score -= 1
    if _PAPER_SKIN.search(title + flavor):
        score -= 1
    return score


def rank_opening_ponds(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """点选卡片按连载体量排序，不丢候选。"""
    return sorted(items, key=pond_serial_scale, reverse=True)


def save_opening_ponds(
    items: list[dict[str, str]],
    *,
    summary: str = "",
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """写入 sidecar，返回事件 payload。"""
    ponds_id = f"ponds-{uuid4().hex[:8]}"
    contrast = ponds_contrast_summary(items)
    body = {
        "ponds_id": ponds_id,
        "summary": contrast or _clip(summary, 4096),
        "items": items,
    }
    path = opening_ponds_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return body


def load_opening_ponds(*, workspace_root: Path | None = None) -> dict[str, Any] | None:
    path = opening_ponds_path(workspace_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    items = normalize_pond_items(data.get("items"))
    if len(items) < _MIN_ITEMS:
        return None
    return {
        "ponds_id": str(data.get("ponds_id") or "ponds"),
        "summary": str(data.get("summary") or ""),
        "items": items,
    }


def clear_opening_ponds(*, workspace_root: Path | None = None) -> bool:
    path = opening_ponds_path(workspace_root)
    if not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


_COMMIT_TITLE_RE = re.compile(
    r"(?:按开篇候选|采用此开篇|按此开篇)[「『](.+?)[」』]"
)


def format_select_pond_message(item: dict[str, str]) -> str:
    """勾选后发给下一回合的令牌；聊天不画这条气泡。"""
    title = (item.get("title") or item.get("id") or "").strip()
    return f"采用此开篇「{title}」"


def committed_pond_title(message: str) -> str | None:
    text = (message or "").strip()
    if not text:
        return None
    match = _COMMIT_TITLE_RE.search(text)
    title = (match.group(1) if match else "").strip()
    return title or None


def find_committed_pond(
    *,
    message: str,
    workspace_root: Path | None,
) -> dict[str, str] | None:
    title = committed_pond_title(message)
    if not title:
        return None
    data = load_opening_ponds(workspace_root=workspace_root)
    if not data:
        return None
    for item in data["items"]:
        if (item.get("title") or item.get("id") or "").strip() == title:
            return item
    return None


def format_committed_pond_block(
    *,
    message: str,
    workspace_root: Path | None = None,
) -> str:
    """volatile：用户只点了选择，卡片正文从 sidecar 灌给模型。"""
    item = find_committed_pond(message=message, workspace_root=workspace_root)
    if not item:
        return ""
    title = item.get("title") or item.get("id") or ""
    lines = [
        "## 已选开篇",
        "用户在卡片上勾选了一份。按下面这份写第一章，不要再出候选。",
        "这是一本能连载的书。按「这本书」和「开篇」写；不要另起账单、走向、气味三栏，也不要另起窗口办事。",
        f"书名：{title}",
    ]
    if item.get("flavor"):
        lines.append(f"这本书：{item['flavor']}")
    if item.get("opening"):
        lines.append(f"开篇：{item['opening']}")
    trust = str(item.get("source_trust") or "")
    if trust:
        lines.append(f"力的来源：{source_trust_label(trust)}")
    if item.get("who"):
        lines.append(f"棋盘位：{item['who']}")
    if item.get("where"):
        lines.append(f"站在哪：{item['where']}")
    if item.get("want"):
        lines.append(f"入口（不是这本书要解决的事）：{item['want']}")
    kind = str(item.get("start_kind") or "")
    promise = str(item.get("promise") or "")
    if kind:
        lines.append(f"超凡怎么开始：{start_kind_label(kind)}")
    if promise:
        lines.append(f"读者买什么：{promise_label(promise)}")
    return "\n".join(lines)


def format_opening_ponds_block(*, workspace_root: Path | None = None) -> str:
    """volatile：上一组候选，下一组不得复用同一 start_kind。"""
    data = load_opening_ponds(workspace_root=workspace_root)
    if not data:
        return ""
    used = {
        str(item.get("start_kind") or "")
        for item in data["items"]
        if item.get("start_kind")
    }
    unused = [
        start_kind_label(k) for k in START_KIND_LABELS if k not in used
    ]
    unused_line = "、".join(unused) if unused else "五种都用过了，改场面和 promise"
    lines = [
        "## 上一组开篇候选（不要换皮重写）",
        "换皮 = start_kind 与上一组相同，只换职业地点或换一套系统皮。",
        f"下一组必须用还没用过的 start_kind：{unused_line}。",
        "下一组写成书名 + 这本书 + 开篇，不要再拆账单/走向/气味。",
        "每份仍要是一本不同的书，不要只交对照标签。",
    ]
    for item in data["items"]:
        title = item.get("title") or item.get("id")
        flavor = item.get("flavor") or ""
        kind = start_kind_label(str(item.get("start_kind") or ""))
        bit = " · ".join(p for p in (title, flavor, kind) if p)
        lines.append(f"- {bit}" if bit else f"- {title}")
    return "\n".join(lines)
