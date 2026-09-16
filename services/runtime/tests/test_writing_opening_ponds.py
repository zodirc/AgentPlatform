from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.writing.opening_ponds import (
    MORE_PONDS_MESSAGE,
    format_select_pond_message,
    load_opening_ponds,
    normalize_pond_items,
    normalize_promise,
    normalize_start_kind,
    opening_choice_block,
    ponds_reject_reason,
    should_gate_opening_choice,
)
from app.writing.outline_phase import wants_opening_candidates


_KIND_AXIS = {
    "self_notice": "status",
    "pulled_in": "contract",
    "granted_path": "memory",
    "world_already": "lifespan",
    "no_extraordinary": "none",
}


def _pitch(title: str) -> str:
    return (
        f"{title}写的是一个还在过日子的人被拖进这本书自己的局面："
        f"他每做一次选择，处境就改一截，新的处境又逼他再选。"
        f"读者追的是他怎么把这件事做成，以及做成之后会欠下什么。"
        f"局面本身不会在第一次反转后停住。"
    )


def _pond(
    title: str,
    *,
    start_kind: str,
    promise: str,
    who: str = "甲",
    where: str = "这里",
    want: str = "眼下这件事",
    opening: str = "",
    arc: str = "往后仍扣着这笔要的东西往前走，中段加压，隐世那一层会打开，不另开百科。",
    flavor: str = "",
    price: str = "",
    source_trust: str = "dubious",
    first_conflict_at: str = "chapter_one",
    price_axis: str = "",
    book_self_note: str = "",
) -> dict[str, str]:
    return {
        "title": title,
        "who": who,
        "where": where,
        "want": want,
        "opening": opening or _pitch(title),
        "arc": arc,
        "flavor": flavor,
        "price": price or f"付{title}一次",
        "start_kind": start_kind,
        "promise": promise,
        "source_trust": source_trust,
        "first_conflict_at": first_conflict_at,
        "price_axis": price_axis or _KIND_AXIS.get(start_kind, "none"),
        "book_self_note": book_self_note,
    }


def test_wants_opening_candidates_browse_and_commit() -> None:
    assert wants_opening_candidates("写一章长篇修真，我看看") is True
    assert wants_opening_candidates(MORE_PONDS_MESSAGE) is True
    assert MORE_PONDS_MESSAGE == "我要其他的"
    assert "start_kind" not in MORE_PONDS_MESSAGE
    assert (
        wants_opening_candidates("按开篇候选「早高峰系统」写第一章。") is False
    )
    assert wants_opening_candidates("采用此开篇「早高峰系统」") is False


def test_normalize_pond_item_maps_pitch_to_opening() -> None:
    items = normalize_pond_items(
        [
            {
                "title": "隔断",
                "pitch": "他在夜里把店门从里面闩上，灯管滋了一声。外面有人敲门。",
            },
            {
                "title": "虚岁",
                "opening": "她把名册翻回前一页，手指按在那一行上。",
            },
        ]
    )
    assert items[0]["opening"].startswith("他在夜里")
    assert "pitch" not in items[0]
    assert items[1]["opening"].startswith("她把名册")
    rejected = ponds_reject_reason(items)
    assert rejected is None or rejected[0] != "title_off_page"


def test_opening_choice_block_is_book_pitch_first() -> None:
    block = opening_choice_block()
    assert "### BOOK CANDIDATES" not in block
    assert "### CANDIDATE MODE" not in block
    assert "### TARGET SHELF" not in block
    assert "### TARGET SPACE" not in block
    assert "### MODEL ATTRACTOR" not in block
    assert "### FORM" not in block
    assert "### TWO BOOKS" not in block
    assert "### WORK CHECK" not in block
    assert "### HUMAN BOUNDARY" not in block
    assert "## Book choice" in block
    assert "empty `items`" in block
    assert "《诡秘之主》" not in block
    assert "读者长期追" not in block
    assert "作品空间" not in block
    assert "previous_attempt_discarded" not in block
    assert "《三环以内》" not in block
    assert "我刚才形成的是一本书" not in block
    assert "先找一个人" not in block
    assert "不要把职业当成故事的创意来源" not in block
    assert "Call `propose_book_candidates`" in block
    assert "Leave the assistant message empty" in block
    assert "张屠户" not in block
    assert "手停住了" not in block
    assert "写到这一拍停" not in block
    assert "绩效" not in block
    assert "封面" not in block
    assert 200 <= len(block) <= 4000


