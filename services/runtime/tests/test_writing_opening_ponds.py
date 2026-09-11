from __future__ import annotations

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


def _pond(
    title: str,
    *,
    start_kind: str,
    promise: str,
    who: str = "甲",
    where: str = "这里",
    want: str = "眼下这件事",
    opening: str = "当场少了一口。开篇跟着这个人把眼前这件事做完，场面里有人有日子。",
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
        "opening": opening,
        "arc": arc,
        "flavor": flavor or f"这本书跟着这个人，规则已经在场上转，不把「{title}」写成口号。",
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


def test_opening_choice_block_is_book_first() -> None:
    block = opening_choice_block()
    assert "## Opening choice (platform)" in block
    assert "书名 / 这本书 / 开篇" in block
    assert "哪一个角落" not in block
    assert "什么机制" not in block
    assert "怎么推进" not in block
    assert "用户" in block and ("题材" in block or "点名" in block)
    assert "必须换第一口力" not in block
    assert "在玩什么" not in block
    assert "开篇怎么进" not in block
    assert "Write title / flavor / opening first" in block
    assert "book_self_note" in block
    assert "unifying summary" in block
    assert "in-turn repair" in block
    assert "连载" in block
    assert "今晚" not in block
    assert "封面" in block
    assert "九龙拉棺" in block
    assert "场上" in block
    assert "觉醒" in block
    assert "灵气" in block
    assert "末班车" not in block
    assert "出候选不要用" not in block
    assert "不是发现这座城" not in block
    assert "secret ledger" not in block
    assert "规则怪谈" not in block
    assert "Leave the assistant message empty" in block
    assert "pulled_in is a normal" not in block
    assert "At least one book should put" not in block
    assert "do not reuse previous price_axis" not in block.lower()
    assert "world_already =" not in block
    assert "granted_path =" not in block
    assert "房租" not in block
    assert "殡仪" not in block
    for banned in (
        "need_start_kind_and_promise",
        "kinds_repeat",
        "gift_not_gift",
        "paper_skin_collision",
        "bureau_over_quota",
    ):
        assert banned not in block
    assert 800 <= len(block) <= 2800


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
    assert "得到了什么" in locked_blob


def test_should_gate_opening_choice_when_browsing() -> None:
    assert should_gate_opening_choice(
        "写一章长篇修真小说的第一章, 现代都市题材，我看看",
        outline="",
        tool_names=["propose_opening_ponds", "draft_section"],
    )
    assert not should_gate_opening_choice(
        "采用此开篇「早高峰系统」",
        outline="",
        tool_names=["propose_opening_ponds", "draft_section"],
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
            _pond("A", start_kind="self_notice", promise="power_steps"),
            _pond("B", start_kind="pulled_in", promise="power_steps"),
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
            {**_pond("A", start_kind="self_notice", promise="power_steps"), "price_axis": "", "start_kind": "", "promise": ""},
            _pond("B", start_kind="pulled_in", promise="costly_truth"),
        ]
    )
    assert ponds_reject_reason(missing_axis) is None

    reused = ponds_reject_reason(
        normalize_pond_items(
            [
                _pond("A", start_kind="self_notice", promise="power_steps"),
                _pond("B", start_kind="pulled_in", promise="costly_truth"),
            ]
        ),
        message=MORE_PONDS_MESSAGE,
    )
    assert reused is None

    gothic = normalize_pond_items(
        [
            _pond("替人收下一场雷", start_kind="granted_path", promise="power_steps"),
            _pond(
                "这座城没有真正的失踪者",
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
            _pond("A", start_kind="self_notice", promise="power_steps", source_trust="trusted"),
            _pond("B", start_kind="pulled_in", promise="costly_truth", source_trust="trusted"),
            _pond("C", start_kind="granted_path", promise="social_place", source_trust="trusted"),
        ]
    )
    assert ponds_reject_reason(all_clean) is None


def test_kept_reject_codes() -> None:
    assert ponds_reject_reason([])[0] == "need_two_ponds"
    empty = normalize_pond_items(
        [
            {**_pond("A", start_kind="granted_path", promise="power_steps"), "opening": "", "flavor": ""},
            {**_pond("B", start_kind="no_extraordinary", promise="survive_relation"), "opening": "", "flavor": ""},
        ]
    )
    assert (ponds_reject_reason(empty) or ("", ""))[0] == "need_book_plan"
    axis = normalize_pond_items(
        [
            _pond("A", start_kind="granted_path", promise="power_steps", flavor="变强台阶"),
            _pond("B", start_kind="no_extraordinary", promise="survive_relation", flavor="在关系里活下去"),
        ]
    )
    assert (ponds_reject_reason(axis) or ("", ""))[0] == "plan_is_axis"
    note = normalize_pond_items(
        [
            {
                **_pond("A", start_kind="granted_path", promise="power_steps"),
                "book_self_note": "系统/金手指落到身上",
            },
            _pond("B", start_kind="no_extraordinary", promise="survive_relation"),
        ]
    )
    assert (ponds_reject_reason(note) or ("", ""))[0] == "plan_is_axis"
    two_later = normalize_pond_items(
        [
            _pond("A", start_kind="self_notice", promise="power_steps", first_conflict_at="later"),
            _pond("B", start_kind="pulled_in", promise="costly_truth", first_conflict_at="later"),
        ]
    )
    assert (ponds_reject_reason(two_later) or ("", ""))[0] == "later_over_quota"


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
            _pond("A", start_kind="self_notice", promise="power_steps"),
            _pond("B", start_kind="pulled_in", promise="costly_truth"),
        ]
    )
    save_opening_ponds(items, summary="x", workspace_root=workspace)
    browse = format_opening_ponds_block(workspace_root=workspace, mode="browse")
    assert "还没用过的 start_kind" not in browse
    assert "price_axis" not in browse
    assert "上次给过《A》《B》" in browse
    more = format_opening_ponds_block(workspace_root=workspace, mode="more")
    assert "## 上一组开篇候选（用户说这几本都不对）" in more
    assert "离下面这几本远" in more
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
    assert "Call `propose_opening_ponds`" in fallback

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
    assert "开篇：剑冢夜里第三声响" in text
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
            _pond("B", start_kind="pulled_in", promise="costly_truth"),
        ]
    )
    save_opening_ponds(items, summary="x", workspace_root=workspace)
    msg = format_select_pond_message(items[0])
    block = format_committed_pond_block(message=msg, workspace_root=workspace)
    assert "## 已选开篇" in block
    assert "开篇：一早改校服裤脚" in block
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
    assert "## 已选开篇" in pin.volatile_block
    more = prepare_writing_system_prompt(
        "You are a writing assistant.",
        MORE_PONDS_MESSAGE,
        workspace_root=workspace,
    )
    assert "## 上一组开篇候选" in more.volatile_block
    assert "## 已选开篇" not in more.volatile_block


