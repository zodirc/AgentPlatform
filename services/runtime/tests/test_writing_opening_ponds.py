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


def test_opening_choice_block_requires_distinct_start_kind() -> None:
    block = opening_choice_block()
    assert "start_kind" in block
    assert "self_notice" in block
    assert "promise" in block
    assert "unifying summary" in block or "三条都市修真" in block
    assert "系统" in block
    assert "过日子" in block
    assert "opening" in block
    assert "flavor" in block
    assert "这本书" in block
    assert "source_trust" in block
    assert "first_conflict_at" in block
    assert "no chat bubble" in block
    assert "连载" in block
    assert "事故" in block
    assert "工种" in block
    assert "title_is_mood" in block
    assert "title_needs_stake" in block
    assert "title_is_season" in block
    assert "opening_no_accident" in block
    assert "账单 / 走向 / 气味" in block or "账单/走向/气味" in block
    assert "七张" in block or "三次拒签" in block
    assert "family_errand_collision" in block
    assert "paper_skin_collision" in block
    assert "job_who_over_quota" in block
    assert "countdown_errand_collision" in block
    assert "bureau_over_quota" in block
    assert "tax_engine_over_quota" in block
    assert "civic_fable_over_quota" in block
    assert "transit_over_quota" in block
    assert "title_is_gimmick" in block
    assert "title_is_workplace" in block
    assert "quirk_shop_over_quota" in block
    assert "grotesque_opening_over_quota" in block
    assert "opening_is_setpiece" in block
    assert "need_world_layer" not in block
    assert "need_price" not in block
    assert "first third" not in block.lower()
    assert "capability" not in block.lower()


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
        "按开篇候选「早高峰系统」写第一章。",
        outline="",
        tool_names=["propose_opening_ponds", "draft_section"],
    )
    assert not should_gate_opening_choice(
        "写一章长篇修真，我看看",
        outline="",
        tool_names=["draft_section"],
    )


def test_normalize_pond_items_requires_two() -> None:
    assert normalize_pond_items([{"title": "only"}]) == [
        {
            "id": "pond-1",
            "title": "only",
            "who": "",
            "where": "",
            "want": "",
            "chapter_job": "",
            "opening": "",
            "arc": "",
            "flavor": "",
            "price": "",
            "start_kind": "",
            "promise": "",
            "source_trust": "",
            "first_conflict_at": "",
            "summary": "",
        }
    ]


def test_normalize_start_kind_aliases() -> None:
    assert normalize_start_kind("自己发觉") == "self_notice"
    assert normalize_start_kind("开启系统") == "granted_path"
    assert normalize_start_kind("平淡开局") == "no_extraordinary"
    assert normalize_promise("变强台阶") == "power_steps"
    from app.writing.opening_ponds import (
        normalize_first_conflict_at,
        normalize_source_trust,
    )

    assert normalize_source_trust("来源不可信") == "dubious"
    assert normalize_source_trust("虚假") == "false"
    assert normalize_first_conflict_at("前300字") == "first_300"
    assert normalize_first_conflict_at("第一章之后") == "later"


def test_ponds_contrast_summary_is_book_pitch_not_genre_blurb(workspace: Path) -> None:
    from app.writing.opening_ponds import ponds_contrast_summary, save_opening_ponds

    items = normalize_pond_items(
        [
            _pond(
                "跑单换力气",
                start_kind="granted_path",
                promise="power_steps",
                flavor="城南跑单的人把奔波换成能用的力气",
            ),
            _pond(
                "先把这锅汤端稳",
                start_kind="no_extraordinary",
                promise="survive_relation",
                flavor="合租房里把日子过下去，超凡先别来",
            ),
        ]
    )
    line = ponds_contrast_summary(items)
    assert line == "跑单换力气 ｜ 先把这锅汤端稳"
    assert "系统/金手指落到身上" not in line
    assert "都市修真" not in line
    saved = save_opening_ponds(
        items, summary="三条不同的都市修真近池", workspace_root=workspace
    )
    assert saved["summary"] == line
    assert "都市修真" not in saved["summary"]


def test_ponds_reject_same_start_kind_despite_new_job() -> None:
    items = normalize_pond_items(
        [
            _pond("保安窗", start_kind="pulled_in", promise="dread_decode", who="保安"),
            _pond("实习生窗", start_kind="pulled_in", promise="power_steps", who="实习生"),
        ]
    )
    code, _summary = ponds_reject_reason(items) or ("", "")
    assert code == "start_kind_collision"


def test_ponds_reject_all_same_promise() -> None:
    items = normalize_pond_items(
        [
            _pond("A", start_kind="self_notice", promise="power_steps"),
            _pond("B", start_kind="pulled_in", promise="power_steps"),
        ]
    )
    code, _summary = ponds_reject_reason(items) or ("", "")
    assert code == "promise_collision"