def test_candidate_mode_block_is_shelf_not_prose_rules() -> None:
    from app.writing.opening_ponds import candidate_mode_block

    block = candidate_mode_block()
    assert "### CANDIDATE MODE" in block
    assert "### TARGET SHELF" in block
    assert "不要总结它们的共同公式" in block
    assert "《诡秘之主》" in block
    assert "《第九特区》" in block
    assert "《我在精神病院里学斩神》" in block
    assert "《修真四万年》" in block
    assert "可以不出现在 pitch 中" in block
    assert "主角已经有" not in block
    assert "当成构思起点" in block
    assert "先写正在发生的事。" not in block
    assert "两本不同的书" not in block
    assert "读者长期追" not in block
    assert "作品空间" not in block
    assert "### TARGET SPACE" not in block
    assert "### MODEL ATTRACTOR" not in block
    assert "### WORK CHECK" not in block
    assert "### HUMAN BOUNDARY" not in block


def test_picking_prompt_omits_after_lock_craft(tmp_path, monkeypatch) -> None:
    from app.settings import settings
    from app.writing.cards import prepare_writing_system_prompt
    from app.writing.work_mode import SERIAL_AFTER_LOCK_CRAFT

    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    pin = prepare_writing_system_prompt(
        "You are a writing assistant.",
        "写一篇都市修真小说，我看看",
        workspace_root=tmp_path,
    )
    blob = "\n".join(
        x for x in (pin.prompt, pin.volatile_block, pin.cards_block) if x
    )
    assert "得到了什么" not in blob
    assert SERIAL_AFTER_LOCK_CRAFT not in blob
    locked = prepare_writing_system_prompt(
        "You are a writing assistant.",
        "采用此开篇「废脉剑声」。写都市修真第一章",
        workspace_root=tmp_path,
    )
    locked_blob = "\n".join(
        x for x in (locked.prompt, locked.volatile_block, locked.cards_block) if x
    )
    assert "不要把简介" in locked_blob
    assert "得到了什么" not in locked_blob


def test_should_gate_opening_choice_when_browsing() -> None:
    assert should_gate_opening_choice(
        "写一章长篇修真小说的第一章, 现代都市题材，我看看",
        outline="",
        tool_names=["propose_book_candidates", "draft_section"],
    )
    assert not should_gate_opening_choice(
        "采用此开篇「早高峰系统」",
        outline="",
        tool_names=["propose_book_candidates", "draft_section"],
    )
    assert not should_gate_opening_choice(
        "写一章长篇修真，我看看",
        outline="",
        tool_names=["draft_section"],
    )


def test_normalize_pond_items_maps_self_notes() -> None:
    items = normalize_pond_items(
        [
            {
                "title": "only",
                "这本书在玩什么": "城中村停水之后邻里的术互相卡住",
                "社会角落": "城中村天台",
                "为什么能一直写": "停水结阵把整栋楼的日子卡住",
            }
        ]
    )
    assert items[0]["book_self_note"].startswith("城中村")
    assert items[0]["social_space"] == "城中村天台"
    assert "停水" in items[0]["engine_note"]
    assert items[0]["start_kind"] == ""


def test_normalize_start_kind_aliases() -> None:
    assert normalize_start_kind("自己发觉") == "self_notice"
    assert normalize_start_kind("开启系统") == "granted_path"
    assert normalize_start_kind("平淡开局") == "no_extraordinary"
    assert normalize_promise("变强台阶") == "power_steps"
    from app.writing.opening_ponds import (
        normalize_first_conflict_at,
        normalize_price_axis,
        normalize_source_trust,
    )

    assert normalize_source_trust("来源不可信") == "dubious"
    assert normalize_first_conflict_at("前300字") == "first_300"
    assert normalize_price_axis("烧寿") == "lifespan"
    assert normalize_price_axis("用记忆结账") == "memory"
    assert normalize_price_axis("灵契") == ""
    assert normalize_price_axis("仙籍") == ""
    assert normalize_price_axis("功簿") == ""
    assert normalize_price_axis("工分") == ""