def test_user_axis_intent_only_when_named() -> None:
    from app.writing.opening_ponds import format_user_axis_intent_block

    urban = format_user_axis_intent_block("写一篇都市修真小说，我看看")
    assert urban == ""
    named = format_user_axis_intent_block("写一篇都市修真，要一个金手指流的，我看看")
    assert "金手指" in named
    assert "用户点名" in named


def test_seed_identity_uses_self_note(workspace: Path) -> None:
    from app.writing.story_state import load_story_state, seed_identity_from_pond

    seed_identity_from_pond(
        {
            "title": "夜行证失效",
            "flavor": "跑腿、死人留下的证、三分钟确认",
            "promise": "power_steps",
            "book_self_note": "凡人靶身份漏洞在编制城里活下去",
        },
        workspace_root=workspace,
    )
    identity = load_story_state(workspace_root=workspace)["identity"]
    assert "凡人靶身份漏洞在编制城里活下去" in identity["is"]
    assert "power_steps" not in identity["is"]


def test_pond_reject_allows_one_in_turn_repair() -> None:
    from uuid import uuid4

    from app.writing.opening_ponds import clear_pond_rejects, note_pond_reject

    clear_pond_rejects()
    turn_id = uuid4()
    first = note_pond_reject(turn_id, ("need_book_plan", "每份都要有这本书和开篇。"))
    assert first is not None
    assert first.get("stop_retry") is False
    second = note_pond_reject(turn_id, ("ponds_same_book", "这两本是同一本书换了工位。"))
    assert second is not None
    assert second.get("stop_retry") is True
    clear_pond_rejects()


@pytest.mark.asyncio
async def test_propose_opening_ponds_saves_and_awaits(workspace: Path) -> None:
    from app.tools.core.writing_tools import propose_opening_ponds

    result = await propose_opening_ponds(
        [
            {
                "title": "早高峰系统",
                "who": "保安周石",
                "where": "大堂闸机",
                "want": "系统换班",
                "start_kind": "granted_path",
                "promise": "power_steps",
                "opening": "早高峰闸机前，保安周石的班被一张看不懂的面板打断。",
                "flavor": "白天写字楼里把班上完，面板给出的路已经不像加班那么简单。",
                "book_self_note": "换班面板把家里卷进去",
                "source_trust": "dubious",
                "first_conflict_at": "first_300",
                "price_axis": "memory",
            },
            {
                "title": "窗口人情",
                "who": "林浅",
                "where": "食堂",
                "want": "把这顿账还上",
                "start_kind": "no_extraordinary",
                "promise": "survive_relation",
                "opening": "食堂窗口林浅先把这顿账还上，没人谈功法，先把窗口的人稳住。",
                "flavor": "窗口里把日子过下去，超凡先别来，先把这顿人稳住。",
                "source_trust": "trusted",
                "first_conflict_at": "chapter_one",
                "price_axis": "none",
            },
        ]
    )
    assert result["awaiting_choice"] is True
    assert result["status"] == "ok"
    assert len(result["items"]) == 2
    saved = load_opening_ponds(workspace_root=workspace)
    assert saved is not None
    assert saved["items"][0]["title"] == "早高峰系统"
    assert saved["items"][0]["book_self_note"] == "换班面板把家里卷进去"
    assert "similarity" in saved
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
                "这座城没有真正的失踪者",
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
    assert first["error"] == "need_two_ponds"
    assert first.get("stop_retry") is False
    second = await propose_opening_ponds(bad, turn_id=turn_id)
    assert second.get("stop_retry") is True
    clear_pond_rejects()


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
                _pond("A", start_kind="self_notice", promise="power_steps"),
                _pond("B", start_kind="pulled_in", promise="costly_truth"),
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
    assert groups[0]["items"][0]["title"] == "A"