def test_opening_ponds_edge_paths(workspace: Path) -> None:
    from app.writing.opening_ponds import (
        opening_ponds_path,
        pond_item_event_fields,
        ponds_reject_reason,
    )

    assert should_gate_opening_choice(
        "写一章长篇修真，我看看",
        outline=None,
        tool_names=["propose_opening_ponds"],
        workspace_root=workspace,
    )
    (workspace / "outline.md").write_text("draft only", encoding="utf-8")
    assert should_gate_opening_choice(
        "写一章长篇修真，我看看",
        outline=None,
        tool_names=["propose_opening_ponds"],
        workspace_root=workspace,
    )
    assert normalize_start_kind("self-notice") == "self_notice"
    assert normalize_pond_items("nope") == []
    assert len(normalize_pond_items([{"title": "x"}] * 5 + ["skip"])) == 4
    assert ponds_reject_reason([])[0] == "need_two_ponds"
    path = opening_ponds_path(workspace_root=workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")
    assert load_opening_ponds(workspace_root=workspace) is None
    path.write_text("[]\n", encoding="utf-8")
    assert load_opening_ponds(workspace_root=workspace) is None
    path.write_text('{"items": [{"title": "only"}]}\n', encoding="utf-8")
    assert load_opening_ponds(workspace_root=workspace) is None
    msg = format_select_pond_message(
        {
            "title": "A",
            "id": "p",
            "chapter_job": "写这场",
            "where": "这儿",
            "opening": "开篇跟着这个人把眼前这件事做完。",
            "arc": "往后仍扣着这笔要的东西往前走。",
            "flavor": "有人的日子。",
        }
    )
    assert msg == "采用此开篇「A」"
    assert "跟着谁" not in msg
    assert "开篇：" not in msg
    assert pond_item_event_fields({"title": "", "name": ""}, 0) is not None


def test_clear_and_load_opening_ponds(workspace: Path) -> None:
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
    block = format_opening_ponds_block(workspace_root=workspace)
    assert "自己发觉" in block
    assert "被卷进已在运转的事" in block
    assert "还没用过的 start_kind" in block
    assert "系统/金手指落到身上" in block
    assert "先过日子，超凡往后放" in block
    assert clear_opening_ponds(workspace_root=workspace) is True
    assert load_opening_ponds(workspace_root=workspace) is None
    assert format_opening_ponds_block(workspace_root=workspace) == ""
    assert clear_opening_ponds(workspace_root=workspace) is False


def test_committed_pond_block_from_sidecar(workspace: Path) -> None:
    from app.writing.cards import prepare_writing_system_prompt
    from app.writing.opening_ponds import (
        format_committed_pond_block,
        format_select_pond_message,
        save_opening_ponds,
    )

    items = normalize_pond_items(
        [
            _pond(
                "《这条街的人都很会过日子》",
                who="许棠，二十九岁",
                where="南平码头附近的老街",
                want="把裁缝铺撑住",
                start_kind="no_extraordinary",
                promise="survive_relation",
                opening="一早改校服裤脚，下午去领弟弟。",
                arc="缝门窗时发现黑色裂缝。",
                flavor="这条街的人都很会过日子",
            ),
            _pond("B", start_kind="pulled_in", promise="costly_truth"),
        ]
    )
    save_opening_ponds(items, summary="x", workspace_root=workspace)
    msg = format_select_pond_message(items[0])
    assert msg == "采用此开篇「《这条街的人都很会过日子》」"
    block = format_committed_pond_block(message=msg, workspace_root=workspace)
    assert "## 已选开篇" in block
    assert "开篇：一早改校服裤脚" in block
    assert "这本书：这条街的人都很会过日子" in block
    assert "账单：" not in block
    assert "走向：" not in block
    assert "力的来源：来源不可信" in block
    assert "棋盘位：许棠" in block
    assert "不要另起账单" in block
    assert "先过日子，超凡往后放" in block
    assert "在关系里活下去" in block
    pin = prepare_writing_system_prompt(
        "You are a writing assistant.",
        msg,
        workspace_root=workspace,
    )
    assert "## 已选开篇" in pin.volatile_block
    assert "## 上一组开篇候选" not in pin.volatile_block
    more = prepare_writing_system_prompt(
        "You are a writing assistant.",
        MORE_PONDS_MESSAGE,
        workspace_root=workspace,
    )
    assert "## 上一组开篇候选" in more.volatile_block
    assert "## 已选开篇" not in more.volatile_block
    assert format_committed_pond_block(
        message="采用此开篇「没有这份」",
        workspace_root=workspace,
    ) == ""


def test_pond_item_event_fields_drops_unknown_kind() -> None:
    from app.writing.opening_ponds import pond_item_event_fields

    row = pond_item_event_fields(
        {
            "title": "a",
            "start_kind": "not-a-kind",
            "promise": "power_steps",
            "who": "w",
        },
        0,
    )
    assert row is not None
    assert "start_kind" not in row
    assert row["promise"] == "power_steps"


def test_ponds_accept_orthogonal_set() -> None:
    items = normalize_pond_items(
        [
            _pond("A", start_kind="self_notice", promise="power_steps"),
            _pond("B", start_kind="pulled_in", promise="costly_truth"),
        ]
    )
    assert ponds_reject_reason(items) is None


def test_plain_pond_cannot_be_urban_mystery() -> None:
    items = normalize_pond_items(
        [
            _pond("系统亮了", start_kind="granted_path", promise="power_steps"),
            _pond(
                "这座城没有真正的失踪者",
                start_kind="no_extraordinary",
                promise="dread_decode",
                who="殡仪馆化妆师",
                where="冷藏库",
            ),
        ]
    )
    code, _ = ponds_reject_reason(items) or ("", "")
    assert code == "plain_not_plain"


def test_fantasy_menu_wants_normal_opening_and_real_gift() -> None:
    gothic_gift = normalize_pond_items(
        [
            _pond("替人收下一场雷", start_kind="granted_path", promise="power_steps"),
            _pond("先把这班上完", start_kind="no_extraordinary", promise="survive_relation"),
        ]
    )
    code, _ = ponds_reject_reason(gothic_gift, message="写一章都市修真") or ("", "")
    assert code == "gift_not_gift"

    only_early = normalize_pond_items(
        [
            _pond("自己修", start_kind="self_notice", promise="power_steps"),
            _pond("被卷", start_kind="pulled_in", promise="costly_truth"),
        ]
    )
    assert ponds_reject_reason(only_early, message="玄幻") is None

    no_early = normalize_pond_items(
        [
            _pond("被卷", start_kind="pulled_in", promise="costly_truth"),
            _pond(
                "修行者排队办证",
                start_kind="world_already",
                promise="social_place",
                where="灵气坊市窗口",
            ),
        ]
    )
    code, _ = ponds_reject_reason(no_early, message="玄幻") or ("", "")
    assert code == "need_normal_opening"

    ok = normalize_pond_items(
        [
            _pond(
                "系统亮了",
                start_kind="granted_path",
                promise="power_steps",
                want="把系统任务做完",
            ),
            _pond(
                "先把这班上完",
                start_kind="no_extraordinary",
                promise="survive_relation",
                want="赶上早班地铁",
            ),
        ]
    )
    assert ponds_reject_reason(ok, message="都市修真") is None


def test_ponds_reject_missing_or_axis_book_plan() -> None:
    empty = normalize_pond_items(
        [
            {
                **_pond("A", start_kind="granted_path", promise="power_steps"),
                "opening": "",
                "arc": "",
                "flavor": "",
            },
            {
                **_pond("B", start_kind="no_extraordinary", promise="survive_relation"),
                "opening": "",
                "arc": "",
                "flavor": "",
            },
        ]
    )
    code, _ = ponds_reject_reason(empty) or ("", "")
    assert code == "need_book_plan"

    axis = normalize_pond_items(
        [
            _pond(
                "A",
                start_kind="granted_path",
                promise="power_steps",
                flavor="变强台阶",
            ),
            _pond(
                "B",
                start_kind="no_extraordinary",
                promise="survive_relation",
                flavor="在关系里活下去",
            ),
        ]
    )
    code, _ = ponds_reject_reason(axis) or ("", "")
    assert code == "plan_is_axis"

    no_arc = normalize_pond_items(
        [
            {
                **_pond("A", start_kind="granted_path", promise="power_steps"),
                "arc": "",
            },
            {
                **_pond("B", start_kind="no_extraordinary", promise="survive_relation"),
                "arc": "",
            },
        ]
    )
    assert ponds_reject_reason(no_arc) is None


def test_fantasy_three_card_menu_rejects_notice_pulled_world() -> None:
    gothic = normalize_pond_items(
        [
            _pond("电梯十三层", start_kind="self_notice", promise="dread_decode"),
            _pond("封锁道观", start_kind="pulled_in", promise="costly_truth"),
            _pond(
                "修行者也要排队办证",
                start_kind="world_already",
                promise="social_place",
                where="灵气坊市窗口",
            ),
        ]
    )
    code, _ = ponds_reject_reason(gothic, message="写一篇都市修真小说") or ("", "")
    assert code == "dread_not_cultivation"

    no_dread = normalize_pond_items(
        [
            _pond("电梯井里听见功法", start_kind="self_notice", promise="power_steps"),
            _pond("替人送进道观", start_kind="pulled_in", promise="costly_truth"),
            _pond(
                "修行者排队办证",
                start_kind="world_already",
                promise="social_place",
                where="灵气坊市窗口",
            ),
        ]
    )
    assert ponds_reject_reason(no_dread, message="都市修真") is None


def test_fantasy_rejects_dread_decode_unless_occult() -> None:
    items = normalize_pond_items(
        [
            _pond("系统亮了", start_kind="granted_path", promise="dread_decode"),
            _pond("先把这班上完", start_kind="no_extraordinary", promise="survive_relation"),
        ]
    )
    code, _ = ponds_reject_reason(items, message="都市修真") or ("", "")
    assert code == "dread_not_cultivation"
    assert ponds_reject_reason(items, message="写一篇修真，走克系") is None


def test_more_ponds_rejects_reused_start_kinds() -> None:
    items = normalize_pond_items(
        [
            _pond("A", start_kind="self_notice", promise="power_steps"),
            _pond("B", start_kind="pulled_in", promise="costly_truth"),
            _pond(
                "C",
                start_kind="world_already",
                promise="social_place",
                where="灵气坊市",
            ),
        ]
    )
    code, summary = ponds_reject_reason(
        items,
        message=MORE_PONDS_MESSAGE,
        previous_kinds={"self_notice", "pulled_in", "world_already"},
    ) or ("", "")
    assert code == "kinds_repeat"
    assert "granted_path" in summary or "系统" in summary


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
                "chapter_job": "当场进场",
                "start_kind": "granted_path",
                "promise": "power_steps",
                "opening": "早高峰闸机前，保安周石的班被一张看不懂的面板打断。",
                "arc": "他先靠这面板把班撑住，后面才发现换班的代价会落到家里。",
                "flavor": "白天写字楼里把班上完，面板给出的路已经不像加班那么简单。",
                "price": "换班一次扣一夜睡眠",
                "source_trust": "dubious",
                "first_conflict_at": "first_300",
            },
            {
                "title": "窗口人情",
                "who": "林浅",
                "where": "食堂",
                "want": "把这顿账还上",
                "start_kind": "no_extraordinary",
                "promise": "survive_relation",
                "opening": "食堂窗口林浅先把这顿账还上，没人谈功法，先把窗口的人稳住。",
                "arc": "人情债越积越沉，超凡是后面才挤进来的。",
                "flavor": "窗口里把日子过下去，超凡先别来，先把这顿人稳住。",
                "price": "窗口人情少一顿",
                "source_trust": "trusted",
                "first_conflict_at": "chapter_one",
            },
        ],
        summary="两份近池",
    )
    assert result["awaiting_choice"] is True
    assert result["status"] == "ok"
    assert len(result["items"]) == 2
    assert "当场得到能用的路" not in (result.get("summary") or "")
    assert "早高峰系统" in (result.get("summary") or "")
    assert "窗口人情" in (result.get("summary") or "")
    assert "系统/金手指落到身上" not in (result.get("summary") or "")
    saved = load_opening_ponds(workspace_root=workspace)
    assert saved is not None
    assert saved["items"][0]["title"] == "早高峰系统"
    assert saved["items"][0]["start_kind"] == "granted_path"
    msg = format_select_pond_message(saved["items"][0])
    assert msg == "采用此开篇「早高峰系统」"
    assert wants_opening_candidates(msg) is False