def test_fill_pond_defaults_does_not_invent_axes() -> None:
    from app.writing.opening_ponds import fill_pond_defaults

    items = normalize_pond_items(
        [
            _pond("保安窗", start_kind="pulled_in", promise="dread_decode"),
            _pond("实习生窗", start_kind="pulled_in", promise="power_steps"),
        ]
    )
    items[0]["start_kind"] = "pulled_in"
    items[1]["start_kind"] = "pulled_in"
    items[0]["source_trust"] = ""
    items[1]["source_trust"] = ""
    items[0]["first_conflict_at"] = ""
    items[1]["first_conflict_at"] = ""
    filled = fill_pond_defaults(items)
    kinds = [str(it.get("start_kind")) for it in filled]
    assert kinds == ["pulled_in", "pulled_in"]
    assert filled[0]["source_trust"] == ""
    assert filled[1]["source_trust"] == ""
    assert filled[0]["first_conflict_at"] == ""
    assert filled[1]["first_conflict_at"] == ""


def test_retired_axis_codes_no_longer_reject() -> None:
    same_kind = normalize_pond_items(
        [
            _pond("保安窗", start_kind="pulled_in", promise="dread_decode", who="保安"),
            _pond("实习生窗", start_kind="pulled_in", promise="power_steps", who="实习生"),
        ]
    )
    assert ponds_reject_reason(same_kind) is None

    same_promise = normalize_pond_items(
        [
            _pond("A窗", start_kind="self_notice", promise="power_steps"),
            _pond("B窗", start_kind="pulled_in", promise="power_steps"),
        ]
    )
    assert ponds_reject_reason(same_promise) is None

    same_axis = normalize_pond_items(
        [
            _pond("借火", start_kind="self_notice", promise="power_steps", price_axis="lifespan"),
            _pond("功簿", start_kind="pulled_in", promise="costly_truth", price_axis="lifespan"),
        ]
    )
    assert ponds_reject_reason(same_axis) is None

    missing_axis = normalize_pond_items(
        [
            {**_pond("A窗", start_kind="self_notice", promise="power_steps"), "price_axis": "", "start_kind": "", "promise": ""},
            _pond("B窗", start_kind="pulled_in", promise="costly_truth"),
        ]
    )
    assert ponds_reject_reason(missing_axis) is None

    reused = ponds_reject_reason(
        normalize_pond_items(
            [
                _pond("A窗", start_kind="self_notice", promise="power_steps"),
                _pond("B窗", start_kind="pulled_in", promise="costly_truth"),
            ]
        ),
        message=MORE_PONDS_MESSAGE,
    )
    assert reused is None

    gothic = normalize_pond_items(
        [
            _pond("替人收下一场雷", start_kind="granted_path", promise="power_steps"),
            _pond(
                "失踪者",
                start_kind="no_extraordinary",
                promise="dread_decode",
                who="殡仪馆化妆师",
                where="冷藏库",
            ),
        ]
    )
    assert ponds_reject_reason(gothic, message="写一份都市修真小说，我看看") is None

    all_clean = normalize_pond_items(
        [
            _pond("A窗", start_kind="self_notice", promise="power_steps", source_trust="trusted"),
            _pond("B窗", start_kind="pulled_in", promise="costly_truth", source_trust="trusted"),
            _pond("C窗", start_kind="granted_path", promise="social_place", source_trust="trusted"),
        ]
    )
    assert ponds_reject_reason(all_clean) is None

    two_later = normalize_pond_items(
        [
            _pond("A窗", start_kind="self_notice", promise="power_steps", first_conflict_at="later"),
            _pond("B窗", start_kind="pulled_in", promise="costly_truth", first_conflict_at="later"),
        ]
    )
    assert ponds_reject_reason(two_later) is None

    axis = normalize_pond_items(
        [
            _pond("A窗", start_kind="granted_path", promise="power_steps", flavor="变强台阶"),
            _pond("B窗", start_kind="no_extraordinary", promise="survive_relation", flavor="在关系里活下去"),
        ]
    )
    assert ponds_reject_reason(axis) is None


