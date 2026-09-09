"""prose 专用指标。"""

from __future__ import annotations

import re
from typing import Any

from app.writing.staccato import staccato_fields
from app.writing.text_metrics import visible_chars

_SENT_SPLIT = re.compile(r"[。！？!?\n]+")
_DIALOGUE_OR_ACTION = re.compile(
    r'[「」『』“”"].+|说道|问道|答道|点了点头|摇了摇头|转身|推门|拔刀|拔枪'
)
_SYNOPSIS_CUE = re.compile(
    r"本章讲述|本章先|这一章|由此可见|概括|总结起来|总而言之|"
    r"到了这一刻|所有的铺垫|命运就此|踏上旅程"
)
_MOTION = re.compile(
    r"走|站|坐|跑|冲|咬|劈|拉|飞|缩|摸|递|喊|叫|望|进|来|去|喝|买|温|捧|塞|抢|射"
)
_HOOK_CUE = re.compile(
    r"变|劫|觉醒|突破|灵根|秘境|妖|系统|传承|血脉|天赋|"
    r"金丹|元婴|练气|功法|天机|预言|诅咒|"
    r"灵气|真气|修士|外门|内门|入门|异能|灵石|师兄|师姐|炼体|"
    r"乱世"
)
_CULTIVATION_LANDING = re.compile(
    r"功法|系统|灵气|灵根|丹田|面板|觉醒|传承|入体|金丹|元婴|练气"
)
_CONFLICT_CUE = re.compile(
    r"杀|战|危|敌|疑|秘|死|失踪|不对|奇怪|突然|竟然|发现|追|逃|挡|抢|威胁"
)
_BODY = re.compile(r"手|头|眼|脸|嘴|肩|脚|臂|鼻")
_PERSON = re.compile(r"他|她|我|你|们|说|道")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def paragraphs(text: str) -> list[str]:
    """分段。
    
    参数:
        text。
    
    返回:
        list。"""
    body = (text or "").strip()
    parts = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    return parts or ([body] if body else [])


def sentence_count(text: str) -> int:
    """句数。
    
    参数:
        text。
    
    返回:
        int。"""
    return len([p for p in _SENT_SPLIT.split(text or "") if p.strip()])


def paragraph_shown(para: str) -> bool:
    """段是否在场上。
    
    参数:
        para。
    
    返回:
        bool。"""
    if "「" in para and "」" in para:
        return True
    # Told-not-shown: 终于/本章/于是 without a spoken beat.
    if _SYNOPSIS_CUE.search(para):
        return False
    if _DIALOGUE_OR_ACTION.search(para):
        return True
    return bool(_MOTION.search(para) or _BODY.search(para))


def narrative_scene_ratio(text: str) -> float:
    """场面比。
    
    参数:
        text。
    
    返回:
        float。"""
    paras = paragraphs(text)
    if not paras:
        return 0.0
    hits = sum(1.0 if paragraph_shown(p) else 0.0 for p in paras)
    syn = sum(0.5 for p in paras if _SYNOPSIS_CUE.search(p) and not ("「" in p and "」" in p))
    return round(_clamp((hits - syn) / len(paras)), 4)


def synopsis_rate(text: str) -> float:
    """提要段比例。
    
    参数:
        text。
    
    返回:
        float。"""
    paras = paragraphs(text)
    if not paras:
        return 0.0
    n = sum(1 for p in paras if _SYNOPSIS_CUE.search(p) and not ("「" in p and "」" in p))
    return round(n / len(paras), 4)


def has_person_on_stage(text: str) -> bool:
    """是否有人在场。
    
    参数:
        text。
    
    返回:
        bool。"""
    body = text or ""
    return bool(_PERSON.search(body) or ("「" in body and "」" in body))


def shown_for_fragment(fragment: str, *, scene: float, feats: dict[str, float]) -> bool:
    """类型 aware shown。
    
    参数:
        fragment/scene/feats。
    
    返回:
        bool。"""
    quote = float(feats.get("quote_ratio") or 0.0)
    battle = float(feats.get("battle_density") or 0.0)
    world = float(feats.get("world_density") or 0.0)
    if fragment == "dialogue_dyad":
        return scene >= 0.45 and quote >= 0.20
    if fragment == "battle_action":
        return battle >= 0.12 or scene >= 0.40
    if fragment == "worldview_texture":
        return world >= 0.08 or (scene >= 0.35 and quote < 0.45)
    if fragment == "climax_beat":
        return scene >= 0.30
    if fragment == "plot_progress":
        return scene >= 0.25
    return scene >= 0.35


def anti_pattern_flags(
    text: str, rubric: dict[str, Any], *, work_mode: str = "literary"
) -> dict[str, bool]:
    """反模式 flags。"""
    from app.writing.hinge import hinge_fields

    staccato = bool(staccato_fields(text, work_mode=work_mode).get("staccato_uniform"))
    hinge = bool(hinge_fields(text).get("hinge_dense"))
    meta = float(rubric.get("meta_knowing_rate") or 0.0) >= 0.35
    glue = float(rubric.get("glue_rate") or 0.0) >= 0.35
    syn = synopsis_rate(text) >= 0.5
    return {
        "staccato": staccato,
        "hinge": hinge,
        "meta": meta,
        "glue": glue,
        "synopsis": syn,
    }