@pytest.mark.asyncio
async def test_propose_opening_ponds_rejects_reskin(workspace: Path) -> None:
    from app.tools.core.writing_tools import propose_opening_ponds
    result = await propose_opening_ponds(
        [
            _pond("夜班窗", start_kind="pulled_in", promise="dread_decode", who="保安"),
            _pond("食堂窗", start_kind="pulled_in", promise="costly_truth", who="实习生"),
        ]
    )
    assert result["status"] == "error"
    assert result["error"] == "start_kind_collision"


@pytest.mark.asyncio
async def test_propose_opening_ponds_rejects_missing_kind(workspace: Path) -> None:
    from app.tools.core.writing_tools import propose_opening_ponds
    result = await propose_opening_ponds(
        [
            {"title": "a", "who": "a", "where": "b", "want": "c"},
            {"title": "b", "who": "d", "where": "e", "want": "f"},
        ]
    )
    assert result["status"] == "error"
    assert result["error"] == "need_start_kind_and_promise"


@pytest.mark.asyncio
async def test_propose_opening_ponds_rejects_same_promise(workspace: Path) -> None:
    from app.tools.core.writing_tools import propose_opening_ponds
    result = await propose_opening_ponds(
        [
            _pond("A", start_kind="self_notice", promise="power_steps"),
            _pond("B", start_kind="pulled_in", promise="power_steps"),
        ]
    )
    assert result["status"] == "error"
    assert result["error"] == "promise_collision"