def test_kept_reject_codes() -> None:
    assert ponds_reject_reason([])[0] == "need_two_ponds"
    empty = normalize_pond_items(
        [
            {**_pond("A窗", start_kind="granted_path", promise="power_steps"), "opening": "", "flavor": ""},
            {**_pond("B窗", start_kind="no_extraordinary", promise="survive_relation"), "opening": "", "flavor": ""},
        ]
    )
    assert (ponds_reject_reason(empty) or ("", ""))[0] == "pitch_too_short"
    montage = normalize_pond_items(
        [
            {
                "title": "下山",
                "opening": (
                    "他在山上待了二十七年。师父咽气前把一只旧木匣塞给他，让他进城，送到城南一户人家手上。"
                    "他下山第二天找到那片巷子，那里已经拆了三年，原地方立着一个超市。"
                    "他没回去，在对面租了间房，每天去问。到第二十天，那只匣子比下山时重了。"
                ),
            },
            _pond("末班车", start_kind="pulled_in", promise="dread_decode"),
        ]
    )
    assert ponds_reject_reason(montage) is None


def test_ponds_contrast_summary_is_book_pitch(workspace: Path) -> None:
    from app.writing.opening_ponds import ponds_contrast_summary, save_opening_ponds

    items = normalize_pond_items(
        [
            _pond("跑单换力气", start_kind="granted_path", promise="power_steps", flavor="城南跑单的人把奔波换成能用的力气"),
            _pond("先把这锅汤端稳", start_kind="no_extraordinary", promise="survive_relation", flavor="合租房里把日子过下去，超凡先别来"),
        ]
    )
    line = ponds_contrast_summary(items)
    assert line == "跑单换力气 ｜ 先把这锅汤端稳"
    saved = save_opening_ponds(items, summary="三条不同的都市修真近池", workspace_root=workspace)
    assert saved["summary"] == line


def test_opening_ponds_edge_paths(workspace: Path) -> None:
    from app.writing.opening_ponds import opening_ponds_path, pond_item_event_fields

    assert normalize_pond_items("nope") == []
    assert len(normalize_pond_items([{"title": "x"}] * 5 + ["skip"])) == 4
    path = opening_ponds_path(workspace_root=workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")
    assert load_opening_ponds(workspace_root=workspace) is None
    msg = format_select_pond_message({"title": "A", "id": "p"})
    assert msg == "采用此开篇「A」"
    row = pond_item_event_fields(
        {
            "title": "早高峰系统",
            "book_self_note": "面板换班把家里卷进去",
            "social_space": "写字楼大堂",
            "engine_note": "换班代价按夜叠加",
            "start_kind": "granted_path",
            "promise": "power_steps",
        },
        0,
    )
    assert row is not None
    assert "book_self_note" not in row
    assert "social_space" not in row
    assert "engine_note" not in row
    assert row["start_kind"] == "granted_path"


def test_clear_and_load_opening_ponds_browse_is_soft(workspace: Path) -> None:
    from app.writing.opening_ponds import (
        clear_opening_ponds,
        format_opening_ponds_block,
        save_opening_ponds,
    )

    items = normalize_pond_items(
        [
            _pond("A窗", start_kind="self_notice", promise="power_steps"),
            _pond("B窗", start_kind="pulled_in", promise="costly_truth"),
        ]
    )
    save_opening_ponds(items, summary="x", workspace_root=workspace)
    browse = format_opening_ponds_block(workspace_root=workspace, mode="browse")
    assert "还没用过的 start_kind" not in browse
    assert "price_axis" not in browse
    assert "此前候选：《A窗》《B窗》" in browse
    assert "不要续写、修补或改名" in browse
    more = format_opening_ponds_block(workspace_root=workspace, mode="more")
    assert "## 此前候选" in more
    assert "《A窗》《B窗》" in more
    assert "离下面这几本远" not in more
    assert "社会角落" not in more
    assert "必须换第一口力" not in more
    assert "还没用过的" not in more
    assert clear_opening_ponds(workspace_root=workspace) is True
    assert format_opening_ponds_block(workspace_root=workspace) == ""


def test_seed_outline_from_pond_empty_wrap_and_prepend(
    workspace: Path, monkeypatch
) -> None:
    from app.writing.opening_ponds import seed_outline_from_pond

    seed_outline_from_pond({}, workspace_root=workspace)
    assert not (workspace / "outline.md").exists()

    seed_outline_from_pond(
        {
            "title": "《玉里有人》",
            "flavor": "旧货摊称来的玉里锁着半部功法。",
            "opening": "夜里枕头底下发烫。",
        },
        workspace_root=workspace,
    )
    first = (workspace / "outline.md").read_text(encoding="utf-8")
    assert first.count("《") == 1
    assert "《玉里有人》" in first
    assert "## 主线一句话" in first

    seed_outline_from_pond(
        {
            "title": "末班车",
            "opening": "老李把钥匙拍在他手里，转身去关调度室的灯。末班车停在最里面那个位。",
        },
        workspace_root=workspace,
    )
    no_flavor = (workspace / "outline.md").read_text(encoding="utf-8")
    assert "《末班车》" in no_flavor
    assert "简介：" in no_flavor
    assert "《末班车》。" not in no_flavor

    (workspace / "outline.md").write_text("## 主线一句话\n先往前走。\n", encoding="utf-8")
    seed_outline_from_pond(
        {
            "title": "废脉剑声",
            "flavor": "边荒剑冢夜里会响。",
        },
        workspace_root=workspace,
    )
    prepended = (workspace / "outline.md").read_text(encoding="utf-8")
    assert prepended.index("## 这本书") < prepended.index("## 主线一句话")
    assert "开篇：" not in prepended

    outline = workspace / "outline.md"
    outline.write_text("## 主线一句话\n先往前走。\n", encoding="utf-8")
    real_read = Path.read_text

    def _boom(self, *args, **kwargs):
        if self == outline:
            raise OSError("busy")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _boom)
    seed_outline_from_pond(
        {"title": "废脉剑声", "flavor": "边荒剑冢夜里会响。"},
        workspace_root=workspace,
    )
    assert "《废脉剑声》" in real_read(outline, encoding="utf-8")


