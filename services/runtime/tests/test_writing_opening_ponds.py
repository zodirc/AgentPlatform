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
    opening: str = "开篇跟着这个人把眼前这件事做完，场面里有人有日子。",
    arc: str = "往后仍扣着这笔要的东西往前走，中段加压，不另开百科。",
    flavor: str = "",
) -> dict[str, str]:
    return {
        "title": title,
        "who": who,
        "where": where,
        "want": want,
        "opening": opening,
        "arc": arc,
        "flavor": flavor or f"跟「{title}」这条日子把事做完。",
        "start_kind": start_kind,
        "promise": promise,
    }


def test_wants_opening_candidates_browse_and_commit() -> None:
    assert wants_opening_candidates("写一章长篇修真，我看看") is True
    assert wants_opening_candidates(MORE_PONDS_MESSAGE) is True
    assert (
        wants_opening_candidates("按开篇候选「早高峰系统」写第一章。") is False
    )


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
    assert "first third" not in block.lower()
    assert "capability" not in block.lower()


def test_should_gate_opening_choice_when_browsing() -> None:
    assert should_gate_opening_choice(
        "写一章长篇修真小说的第一章, 现代都市题材，我看看",
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
            "start_kind": "",
            "promise": "",
            "summary": "",
        }
    ]


def test_normalize_start_kind_aliases() -> None:
    assert normalize_start_kind("自己发觉") == "self_notice"
    assert normalize_start_kind("开启系统") == "granted_path"
    assert normalize_start_kind("平淡开局") == "no_extraordinary"
    assert normalize_promise("变强台阶") == "power_steps"


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
    assert "跑单换力气·城南跑单的人把奔波换成能用的力气" in line
    assert "先把这锅汤端稳·合租房里把日子过下去，超凡先别来" in line
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
    assert "开篇：开篇跟着这个人把眼前这件事做完。" in msg
    assert "走向：往后仍扣着这笔要的东西往前走。" in msg
    assert "风格：有人的日子。" in msg
    assert "这一章干什么" not in msg
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
    code, _ = ponds_reject_reason(only_early, message="玄幻") or ("", "")
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
            _pond("电梯井里听见气", start_kind="self_notice", promise="power_steps"),
            _pond("替人送进道观", start_kind="pulled_in", promise="costly_truth"),
            _pond(
                "修行者排队办证",
                start_kind="world_already",
                promise="social_place",
                where="灵气坊市窗口",
            ),
        ]
    )
    code, _ = ponds_reject_reason(no_dread, message="都市修真") or ("", "")
    assert code == "need_gift_or_plain"


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
                "flavor": "白天写字楼里把班上完的升级日常",
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
                "flavor": "窗口里把日子过下去",
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
    assert "按开篇候选「早高峰系统」" in msg
    assert "风格：白天写字楼里把班上完的升级日常" in msg
    assert "开篇：早高峰闸机前" in msg
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