@pytest.mark.asyncio
async def test_propose_opening_ponds_rejects_one(workspace: Path) -> None:
    from app.tools.core.writing_tools import propose_opening_ponds
    result = await propose_opening_ponds([{"title": "only", "who": "a", "where": "b", "want": "c"}])
    assert result["status"] == "error"
    assert result["error"] == "need_two_ponds"


@pytest.mark.asyncio
async def test_propose_opening_ponds_rejects_previous_kinds(
    workspace: Path,
) -> None:
    from app.tools.core.writing_tools import propose_opening_ponds
    from app.writing.opening_ponds import save_opening_ponds

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
    assert result["status"] == "error"
    assert result["error"] == "kinds_repeat"


def test_ponds_allow_missing_or_duplicate_price() -> None:
    missing = normalize_pond_items(
        [
            {**_pond("A", start_kind="self_notice", promise="power_steps"), "price": ""},
            _pond("B", start_kind="pulled_in", promise="costly_truth"),
        ]
    )
    assert ponds_reject_reason(missing) is None

    same = normalize_pond_items(
        [
            _pond("A", start_kind="self_notice", promise="power_steps", price="少一夜睡眠"),
            _pond("B", start_kind="pulled_in", promise="costly_truth", price="少一夜睡眠"),
        ]
    )
    assert ponds_reject_reason(same) is None