def test_opening_ponds_fallback_and_bad_sidecar(workspace: Path, monkeypatch) -> None:
    from app.writing.opening_ponds import (
        _clip,
        committed_pond_title,
        format_opening_ponds_block,
        load_committed_pond,
        opening_choice_block,
    )

    monkeypatch.setattr(
        "app.writing.opening_ponds._OPENING_CHOICE_REL",
        workspace / "missing_opening_choice.md",
    )
    fallback = opening_choice_block()
    assert "Call `propose_book_candidates`" in fallback

    sidecar = workspace / ".agent" / "work" / "committed_pond.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text("{not json", encoding="utf-8")
    assert load_committed_pond(workspace_root=workspace) is None
    sidecar.write_text("[]\n", encoding="utf-8")
    assert load_committed_pond(workspace_root=workspace) is None
    sidecar.write_text('{"flavor": "only"}\n', encoding="utf-8")
    assert load_committed_pond(workspace_root=workspace) is None

    assert committed_pond_title("  ") is None
    assert _clip("abcdefghij", 4).endswith("…")
    assert format_opening_ponds_block(workspace_root=workspace, mode="nope") == ""


def test_save_committed_pond_copies_card_into_outline(workspace: Path) -> None:
    from app.writing.opening_ponds import save_committed_pond
    from app.writing.outline_arc import (
        STYLE_CONTRACT_OUTLINE_TEMPLATE,
        outline_style_committed,
    )

    assert outline_style_committed(STYLE_CONTRACT_OUTLINE_TEMPLATE) is False
    (workspace / "outline.md").write_text(
        STYLE_CONTRACT_OUTLINE_TEMPLATE, encoding="utf-8"
    )
    item = normalize_pond_items(
        [
            _pond(
                "废脉剑声",
                start_kind="granted_path",
                promise="power_steps",
                flavor="边荒一个被废了灵根的少年，村里剑冢夜里会响。",
                opening="剑冢夜里第三声响的时候，门栓断了。",
            )
        ]
    )[0]
    save_committed_pond(item, workspace_root=workspace)
    text = (workspace / "outline.md").read_text(encoding="utf-8")
    assert "《废脉剑声》" in text
    assert "剑冢夜里会响" in text
    assert "简介：剑冢夜里第三声响" in text
    assert "**跟着谁**" not in text
    assert outline_style_committed(text) is True


def test_committed_pond_block_omits_axis_labels(workspace: Path) -> None:
    from app.writing.cards import prepare_writing_system_prompt
    from app.writing.opening_ponds import (
        format_committed_pond_block,
        format_select_pond_message,
        save_opening_ponds,
    )

    items = normalize_pond_items(
        [
            {
                **_pond(
                    "《这条街的人都很会过日子》",
                    who="许棠，二十九岁",
                    where="南平码头附近的老街",
                    want="把裁缝铺撑住",
                    start_kind="no_extraordinary",
                    promise="survive_relation",
                    opening="一早改校服裤脚，下午去领弟弟。",
                    flavor="这条街的人都很会过日子",
                ),
                "book_self_note": "裁缝铺里把日子过下去",
            },
            _pond("B窗", start_kind="pulled_in", promise="costly_truth"),
        ]
    )
    save_opening_ponds(items, summary="x", workspace_root=workspace)
    msg = format_select_pond_message(items[0])
    block = format_committed_pond_block(message=msg, workspace_root=workspace)
    assert "## 已选作品" in block
    assert "不是正文" in block
    assert "简介：一早改校服裤脚" in block
    assert "这本书：这条街的人都很会过日子" in block
    assert "这本书在玩什么" not in block
    assert "力的来源" not in block
    assert "棋盘位" not in block
    assert "站在哪" not in block
    assert "入口（不是这本书要解决的事）" not in block
    assert "超凡怎么开始" not in block
    assert "读者买什么" not in block
    assert "拿什么结账" not in block
    assert "先过日子，超凡往后放" not in block
    assert "在关系里活下去" not in block
    pin = prepare_writing_system_prompt(
        "You are a writing assistant.",
        msg,
        workspace_root=workspace,
    )
    assert "## 已选作品" in pin.volatile_block
    more = prepare_writing_system_prompt(
        "You are a writing assistant.",
        MORE_PONDS_MESSAGE,
        workspace_root=workspace,
    )
    assert "## 此前候选" in more.volatile_block
    assert "## 已选作品" not in more.volatile_block


def test_user_axis_intent_only_when_named() -> None:
    from app.writing.opening_ponds import format_user_axis_intent_block

    urban = format_user_axis_intent_block("写一篇都市修真小说，我看看")
    assert urban == ""
    named = format_user_axis_intent_block("写一篇都市修真，要一个金手指流的，我看看")
    assert "金手指" in named
    assert "用户点名" in named


def test_seed_identity_uses_opening_when_no_flavor(workspace: Path) -> None:
    from app.writing.story_state import load_story_state, seed_identity_from_pond

    seed_identity_from_pond(
        {
            "title": "夜行证失效",
            "opening": "夜行证就搁在他手边，灯管滋了一声。他没有抬头。",
            "promise": "power_steps",
        },
        workspace_root=workspace,
    )
    identity = load_story_state(workspace_root=workspace)["identity"]
    assert any("夜行证就搁在他手边" in row for row in identity["is"])
    assert "power_steps" not in identity["is"]


def test_pond_reject_allows_two_in_turn_repairs() -> None:
    from uuid import uuid4

    from app.writing.opening_ponds import clear_pond_rejects, note_pond_reject

    clear_pond_rejects()
    turn_id = uuid4()
    first = note_pond_reject(turn_id, ("excerpt_too_short", "写到 60 字以上。"))
    assert first is not None
    assert first.get("stop_retry") is False
    assert first.get("fresh_retry") is True
    assert first.get("error") == "ponds_fresh_retry"
    assert first.get("detail") == ""
    assert "occupation" not in str(first.get("summary") or "").lower()
    second = note_pond_reject(turn_id, ("excerpt_is_montage", "只写一个时刻。"))
    assert second is not None
    assert second.get("stop_retry") is False
    third = note_pond_reject(turn_id, ("ponds_same_book", "这两本是同一本书换了工位。"))
    assert third is not None
    assert third.get("stop_retry") is True
    clear_pond_rejects()


@pytest.mark.asyncio
async def test_propose_opening_ponds_saves_and_awaits(workspace: Path) -> None:
    from app.tools.core.writing_tools import propose_opening_ponds

    result = await propose_opening_ponds(
        [
            {
                "title": "末班车",
                "opening": (
                    "夜班司机把末班车钥匙拍进徒弟手里，转身去关灯。"
                    "这城的末班车不按时刻表收班：谁接过钥匙，谁就要把还活着的乘客送到一个不在地图上的站。"
                    "徒弟每多跑一班，车上就多一个他认识的活人。"
                    "他要决定是把车开回去，还是把这条夜路做成自己的饭碗。"
                ),
                "book_self_note": "换班面板把家里卷进去",
                "start_kind": "granted_path",
            },
            {
                "title": "十七号",
                "opening": (
                    "陈老师的名册上第十七号从来对不上人：点到那个名字，后排椅子会自己挪一寸。"
                    "她发现缺席的不是学生，是这座学校用来顶人数的空名额，而空名额会把活人从班上换走。"
                    "她要决定是把十七号从名册划掉，还是用自己的名字把那个位子填回去。"
                ),
            },
        ]
    )
    assert result["awaiting_choice"] is True
    assert result["status"] == "ok"
    assert len(result["items"]) == 2
    saved = load_opening_ponds(workspace_root=workspace)
    assert saved is not None
    assert saved["items"][0]["title"] == "末班车"
    assert saved["items"][0]["book_self_note"] == "换班面板把家里卷进去"
    assert "similarity" in saved
    assert "job_signals" in saved
    ledger = (workspace / ".agent" / "work" / "ledger.jsonl").read_text(encoding="utf-8")
    row = __import__("json").loads(ledger.splitlines()[0])
    assert row["kind"] == "pond"
    assert "vector" not in row
    assert row["self_note"] == "换班面板把家里卷进去"
    assert row["declared"]["start_kind"] == "granted_path"


@pytest.mark.asyncio
async def test_propose_keeps_duplicate_kinds_and_accepts_plain(workspace: Path) -> None:
    from app.tools.core.writing_tools import propose_opening_ponds

    result = await propose_opening_ponds(
        [
            _pond("夜班窗", start_kind="pulled_in", promise="dread_decode", who="保安"),
            _pond("食堂窗", start_kind="pulled_in", promise="costly_truth", who="实习生"),
        ]
    )
    assert result["status"] == "ok"
    kinds = [str(it.get("start_kind")) for it in result["items"]]
    assert kinds == ["pulled_in", "pulled_in"]

    gothic = await propose_opening_ponds(
        [
            _pond("系统亮了", start_kind="granted_path", promise="power_steps"),
            _pond(
                "失踪者",
                start_kind="no_extraordinary",
                promise="dread_decode",
                who="殡仪馆化妆师",
                where="冷藏库",
            ),
        ],
        turn_user_text="写一份都市修真小说，我看看",
    )
    assert gothic["status"] == "ok"
    assert len(gothic["items"]) == 2


@pytest.mark.asyncio
async def test_propose_opening_ponds_repairs_once_then_stops(workspace: Path) -> None:
    from uuid import uuid4

    from app.tools.core.writing_tools import propose_opening_ponds
    from app.writing.opening_ponds import clear_pond_rejects

    clear_pond_rejects()
    turn_id = uuid4()
    bad = [{"title": "only", "who": "a", "where": "b", "want": "c"}]
    first = await propose_opening_ponds(bad, turn_id=turn_id)
    assert first["status"] == "error"
    assert first["error"] == "ponds_fresh_retry"
    assert first.get("fresh_retry") is True
    assert first.get("stop_retry") is False
    assert first.get("detail") == ""
    second = await propose_opening_ponds(bad, turn_id=turn_id)
    assert second.get("stop_retry") is False
    assert second["error"] == "ponds_fresh_retry"
    third = await propose_opening_ponds(bad, turn_id=turn_id)
    assert third.get("stop_retry") is True
    clear_pond_rejects()


def test_drop_pond_attempt_strips_titles_and_injects_opaque_flag() -> None:
    from app.engine.state import assistant_tool_use, user_message
    from app.writing.opening_ponds import (
        drop_pond_tool_attempt,
        inject_pond_fresh_retry_block,
    )

    msgs = [
        user_message("写一篇长篇的都市修真小说"),
        assistant_tool_use(
            "c1",
            "propose_book_candidates",
            {"items": [{"title": "余火", "pitch": "修电动车"}]},
        ),
    ]
    assert drop_pond_tool_attempt(msgs, "c1") is True
    blob = json.dumps(msgs, ensure_ascii=False)
    assert "余火" not in blob
    assert "propose_book_candidates" not in blob
    vol = inject_pond_fresh_retry_block("## Work index\nempty")
    assert "重新形成一个新的候选" in vol
    assert "empty items" in vol
    assert "occupation" not in vol
    assert "ponds_occupation" not in vol
    assert "余火" not in vol


@pytest.mark.asyncio
async def test_propose_keeps_passing_card_and_fills_on_fresh_retry(
    workspace: Path,
) -> None:
    from uuid import uuid4

    from app.tools.core.writing_tools import propose_opening_ponds
    from app.writing.opening_ponds import clear_pond_rejects

    clear_pond_rejects()
    turn_id = uuid4()
    occupation = (
        "周记推拿店打烊后，林哥把客人背上那张符纸揭下来。"
        "灵气顺着掌心进来，这门手艺从此能把人的寿元往回推。"
        "他不敢跟伙计说，只把这件事按在自己手底下。"
        "明天店门还要开，他已经知道有人会再来求这一手。"
    )
    yu_huo = (
        "陈砚在巷口修电动车已经三年，晚上还要去给病着的父亲熬药。"
        "他不是来查案，只是要把这家人的日子撑过去。"
        "修真规矩掺进修车和讨债之后，他能接触的人和能走的路都变了，"
        "但他要做的事还是原来那件：把父亲的病和这条街的欠账摆平。"
    )
    serial = (
        "灾变之后，人类进入了一个新的时代。资源匮乏、军阀割据、势力林立，"
        "秦禹只想要活下去。但现实一步步把他推向了更大的舞台。"
        "他明天还得去领粮，也还得决定跟哪一路人站在一起。"
    )
    siwan = (
        "四万年前，人类发现了修真之路。四万年后，修真已经成为这个时代最重要的力量。"
        "李耀出生在大荒，靠捡破烂为生，却想成为最出色的炼器师。"
        "一个生活在修真时代底层的少年，就这样走上了自己的修真之路。"
    )
    first = await propose_opening_ponds(
        [
            {"title": "周记推拿", "opening": occupation},
            {"title": "余火", "opening": yu_huo},
        ],
        turn_id=turn_id,
    )
    assert first["status"] == "error"
    assert first["error"] == "ponds_fresh_retry"
    assert first.get("fresh_retry") is True
    assert "occupation" not in json.dumps(first, ensure_ascii=False)
    second = await propose_opening_ponds(
        [
            {"title": "第九特区", "opening": serial},
            {"title": "修真四万年", "opening": siwan},
        ],
        turn_id=turn_id,
    )
    assert second["status"] == "ok"
    titles = {str(it.get("title")) for it in second["items"]}
    assert "余火" in titles
    assert "周记推拿" not in titles
    clear_pond_rejects()


@pytest.mark.asyncio
async def test_gate_off_logs_only(workspace: Path, monkeypatch, caplog) -> None:
    import logging

    from app.settings import settings
    from app.tools.core.writing_tools import propose_opening_ponds

    monkeypatch.setattr(settings, "ponds_excerpt_gate", False)
    caplog.set_level(logging.INFO)
    result = await propose_opening_ponds(
        [
            {"title": "怪事", "opening": "某人在城里遇到一件奇怪的事。"},
            {"title": "异物", "opening": "另一个人捡到一样奇怪的东西。"},
        ]
    )
    assert result["status"] == "ok"
    assert result.get("awaiting_choice") is True


@pytest.mark.asyncio
async def test_propose_more_appends_rejected_and_allows_reused_axes(
    workspace: Path,
) -> None:
    from app.tools.core.writing_tools import propose_opening_ponds
    from app.writing.opening_ponds import save_opening_ponds
    from app.writing.pond_history import load_rejected_pond_groups

    save_opening_ponds(
        normalize_pond_items(
            [
                _pond("A窗", start_kind="self_notice", promise="power_steps"),
                _pond("B窗", start_kind="pulled_in", promise="costly_truth"),
            ]
        ),
        workspace_root=workspace,
    )
    result = await propose_opening_ponds(
        [
            _pond("电梯", start_kind="self_notice", promise="power_steps"),
            _pond("道观", start_kind="pulled_in", promise="costly_truth"),
        ],
        turn_user_text=MORE_PONDS_MESSAGE,
    )
    assert result["status"] == "ok"
    kinds = {str(it.get("start_kind")) for it in result["items"]}
    assert kinds == {"self_notice", "pulled_in"}
    groups = load_rejected_pond_groups(workspace_root=workspace)
    assert len(groups) == 1
    assert groups[0]["items"][0]["title"] == "A窗"