def serial_hook_flat(text: str, section_id: str = "") -> bool:
    """网文开篇空磨：平凡日子里既没得到、也没发现。

    功法、系统、灵气当场落到身上，不算空磨。
    开篇不能只靠「发现 / 突然 / 鬼怪」过关；得到或发现要早。
    """
    from app.writing.lore import is_opening_section

    if not is_opening_section(section_id):
        return False
    if visible_chars(text) < 400:
        return False
    window = (text or "")[:1600]
    if _CULTIVATION_LANDING.search(window) or _HOOK_CUE.search(window):
        return False
    if narrative_scene_ratio(text) >= 0.42:
        return False
    return True


def plot_step_visible(text: str) -> bool:
    """网文：情节台阶/冲突/悬念在场上可见。"""
    if visible_chars(text) < 120:
        return False
    body = text or ""
    if _HOOK_CUE.search(body) or _CONFLICT_CUE.search(body):
        return True
    return narrative_scene_ratio(body) >= 0.38 and bool(_MOTION.search(body))


_ANOMALY_CUE = re.compile(
    r"系统|金手指|功法|面板|灵气|铜印|异象|入体|觉醒|那只手|突然出现|凭空"
)
_EXPLAIN_CUE = re.compile(
    r"原来是|原来这|其实是|来源于|来自于|真相是|这是因为|解释是"
)
_BLANK_CUE = re.compile(
    r"说不清|说不准|不知道从哪|没人解释|来源不明|来历不明|不问来处"
)
_FAIL_RETREAT = re.compile(
    r"打不过|跑了|败了|败退|后退|逃了|撑不住|没挡住|没打过|认栽"
)
_PRICE_LAND = re.compile(r"代价|账单|少了|扣了|忘了|付了|只剩|寿命|记忆被")
_POWER_USE = re.compile(r"系统|功法|金手指|面板|灵气|入体|催动|运转|异能")
_COUNTABLE_LOSS = re.compile(
    r"\d+\s*(次|米|年|岁|条|格|层)|"
    r"少了.{0,8}(次|米|年|记忆)|"
    r"扣了|"
    r"付了.{0,8}(次|米|年)|"
    r"寿命.{0,8}(少|扣)"
)


def all_explained(text: str, *, work_mode: str = "literary") -> bool:
    """本章每个异常都给了来源或解释，无一处留白。"""
    from app.writing.work_mode import normalize_work_mode

    if normalize_work_mode(work_mode) != "web_serial":
        return False
    if visible_chars(text) < 400:
        return False
    body = text or ""
    if not _ANOMALY_CUE.search(body):
        return False
    if _BLANK_CUE.search(body):
        return False
    return bool(_EXPLAIN_CUE.search(body))


def escalation_flat(text: str, *, work_mode: str = "literary") -> bool:
    """整章无失败、无后退、无代价到账。"""
    from app.writing.work_mode import normalize_work_mode

    if normalize_work_mode(work_mode) != "web_serial":
        return False
    if visible_chars(text) < 400:
        return False
    body = text or ""
    if _FAIL_RETREAT.search(body) or _PRICE_LAND.search(body):
        return False
    if not (_POWER_USE.search(body) or _CONFLICT_CUE.search(body)):
        return False
    return True


def price_paid_visible(text: str, *, work_mode: str = "literary") -> bool:
    """力用过之后，同章内有可数的损失落地。"""
    from app.writing.work_mode import normalize_work_mode

    if normalize_work_mode(work_mode) != "web_serial":
        return False
    if visible_chars(text) < 200:
        return False
    body = text or ""
    if not _POWER_USE.search(body):
        return False
    return bool(_COUNTABLE_LOSS.search(body))


_WORLD_LAYER = re.compile(
    r"境界|序列|职阶|隐世|秘境|第二世界|星域|深空|位面|诸天|"
    r"模拟器|灵境|教会|万族|星门|渡劫|副本|宗门"
)
_NOVELLA_CLOSE = re.compile(
    r"(母亲|父亲|爸|妈|妹妹).{0,24}(救回|保住|尾款|押金|掀掉|解约)"
    r"|(救回|保住).{0,16}(母亲|父亲|妹妹)"
)


def world_layer_visible(text: str, *, work_mode: str = "literary") -> bool:
    """开篇能看见世界下一层（梯子/隐世/第二世界），不是本市案件收束。"""
    from app.writing.work_mode import normalize_work_mode

    if normalize_work_mode(work_mode) != "web_serial":
        return False
    if visible_chars(text) < 200:
        return False
    return bool(_WORLD_LAYER.search(text or ""))


def premise_novella(text: str, *, work_mode: str = "literary") -> bool:
    """开篇把家庭急事做完当成全书，且没有下一层。"""
    from app.writing.work_mode import normalize_work_mode

    if normalize_work_mode(work_mode) != "web_serial":
        return False
    if visible_chars(text) < 400:
        return False
    body = text or ""
    if _WORLD_LAYER.search(body):
        return False
    return bool(_NOVELLA_CLOSE.search(body))


def character_card_action_hit(text: str) -> bool:
    """人物卡姓名命中。
    
    参数:
        text。
    
    返回:
        bool。"""
    body = (text or "").strip()
    if visible_chars(body) < 40:
        return False
    try:
        from app.writing.cards import load_writing_cards

        cards = [c for c in load_writing_cards() if c.kind == "character"]
    except Exception:
        return False
    if not cards:
        return False
    for card in cards:
        name = (card.title or "").strip()
        if len(name) >= 2 and name in body:
            return True
    return False