def test_ponds_reject_all_trusted_sources() -> None:
    all_clean = normalize_pond_items(
        [
            _pond(
                "A",
                start_kind="self_notice",
                promise="power_steps",
                source_trust="trusted",
            ),
            _pond(
                "B",
                start_kind="pulled_in",
                promise="costly_truth",
                source_trust="trusted",
            ),
            _pond(
                "C",
                start_kind="granted_path",
                promise="social_place",
                where="系统弹窗",
                source_trust="trusted",
            ),
        ]
    )
    code, _ = ponds_reject_reason(all_clean) or ("", "")
    assert code == "trust_all_clean"
    mixed = normalize_pond_items(
        [
            _pond(
                "A",
                start_kind="self_notice",
                promise="power_steps",
                source_trust="trusted",
            ),
            _pond(
                "B",
                start_kind="pulled_in",
                promise="costly_truth",
                source_trust="trusted",
            ),
            _pond(
                "C",
                start_kind="granted_path",
                promise="social_place",
                where="系统弹窗",
                source_trust="dubious",
            ),
        ]
    )
    assert ponds_reject_reason(mixed) is None


def test_ponds_reject_later_conflict_over_quota() -> None:
    two_later = normalize_pond_items(
        [
            _pond(
                "A",
                start_kind="self_notice",
                promise="power_steps",
                first_conflict_at="later",
            ),
            _pond(
                "B",
                start_kind="pulled_in",
                promise="costly_truth",
                first_conflict_at="later",
            ),
        ]
    )
    code, _ = ponds_reject_reason(two_later) or ("", "")
    assert code == "later_over_quota"
    one_later = normalize_pond_items(
        [
            _pond(
                "A",
                start_kind="self_notice",
                promise="power_steps",
                first_conflict_at="later",
            ),
            _pond(
                "B",
                start_kind="pulled_in",
                promise="costly_truth",
                first_conflict_at="first_300",
            ),
        ]
    )
    assert ponds_reject_reason(one_later) is None


def test_ponds_reject_missing_source_trust_and_conflict() -> None:
    no_trust = normalize_pond_items(
        [
            {
                **_pond("A", start_kind="self_notice", promise="power_steps"),
                "source_trust": "",
            },
            _pond("B", start_kind="pulled_in", promise="costly_truth"),
        ]
    )
    code, _ = ponds_reject_reason(no_trust) or ("", "")
    assert code == "need_source_trust"
    no_conflict = normalize_pond_items(
        [
            {
                **_pond("A", start_kind="self_notice", promise="power_steps"),
                "first_conflict_at": "",
            },
            _pond("B", start_kind="pulled_in", promise="costly_truth"),
        ]
    )
    code, _ = ponds_reject_reason(no_conflict) or ("", "")
    assert code == "need_first_conflict_at"


def test_plain_over_quota_and_optional_plain() -> None:
    two_plain = [
        _pond("先过一天", start_kind="no_extraordinary", promise="survive_relation"),
        _pond("再过一天", start_kind="no_extraordinary", promise="social_place"),
        _pond(
            "系统亮了",
            start_kind="granted_path",
            promise="power_steps",
            want="把系统任务做完",
        ),
    ]
    items = normalize_pond_items(two_plain)
    # uniqueness would also catch this; quota is named so 过日子超员可读。
    items[0]["start_kind"] = "no_extraordinary"
    items[1]["start_kind"] = "no_extraordinary"
    code, _ = ponds_reject_reason(items, message="都市修真") or ("", "")
    assert code == "plain_over_quota"
    one_plain = normalize_pond_items(
        [
            _pond(
                "系统亮了",
                start_kind="granted_path",
                promise="power_steps",
                want="把系统任务做完",
            ),
            _pond("被卷", start_kind="pulled_in", promise="costly_truth"),
            _pond(
                "先把这班上完",
                start_kind="no_extraordinary",
                promise="survive_relation",
                want="赶上早班地铁",
            ),
        ]
    )
    assert ponds_reject_reason(one_plain, message="都市修真") is None


def test_ponds_reject_mood_title_stake_and_job_opening() -> None:
    mood = normalize_pond_items(
        [
            _pond(
                "雨水从旧楼顶下来",
                start_kind="self_notice",
                promise="power_steps",
            ),
            _pond(
                "系统亮了",
                start_kind="granted_path",
                promise="costly_truth",
            ),
        ]
    )
    code, _ = ponds_reject_reason(mood, message="都市修真") or ("", "")
    assert code == "title_is_mood"

    no_stake = normalize_pond_items(
        [
            _pond(
                "邻里调解委员会的春天",
                start_kind="self_notice",
                promise="power_steps",
            ),
            _pond(
                "系统亮了",
                start_kind="granted_path",
                promise="costly_truth",
            ),
        ]
    )
    code, _ = ponds_reject_reason(no_stake, message="都市修真") or ("", "")
    assert code == "title_needs_stake"

    job_bio = normalize_pond_items(
        [
            _pond(
                "楼下快递柜里有一座山",
                start_kind="self_notice",
                promise="power_steps",
                opening="周野调解两户老人争一间储物室时，发现双方吵的每一句话都被墙里的灰尘记住了。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
            ),
        ]
    )
    code, _ = ponds_reject_reason(job_bio, message="都市修真") or ("", "")
    assert code == "opening_no_accident"

    ok = normalize_pond_items(
        [
            _pond(
                "楼下快递柜里有一座山",
                start_kind="self_notice",
                promise="power_steps",
                opening="柜门是我自己开的，取件码是别人的，格里没有包裹。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    assert ponds_reject_reason(ok, message="都市修真") is None
    assert ponds_reject_reason(mood) is None


def test_ponds_reject_family_errand_and_paper_skin() -> None:
    family = normalize_pond_items(
        [
            _pond(
                "楼下快递柜里有一座山",
                start_kind="self_notice",
                promise="power_steps",
                want="天亮前找回丢失的一车药，保住母亲的手术押金",
                opening="柜门是我自己开的，取件码是别人的，格里没有包裹。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
                want="赶在凌晨前凑齐续命药尾款，不让父亲被转出病房",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(family, message="都市修真") or ("", "")
    assert code == "family_errand_collision"

    paper = normalize_pond_items(
        [
            _pond(
                "阳寿收据",
                start_kind="self_notice",
                promise="power_steps",
                want="查清这座港用谁的寿命结账",
                flavor="一具会开票的尸体给出不可信的账",
                opening="柜门是我自己开的，取件码是别人的，格里没有包裹。",
            ),
            _pond(
                "拒签灵契",
                start_kind="granted_path",
                promise="costly_truth",
                want="把假师父的功法当场用出去",
                flavor="一份灵契能替人拒绝命运",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(paper, message="都市修真") or ("", "")
    assert code == "paper_skin_collision"

    mixed = normalize_pond_items(
        [
            _pond(
                "阳寿收据",
                start_kind="self_notice",
                promise="power_steps",
                want="天亮前找回丢失的一车药，保住母亲的手术押金",
                flavor="一具会开票的尸体给出不可信的账",
                opening="柜门是我自己开的，取件码是别人的，格里没有包裹。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
                want="把假师父的功法当场用出去",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    assert ponds_reject_reason(mixed, message="都市修真") is None

    season = normalize_pond_items(
        [
            _pond(
                "七张阳寿收据",
                start_kind="self_notice",
                promise="power_steps",
                want="查清这座港用谁的寿命结账",
                opening="柜门是我自己开的，取件码是别人的，格里没有包裹。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
                want="把假师父的功法当场用出去",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(season, message="都市修真") or ("", "")
    assert code == "title_is_season"

    jobs = normalize_pond_items(
        [
            _pond(
                "楼下快递柜里有一座山",
                start_kind="self_notice",
                promise="power_steps",
                who="沈青禾，冷链调货的人",
                opening="柜门是我自己开的，取件码是别人的，格里没有包裹。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
                who="唐遇，医院陪护",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(jobs, message="都市修真") or ("", "")
    assert code == "job_who_over_quota"

    one_job = normalize_pond_items(
        [
            _pond(
                "楼下快递柜里有一座山",
                start_kind="self_notice",
                promise="power_steps",
                who="沈青禾，冷链调货的人",
                opening="柜门是我自己开的，取件码是别人的，格里没有包裹。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
                who="林浅，夜巡干员",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    assert ponds_reject_reason(one_job, message="都市修真") is None

    from app.writing.opening_ponds import rank_opening_ponds

    ranked = rank_opening_ponds(
        normalize_pond_items(
            [
                _pond(
                    "窗口人情",
                    start_kind="no_extraordinary",
                    promise="survive_relation",
                    who="准备搬家的上班族",
                    arc="人情债越积越沉，超凡是后面才挤进来的。",
                ),
                _pond(
                    "请勿高考时渡劫",
                    start_kind="granted_path",
                    promise="power_steps",
                    who="考生林浅",
                    arc="高考场上的渡劫会打开隐世职阶，星门那一层会露头。",
                    opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
                ),
            ]
        )
    )
    assert ranked[0]["title"] == "请勿高考时渡劫"

    closed = normalize_pond_items(
        [
            _pond(
                "楼下快递柜里有一座山",
                start_kind="self_notice",
                promise="power_steps",
                want="查清这座港用谁的寿命结账",
                opening="柜门是我自己开的，取件码是别人的，格里没有包裹。",
                arc="救回母亲并掀掉本市航线，他在当不当持票人之间做选择。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
                want="把假师父的功法当场用出去",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    assert ponds_reject_reason(closed, message="都市修真") is None

    taxes = normalize_pond_items(
        [
            _pond(
                "命盘之外",
                start_kind="self_notice",
                promise="power_steps",
                flavor="拍卖行的目录每一页都像证据；他每坐稳一次命席，就会永久忘掉一个熟人的脸。",
                opening="压轴拍品裂开的一刻，拍卖场里两百多人同时叫出了他从未用过的名字。",
            ),
            _pond(
                "醒在第二重天",
                start_kind="granted_path",
                promise="costly_truth",
                flavor="官方灵网说他只是术式失控；每次借影施术，他都会永久失去一段童年记忆。",
                opening="失控的灵车撞破高架护栏时，他的影子先一步抬起了整辆车。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(taxes, message="都市修真") or ("", "")
    assert code == "tax_engine_over_quota"

    fables = normalize_pond_items(
        [
            _pond(
                "凡人也要修行",
                start_kind="self_notice",
                promise="power_steps",
                flavor="地铁用阵法供能，他却是这座城的根，印记完成认主后普通人身份会被清除。",
                opening="地铁撞上看不见的灵脉时，整座城市的路灯在同一秒熄灭，街心升起第二轮太阳。",
            ),
            _pond(
                "天命维修中",
                start_kind="granted_path",
                promise="costly_truth",
                flavor="他接入正在崩坏的天命维护程序，命运故障被推到面前，系统要修掉他。",
                opening="电梯撞上地下三层时，手机亮起天命维护程序已绑定。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(fables, message="都市修真") or ("", "")
    assert code == "civic_fable_over_quota"

    transits = normalize_pond_items(
        [
            _pond(
                "楼下快递柜里有一座山",
                start_kind="self_notice",
                promise="power_steps",
                opening="地铁进站的一瞬间，柜门自己开了，格里没有包裹。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
                opening="电梯门刚合上，面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(transits, message="都市修真") or ("", "")
    assert code == "transit_over_quota"

    clocks = normalize_pond_items(
        [
            _pond(
                "楼下快递柜里有一座山",
                start_kind="self_notice",
                promise="power_steps",
                want="赶在零点前把一张作废的准考证换回来",
                opening="柜门是我自己开的，取件码是别人的，格里没有包裹。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
                want="在封站前把遗落的钥匙送到失主手里",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(clocks, message="都市修真") or ("", "")
    assert code == "countdown_errand_collision"

    bureaus = normalize_pond_items(
        [
            _pond(
                "天门考籍",
                start_kind="self_notice",
                promise="power_steps",
                who="外院考生",
                where="市民服务中心的补证窗口",
                want="决定要不要让考籍系统烙上手背",
                opening="准考证在窗口玻璃后自己翻开，纸上的名字化作一道考籍系统，直接烙进他的手背。",
                arc="他以补录考生的身份进入藏在城市教育体系里的外院，隐世那一层会打开。",
            ),
            _pond(
                "人间巡天司",
                start_kind="pulled_in",
                promise="costly_truth",
                who="见习巡天吏",
                where="晚高峰封闭的地铁换乘层",
                want="截不截这颗正在渡劫的头",
                opening="末班车冲进站台时，车门里先滚出了一颗正在渡劫的头。",
                arc="他从见习巡天吏升入夜巡，进入潮汐秘境，对上不受城市管辖的古老巡天道统。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(bureaus, message="都市修真") or ("", "")
    assert code == "bureau_over_quota"

    one_bureau = normalize_pond_items(
        [
            _pond(
                "天门考籍",
                start_kind="self_notice",
                promise="power_steps",
                who="外院考生",
                where="市民服务中心的补证窗口",
                want="决定要不要让考籍系统烙上手背",
                opening="准考证在窗口玻璃后自己翻开，纸上的名字化作一道考籍系统，直接烙进他的手背。",
                arc="他以补录考生的身份进入藏在城市教育体系里的外院，隐世那一层会打开。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
                who="林浅，夜巡干员",
                want="把假师父的功法当场用出去",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    assert ponds_reject_reason(one_bureau, message="都市修真") is None

    user_gimmicks = normalize_pond_items(
        [
            _pond(
                "借我一段人生",
                start_kind="self_notice",
                promise="power_steps",
                flavor="周既白在旧书市场替人鉴书，能从碰过的物件里借来主人最熟练的一段人生。",
                opening="旧表在周既白掌心倒转，表盘里钻出一根沾血的手指；下一刻，他记起了陌生男人杀人的全部手法。",
            ),
            _pond(
                "我在药铺见过神仙",
                start_kind="pulled_in",
                promise="costly_truth",
                flavor="林照看守祖父留下的一间中药铺，地下丹炉开始认他为主。",
                opening="药柜最深处砰地倒下，一个浑身是血的男人从后面滚出来，睁眼就叫林照把地下的炉火关掉。",
            ),
            _pond(
                "修仙从替班开始",
                start_kind="granted_path",
                promise="survive_relation",
                flavor="许南枝只是夜班便利店的店员，发现修士修的是藏在打工里的人间功。",
                opening="关东煮锅骤然炸裂，青火从西装客嘴里喷上天花板，整间便利店的灯同时熄了。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(user_gimmicks, message="都市修真") or ("", "")
    assert code == "quirk_shop_over_quota"

    gimmick = normalize_pond_items(
        [
            _pond(
                "我在夜市见过神仙",
                start_kind="self_notice",
                promise="power_steps",
                opening="柜门是我自己开的，取件码是别人的，格里没有包裹。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(gimmick, message="都市修真") or ("", "")
    assert code == "title_is_gimmick"

    shops = normalize_pond_items(
        [
            _pond(
                "借我一段人生",
                start_kind="self_notice",
                promise="power_steps",
                flavor="周既白在旧书市场替人鉴书，能从碰过的物件里借来一段人生。",
                opening="柜门是我自己开的，取件码是别人的，格里没有包裹。",
            ),
            _pond(
                "丹火认主",
                start_kind="pulled_in",
                promise="costly_truth",
                flavor="林照看守一间中药铺，地下丹炉开始认他为主。",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(shops, message="都市修真") or ("", "")
    assert code == "quirk_shop_over_quota"

    grotesques = normalize_pond_items(
        [
            _pond(
                "楼下快递柜里有一座山",
                start_kind="self_notice",
                promise="power_steps",
                opening="旧表在掌心倒转，表盘里钻出一根沾血的手指。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
                opening="一个浑身是血的男人从柜后滚出来，当场把任务拍在他脸上。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(grotesques, message="都市修真") or ("", "")
    assert code == "grotesque_opening_over_quota"

    one_shop = normalize_pond_items(
        [
            _pond(
                "借我一段人生",
                start_kind="self_notice",
                promise="power_steps",
                flavor="周既白在旧书市场替人鉴书，能从碰过的物件里借来一段人生。",
                opening="柜门是我自己开的，取件码是别人的，格里没有包裹。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
                flavor="面板落下的异能能当场复制对面的招式。",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    assert ponds_reject_reason(one_shop, message="都市修真") is None

    docks = normalize_pond_items(
        [
            _pond(
                "猎杀修士的第七码头",
                start_kind="world_already",
                promise="power_steps",
                flavor="港城的觉醒者混在航运公司里，陈策能把打在自己身上的术法截留十分钟再还回去。",
                opening="集装箱从吊臂上脱钩，砸穿卸货区的铁棚时，一名浑身是血的女修把一枚染血的宗门信物按进陈策掌心。",
            ),
            _pond(
                "一人万法",
                start_kind="granted_path",
                promise="costly_truth",
                flavor="陆沉被一套只认当场选择的传法系统绑定，替人担事便能得到那一脉的真法。",
                opening="桥栏在陆沉掌下轰然断裂，男人再次朝江面坠去；他抓住手腕的瞬间，脑海里浮出血字：承其因，得其法。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(docks, message="都市修真") or ("", "")
    assert code == "title_is_workplace"

    wanfa = normalize_pond_items(
        [
            _pond(
                "一人万法",
                start_kind="granted_path",
                promise="costly_truth",
                flavor="陆沉被一套只认当场选择的传法系统绑定，替人担事便能得到那一脉的真法。",
                opening="桥栏在陆沉掌下轰然断裂，男人再次朝江面坠去；他抓住手腕的瞬间，脑海里浮出血字：承其因，得其法。",
            ),
            _pond(
                "早高峰系统",
                start_kind="self_notice",
                promise="power_steps",
                flavor="面板落下的异能能当场复制对面的招式。",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    assert ponds_reject_reason(wanfa, message="都市修真") is None

    setpiece = normalize_pond_items(
        [
            _pond(
                "楼下快递柜里有一座山",
                start_kind="self_notice",
                promise="power_steps",
                opening="集装箱从吊臂上脱钩，砸穿卸货区的铁棚，格里没有包裹。",
            ),
            _pond(
                "早高峰系统",
                start_kind="granted_path",
                promise="costly_truth",
                opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
            ),
        ]
    )
    code, _ = ponds_reject_reason(setpiece, message="都市修真") or ("", "")
    assert code == "opening_is_setpiece"

    from app.writing.opening_ponds import rank_opening_ponds

    ranked_straight = rank_opening_ponds(
        normalize_pond_items(
            [
                _pond(
                    "修仙从替班开始",
                    start_kind="granted_path",
                    promise="survive_relation",
                    flavor="许南枝只是夜班便利店的店员。",
                    opening="关东煮锅骤然炸裂，青火从西装客嘴里喷上天花板。",
                ),
                _pond(
                    "请勿高考时渡劫",
                    start_kind="self_notice",
                    promise="power_steps",
                    who="考生林浅",
                    flavor="高考场上的渡劫会打开隐世职阶，异能当场落在人身上。",
                    opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
                ),
            ]
        )
    )
    assert ranked_straight[0]["title"] == "请勿高考时渡劫"

    ranked_hit = rank_opening_ponds(
        normalize_pond_items(
            [
                _pond(
                    "猎杀修士的第七码头",
                    start_kind="world_already",
                    promise="power_steps",
                    flavor="陈策能把打在自己身上的术法截留十分钟再还回去。",
                    opening="集装箱从吊臂上脱钩，砸穿卸货区的铁棚。",
                ),
                _pond(
                    "一人万法",
                    start_kind="granted_path",
                    promise="costly_truth",
                    flavor="传法系统只认当场选择，异能当场落在人身上。",
                    opening="闸机面板亮了，班被一张看不懂的任务当场打断。",
                ),
            ]
        )
    )
    assert ranked_hit[0]["title"] == "一人万法"


def test_pond_item_event_fields_keeps_price_and_trust() -> None:
    from app.writing.opening_ponds import pond_item_event_fields

    row = pond_item_event_fields(
        {
            "title": "早高峰系统",
            "start_kind": "granted_path",
            "promise": "power_steps",
            "price": "换班一次扣一夜睡眠",
            "source_trust": "dubious",
            "first_conflict_at": "first_300",
            "who": "周石",
        },
        0,
    )
    assert row is not None
    assert row["price"] == "换班一次扣一夜睡眠"
    assert row["source_trust"] == "dubious"
    assert row["first_conflict_at"] == "first_300"
    bad = pond_item_event_fields(
        {
            "title": "a",
            "source_trust": "not-a-trust",
            "first_conflict_at": "nope",
            "promise": "power_steps",
        },
        0,
    )
    assert bad is not None
    assert "source_trust" not in bad
    assert "first_conflict_at" not in bad
