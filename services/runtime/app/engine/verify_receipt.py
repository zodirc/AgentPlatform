"""Turn 终态 verify receipt 注入逻辑（Wave 4 W9，veto 13）。

English: Verify receipt injection before turn finalization (Wave 4 W9, veto 13).

在 Turn 即将结束（final edge）时，根据 TurnState 中仅由工具结果维护的追踪器，
决定是否向对话注入一条「交卷前须补验证/修稿」的用户 receipt。分两大类触发：

**经典 coding verify**：代码编辑成功后，自最后一次编辑起未运行任何 testish 命令。
**Issue repro verify**：仓库自带测试已绿，但 problem.md 描述的行为尚未在
*最新代码编辑之后* 成功验收。

约束：不阻塞 cancel/failed；每类 receipt 每 Turn 至多一次；剩余步数不足 K 时不注入。
写作场景另有 staccato/hinge/opening/lore 四类 L0 receipt，与 coding verify 共享注入管线。
"""

from __future__ import annotations

from typing import Any

from app.structural.issue_repro import (
    extract_issue_repro_hints,
    is_clearing_repro_result,
    is_green_test_result,
    load_problem_text,
    obligations_met_for_command,
)
from app.structural.related_tests import related_test_paths
from app.structural.test_summary import is_testish_command
from app.writing.patch_budget import MAX_PATCHES_PER_PENALTY_KEY

# 预留步数：保证 receipt 注入后仍有步数跑测试/修稿再交卷。
DEFAULT_VERIFY_RECEIPT_RESERVE_STEPS = 10
_RELATED_CAP = 5


_WRITING_L0 = ("staccato_uniform", "hinge_dense", "lore_dump", "opening_institution")
_WRITING_PENDING = {
    "staccato_uniform": "staccato_pending",
    "hinge_dense": "hinge_pending",
    "lore_dump": "lore_pending",
    "opening_institution": "opening_pending",
}


def _writing_l0_hits(result: dict[str, Any]) -> dict[str, bool] | None:
    """从写作评分/草稿结果提取最新 L0 命中标志。

    参数:
        result: draft_section / evaluate_writing_fragment 等工具返回 dict。

    返回:
        四类 L0 键 → 是否命中的 dict；非写作评分结果时返回 None。
    """
    signals = result.get("writing_signals")
    has_signals = isinstance(signals, dict) and bool(signals)
    has_top = any(key in result for key in _WRITING_L0) or str(result.get("status") or "") == "drafted"
    if not has_signals and not has_top:
        return None
    hits = {key: False for key in _WRITING_L0}
    if has_signals:
        for item in signals.get("penalties") or []:
            if isinstance(item, dict) and item.get("hit"):
                key = str(item.get("key") or "")
                if key in hits:
                    hits[key] = True
    for key in _WRITING_L0:
        if result.get(key):
            hits[key] = True
    return hits


def note_writing_signals_for_verify(state: Any, result: dict[str, Any]) -> None:
    """根据最近一次 scored 章节更新写作 L0 pending 标志（非 draft 时刻）。

    Receipt 跟随最后评分章节，而非 draft 时的瞬时 flag。

    参数:
        state: ``TurnState`` 或兼容对象（原地 setattr）。
        result: 含 writing_signals 或顶层 L0 键的工具结果。
    """
    hits = _writing_l0_hits(result)
    if hits is None:
        return
    for key, attr in _WRITING_PENDING.items():
        setattr(state, attr, bool(hits.get(key)))


def note_tool_result_for_verify(
    state: Any,
    *,
    tool_name: str,
    result: dict[str, Any],
    arguments: dict[str, Any] | None = None,
) -> None:
    """根据单次工具完成结果更新 TurnState 上的 verify / issue-repro 追踪器。

    参数:
        state: ``TurnState``（原地修改 verify_* / issue_repro_* / writing pending）。
        tool_name: 工具名。
        result: 工具返回 dict；非 dict 时忽略。
        arguments: 可选；run_tests/run_command 取 command 的兜底来源。
    """
    if not isinstance(result, dict):
        return
    name = str(tool_name or "")
    if name in {"draft_section", "propose_patch", "apply_patch", "evaluate_writing_fragment"}:
        note_writing_signals_for_verify(state, result)
        return
    if name == "edit_file" and result.get("status") == "edited":
        impact = result.get("impact") if isinstance(result.get("impact"), dict) else {}
        checks = result.get("checks") if isinstance(result.get("checks"), dict) else {}
        # Non-code paths skip impact/checks — do not arm verify.
        if impact.get("reason") == "non_code_path" or (
            checks.get("status") == "skipped" and impact.get("status") == "skipped"
        ):
            return
        state.code_edits_since_verify = int(getattr(state, "code_edits_since_verify", 0) or 0) + 1
        state.verify_pending = True
        related = result.get("related_tests")
        if isinstance(related, list) and related:
            _merge_related(state, related)
        _ensure_issue_repro_hints(state)
        # Pre-edit issue repro no longer counts.
        state.issue_repro_satisfied = False
        state.issue_repro_edits_since = int(getattr(state, "issue_repro_edits_since", 0) or 0) + 1
        return

    if name == "run_tests":
        if result.get("status") == "rejected" or result.get("error") == "test_command_not_allowed":
            return
        state.verify_pending = False
        cmd = str(result.get("command") or (arguments or {}).get("command") or "").strip()
        _note_issue_repro_from_command(state, cmd, result)
        if cmd and result.get("status") not in {"passed", "executed"}:
            state.last_repro_command = cmd[:500]
        _note_first_failure(state, result)
        return

    if name == "run_command":
        cmd = str(result.get("command") or (arguments or {}).get("command") or "").strip()
        # Issue repro is often ``python -c`` (not testish) — still count it.
        if cmd:
            _note_issue_repro_from_command(state, cmd, result, allow_non_testish=True)
        if not is_testish_command(cmd):
            return
        state.verify_pending = False
        if result.get("status") not in {"executed", "passed"} or int(result.get("exit_code") or 1) != 0:
            state.last_repro_command = cmd[:500]
        _note_first_failure(state, result)
        _arm_issue_repro_if_needed(state, cmd, result)


def _ensure_issue_repro_hints(state: Any) -> None:
    """懒加载 problem.md 中的 issue 复现提示到 TurnState（每 Turn 至多一次）。"""
    if bool(getattr(state, "issue_repro_loaded", False)):
        return
    state.issue_repro_loaded = True
    try:
        from app.tools.core.paths import _workspace_root

        text = load_problem_text(_workspace_root())
    except Exception:
        text = ""
    hints = extract_issue_repro_hints(text)
    state.issue_repro_commands = list(hints.get("commands") or [])[:5]
    state.issue_repro_markers = list(hints.get("markers") or [])[:8]
    state.issue_repro_required_tokens = list(hints.get("required_tokens") or [])[:6]
    state.issue_repro_assets = list(hints.get("assets") or [])[:2]
    state.issue_repro_casefold_assets = list(hints.get("casefold_assets") or [])[:2]
    state.issue_repro_fail_signals = list(hints.get("fail_signals") or [])[:6]
    state.issue_repro_expect_signals = list(hints.get("expect_signals") or [])[:6]
    state.issue_repro_need_roundtrip = bool(hints.get("need_roundtrip"))
    state.issue_repro_need_casefold = bool(hints.get("need_casefold"))
    state.issue_repro_roundtrip_formats = list(hints.get("roundtrip_formats") or [])[:4]
    state.issue_repro_roundtrip_kwargs = list(hints.get("roundtrip_kwargs") or [])[:4]


def _issue_repro_hints_dict(state: Any) -> dict[str, Any]:
    """将 TurnState 上 issue repro 字段打包为 structural 模块消费的 dict。"""
    return {
        "commands": list(getattr(state, "issue_repro_commands", None) or []),
        "markers": list(getattr(state, "issue_repro_markers", None) or []),
        "required_tokens": list(getattr(state, "issue_repro_required_tokens", None) or []),
        "assets": list(getattr(state, "issue_repro_assets", None) or []),
        "casefold_assets": list(getattr(state, "issue_repro_casefold_assets", None) or []),
        "fail_signals": list(getattr(state, "issue_repro_fail_signals", None) or []),
        "expect_signals": list(getattr(state, "issue_repro_expect_signals", None) or []),
        "need_roundtrip": bool(getattr(state, "issue_repro_need_roundtrip", False)),
        "need_casefold": bool(getattr(state, "issue_repro_need_casefold", False)),
        "roundtrip_formats": list(getattr(state, "issue_repro_roundtrip_formats", None) or []),
        "roundtrip_kwargs": list(getattr(state, "issue_repro_roundtrip_kwargs", None) or []),
    }


def _issue_repro_hints_present(state: Any) -> bool:
    """TurnState 是否已解析出至少一条可用的 issue repro 义务。"""
    return bool(
        list(getattr(state, "issue_repro_commands", None) or [])
        or list(getattr(state, "issue_repro_markers", None) or [])
        or list(getattr(state, "issue_repro_required_tokens", None) or [])
        or list(getattr(state, "issue_repro_assets", None) or [])
        or list(getattr(state, "issue_repro_fail_signals", None) or [])
        or bool(getattr(state, "issue_repro_need_roundtrip", False))
        or bool(getattr(state, "issue_repro_need_casefold", False))
    )


def _command_matches_state_issue_repro(state: Any, cmd: str) -> bool:
    """命令是否满足 problem.md 解析出的 issue repro 义务模式。"""
    return obligations_met_for_command(cmd, _issue_repro_hints_dict(state))


def _note_issue_repro_from_command(
    state: Any,
    cmd: str,
    result: dict[str, Any],
    *,
    allow_non_testish: bool = False,
) -> None:
    """根据单次命令执行结果更新 issue repro satisfied / armed 状态。

    参数:
        state: ``TurnState``。
        cmd: 实际执行的命令字符串。
        result: run_tests / run_command 返回 dict。
        allow_non_testish: True 时允许 ``python -c`` 等非 testish 命令参与 issue repro。
    """
    if not _issue_repro_hints_present(state):
        _ensure_issue_repro_hints(state)
    if not _issue_repro_hints_present(state):
        return
    if _command_matches_state_issue_repro(state, cmd):
        if is_clearing_repro_result(
            result,
            fail_signals=list(getattr(state, "issue_repro_fail_signals", None) or []),
            expect_signals=list(getattr(state, "issue_repro_expect_signals", None) or []),
        ):
            state.issue_repro_satisfied = True
            state.issue_repro_armed = False
            state.issue_repro_edits_since = 0
        # Matching but failed / still emitting issue failure → do not satisfy.
        return
    if not allow_non_testish or is_testish_command(cmd):
        _arm_issue_repro_if_needed(state, cmd, result)


def _arm_issue_repro_if_needed(state: Any, cmd: str, result: dict[str, Any]) -> None:
    """仓库测试全绿但未跑 issue repro 时，置 ``issue_repro_armed`` 以待终态 receipt。

    已 satisfied 且编辑计数为 0、或已发过 receipt、或无 hints、或当前 cmd 已是
    issue repro 义务命令时，不重复 arm。
    """
    if bool(getattr(state, "issue_repro_satisfied", False)) and int(
        getattr(state, "issue_repro_edits_since", 0) or 0
    ) == 0:
        return
    if bool(getattr(state, "issue_repro_receipt_sent", False)):
        return
    if not _issue_repro_hints_present(state):
        return
    if _command_matches_state_issue_repro(state, cmd):
        return
    if not is_green_test_result(result):
        return
    # Green repo tests without a successful post-edit issue repro → arm gate.
    state.issue_repro_armed = True


def _note_first_failure(state: Any, result: dict[str, Any]) -> None:
    """从测试结果提取首条失败摘要写入 ``last_test_first_failure``（供 receipt 引用）。"""
    from app.structural.test_summary import format_failure_feed

    feed = result.get("failure_feed")
    if isinstance(feed, str) and feed.strip():
        state.last_test_first_failure = feed.strip()[:400]
        return
    summary = result.get("test_summary")
    formatted = format_failure_feed(summary if isinstance(summary, dict) else None)
    if formatted:
        state.last_test_first_failure = formatted[:400]


def _remaining_steps(state: Any) -> int:
    """本 Turn 剩余可执行 Engine 步数（max_steps - step_count）。"""
    return int(getattr(state, "max_steps", 0) or 0) - int(
        getattr(state, "step_count", 0) or 0
    )


def should_inject_verify_receipt(
    state: Any,
    *,
    reserve_steps: int = DEFAULT_VERIFY_RECEIPT_RESERVE_STEPS,
) -> bool:
    """判断是否应在 Turn 终态注入 verify / 写作 receipt。

    参数:
        state: ``TurnState``。
        reserve_steps: 经典/issue repro 触发所需最少剩余步数；写作类用更紧的 hinge_reserve。

    返回:
        True 表示应注入；cancel/budget 耗尽或步数不足时 False。
    """
    if bool(getattr(state, "cancelled", False)):
        return False
    if bool(getattr(state, "budget_exceeded", False)):
        return False

    remaining = _remaining_steps(state)
    coding_ok = remaining >= max(1, int(reserve_steps))

    if (
        coding_ok
        and bool(getattr(state, "verify_pending", False))
        and int(getattr(state, "code_edits_since_verify", 0) or 0) >= 1
        and not bool(getattr(state, "verify_receipt_sent", False))
    ):
        return True

    satisfied = bool(getattr(state, "issue_repro_satisfied", False)) and int(
        getattr(state, "issue_repro_edits_since", 0) or 0
    ) == 0
    if (
        coding_ok
        and bool(getattr(state, "issue_repro_armed", False))
        and not satisfied
        and not bool(getattr(state, "issue_repro_receipt_sent", False))
        and _issue_repro_hints_present(state)
    ):
        return True

    hinge_reserve = min(max(1, int(reserve_steps)), 3)
    if remaining < hinge_reserve:
        return False
    writing_used = (
        bool(getattr(state, "hinge_receipt_sent", False))
        or bool(getattr(state, "lore_receipt_sent", False))
        or bool(getattr(state, "opening_receipt_sent", False))
        or bool(getattr(state, "staccato_receipt_sent", False))
    )
    if writing_used:
        return False
    if bool(getattr(state, "staccato_pending", False)):
        return True
    if bool(getattr(state, "hinge_pending", False)):
        return True
    if bool(getattr(state, "opening_pending", False)):
        return True
    if bool(getattr(state, "lore_pending", False)):
        return True
    return False


def verify_receipt_kind(state: Any) -> str:
    """决定本次注入使用的 receipt 种类键。

    参数:
        state: ``TurnState``。

    返回:
        ``issue_repro`` | ``classic`` | ``staccato`` | ``hinge`` | ``opening`` | ``lore``。
        issue_repro 优先于 classic；写作类在 classic 不 pending 时按 staccato→hinge→opening→lore。
    """
    satisfied = bool(getattr(state, "issue_repro_satisfied", False)) and int(
        getattr(state, "issue_repro_edits_since", 0) or 0
    ) == 0
    if (
        bool(getattr(state, "issue_repro_armed", False))
        and not satisfied
        and not bool(getattr(state, "issue_repro_receipt_sent", False))
        and not (
            bool(getattr(state, "verify_pending", False))
            and not bool(getattr(state, "verify_receipt_sent", False))
        )
    ):
        return "issue_repro"
    if (
        bool(getattr(state, "verify_pending", False))
        and not bool(getattr(state, "verify_receipt_sent", False))
    ):
        return "classic"
    if bool(getattr(state, "staccato_pending", False)) and not bool(
        getattr(state, "staccato_receipt_sent", False)
    ):
        return "staccato"
    if bool(getattr(state, "hinge_pending", False)) and not bool(
        getattr(state, "hinge_receipt_sent", False)
    ):
        return "hinge"
    if bool(getattr(state, "opening_pending", False)) and not bool(
        getattr(state, "opening_receipt_sent", False)
    ):
        return "opening"
    if bool(getattr(state, "lore_pending", False)) and not bool(
        getattr(state, "lore_receipt_sent", False)
    ):
        return "lore"
    return "classic"


def mark_verify_receipt_injected(state: Any) -> str:
    """注入 receipt 后清除对应 pending 并置 sent 标志（每类至多一次）。

    参数:
        state: ``TurnState``（原地修改）。

    返回:
        实际标记的 receipt 种类（同 ``verify_receipt_kind``）。
    """
    kind = verify_receipt_kind(state)
    if kind == "issue_repro":
        state.issue_repro_receipt_sent = True
        state.issue_repro_armed = False
    elif kind == "staccato":
        state.staccato_receipt_sent = True
        state.staccato_pending = False
        state.hinge_pending = False
        state.lore_pending = False
        state.opening_pending = False
    elif kind == "hinge":
        state.hinge_receipt_sent = True
        state.hinge_pending = False
        state.lore_pending = False
        state.opening_pending = False
        state.staccato_pending = False
    elif kind == "opening":
        state.opening_receipt_sent = True
        state.opening_pending = False
        state.lore_pending = False
        state.hinge_pending = False
        state.staccato_pending = False
    elif kind == "lore":
        state.lore_receipt_sent = True
        state.lore_pending = False
        state.opening_pending = False
        state.hinge_pending = False
        state.staccato_pending = False
    else:
        state.verify_receipt_sent = True
    return kind


def build_verify_receipt_text(state: Any) -> str:
    """按当前 kind 组装注入用户的完整 receipt 正文。

    参数:
        state: ``TurnState``。

    返回:
        多行中文/技术混合说明字符串。
    """
    kind = verify_receipt_kind(state)
    if kind == "issue_repro":
        return _build_issue_repro_receipt_text(state)
    if kind == "staccato":
        return _build_staccato_receipt_text()
    if kind == "hinge":
        return _build_hinge_receipt_text()
    if kind == "opening":
        return _build_opening_receipt_text()
    if kind == "lore":
        return _build_lore_receipt_text()
    return _build_classic_receipt_text(state)


def _build_staccato_receipt_text() -> str:
    """均匀短拍（三字问答/空应声）L0 修复指引正文。"""
    return (
        "这一段对白或句子长短几乎一样短，像机械一问一答"
        "（「进来拿。」「我会还。」「先记账。」「记多久？」这一路）；"
        "或把一句话拆成「…。」他说，「…。」；或把物件说成「A，就是B」；"
        "或用「钟不知道，屋子知道」这类对仗收束；"
        "或接上一句的词干再加「也/还」（「刀钝你也哭」「现在还要看」）；"
        "或用「几点 / 早点睡 / 到家发消息 / 知道」把场收掉；"
        "或嘴里总结「小时候也这样…未必做得到」；"
        "或问答末句用「是A，不是B」收束；"
        "或尽是「我知道」「嗯」「懂」这类没有新决定的应声。"
        "或已经叫过的名字再问「你有名字吗」「叫什么」。"
        "这是同一拍拆成的多轮空问，不是「太短」。"
        "收成一两句把决定或物件说完，或只动手；孤立短打不要扩。"
        "对白里因为/可是可以有。不要另起一套去AI模板。"
        f"用 propose_patch 只换 writing_signals.repair_span.old_text（同 key 本 Turn 至多 {MAX_PATCHES_PER_PENALTY_KEY} 次）；"
        "若 span 带 neighbor，跟那条拍里一句有内容的对白或一记动作，不要搬情节，"
        "也不要把「」拆成旁白。"
        "预算尽则 draft_section mode=rewrite_window 一次替换整窗："
        "一两句说完，或手、物、沉默、信息差接上。"
        "不要把对白改成「告诉他…」的说明。不要整章再 draft_section。"
    )


def _build_hinge_receipt_text() -> str:
    """hinge 拧法（看见+立马+却）L0 修复指引正文。"""
    return (
        "这一段在「看见/听到」之后用了立马/立刻，下一句又在拧（却/没想到/回头）。"
        "不要补转折，不要还上一章的账，不要另起一套去AI模板。"
        "改的是这一拍的拧法，不是把整场改成三字句。"
        "用 propose_patch 只换 writing_signals.repair_span.old_text："
        "看见之后可以停在物件、价钱、规矩或沉默上；若 span 带 neighbor，跟那条拍。"
        "前后句子长短仍可以对不齐。不要改成说明书。不要整章再 draft_section。"
    )


def _build_opening_receipt_text() -> str:
    """开篇机构专名（宗/派）L0 修复指引正文。"""
    return (
        "第一章入口写成了机构专名（宗/派/仙门），读者还不知道这是哪块地。"
        "不要补身世提要，不要另起一套去AI模板。"
        "用 propose_patch 只换开篇几句（writing_signals.repair_span.old_text）："
        "先写可站的场面，机构名让人物后口带出；若 span 带 neighbor，跟那条拍。"
        "不要整章再 draft_section。身世、失踪、全书谜面仍不要写进第一章。"
    )


def _build_lore_receipt_text() -> str:
    """开篇 lore dump（N年前+失踪/尸体）L0 修复指引正文。"""
    return (
        "这一段在点到人名之后，用「N年前」写成了失踪/尸体提要。"
        "不要补转折，不要把全书谜面写圆，不要另起一套去AI模板。"
        "用 propose_patch 只删这段提要（writing_signals.repair_span.old_text）："
        "留在当下的屋子、活计或麻烦上即可；若 span 带 neighbor，跟那条拍。"
        "不要整章再 draft_section。删提要时不要改成三字问答连环。"
    )


def _build_classic_receipt_text(state: Any) -> str:
    """经典 coding verify：未跑测试的编辑计数、related_tests、末次 repro/失败摘要。"""
    n = int(getattr(state, "code_edits_since_verify", 0) or 0)
    lines = [
        f"verify_receipt: 本 Turn 改动 {n} 个代码文件，最后一次编辑后未运行任何测试",
    ]
    related = list(getattr(state, "related_tests_union", None) or [])
    if related:
        lines.append("  related_tests:")
        for item in related[:_RELATED_CAP]:
            if isinstance(item, dict):
                path = str(item.get("path") or "")
                cmd = str(item.get("command") or "")
                if path and cmd:
                    lines.append(f"    - {path} | {cmd}")
                elif path:
                    lines.append(f"    - {path}")
            elif isinstance(item, str) and item.strip():
                lines.append(f"    - {item.strip()}")
    repro = str(getattr(state, "last_repro_command", "") or "").strip()
    if repro:
        lines.append(f"  repro: {repro}")
    fail = str(getattr(state, "last_test_first_failure", "") or "").strip()
    if fail:
        lines.append("  last_failure:")
        for fline in fail.splitlines():
            lines.append(f"    {fline}")
    lines.append(
        "  要求: 运行上述任一验证后再交卷；若有 last_failure 须针对该条修复并重跑同一测；"
        "确实无法运行则说明原因后交卷"
    )
    return "\n".join(lines)


def _build_issue_repro_receipt_text(state: Any) -> str:
    """Issue repro verify：problem.md 义务、样例资产、建议命令与 must_not_still_show。"""
    lines = [
        "verify_receipt: 仓库自带测试已绿，但编辑后尚未按问题描述完成行为验收",
        "  说明: 现有 test_*.py 全绿 / 编辑前复现 都不算；"
        "须在本轮代码编辑之后完成下列义务",
    ]
    if bool(getattr(state, "issue_repro_need_roundtrip", False)):
        fmts = list(getattr(state, "issue_repro_roundtrip_formats", None) or [])
        kws = list(getattr(state, "issue_repro_roundtrip_kwargs", None) or [])
        detail = []
        if fmts:
            detail.append(f"format={','.join(fmts[:3])}")
        if kws:
            detail.append(",".join(kws[:3]))
        lines.append(
            "  obligation_roundtrip: write → read 往返"
            + (f" ({'; '.join(detail)})" if detail else "")
            + "；只用 write 修掉 TypeError 不算"
        )
    if bool(getattr(state, "issue_repro_need_casefold", False)):
        lines.append(
            "  obligation_casefold: issue 主张大小写不敏感 — "
            "须对问题样例（或你已跑通的同格式内容）做非注释行 .lower() 后再读成功"
        )
    assets = list(getattr(state, "issue_repro_assets", None) or [])
    if assets:
        preview = assets[0] if len(assets[0]) <= 200 else assets[0][:200] + "\n..."
        lines.append("  issue_sample (write exactly, then run the API/command from the issue):")
        for pline in preview.splitlines() or [preview]:
            lines.append(f"    {pline}")
    cf_assets = list(getattr(state, "issue_repro_casefold_assets", None) or [])
    if cf_assets:
        preview = cf_assets[0] if len(cf_assets[0]) <= 160 else cf_assets[0][:160] + "\n..."
        lines.append("  casefold_sample:")
        for pline in preview.splitlines() or [preview]:
            lines.append(f"    {pline}")
    required = list(getattr(state, "issue_repro_required_tokens", None) or [])
    if required and not assets:
        lines.append(f"  required_tokens: {', '.join(required[:6])}")
    fails = list(getattr(state, "issue_repro_fail_signals", None) or [])
    if fails:
        lines.append(f"  must_not_still_show: {', '.join(fails[:4])}")
    expects = list(getattr(state, "issue_repro_expect_signals", None) or [])
    if expects and not fails:
        lines.append(f"  expect_hint: {', '.join(expects[:4])}")
    commands = list(getattr(state, "issue_repro_commands", None) or [])
    markers = list(getattr(state, "issue_repro_markers", None) or [])
    if commands:
        lines.append("  suggested_repro:")
        for cmd in commands[:_RELATED_CAP]:
            lines.append(f"    - {cmd}")
    elif markers and not assets:
        lines.append(f"  issue_markers: {', '.join(markers[:6])}")
        lines.append(
            "  suggested_repro: 用 run_command 按问题中的示例构造输入并复现"
        )
    lines.append(
        "  要求: 覆盖上述 obligation_* 并确认成功后再交卷；"
        "确实无法运行则说明原因后交卷"
    )
    return "\n".join(lines)


def _merge_related(state: Any, related: list[Any]) -> None:
    """将 edit_file 返回的 related_tests 合并进 Turn 级 union（去重、上限 _RELATED_CAP）。"""
    existing = list(getattr(state, "related_tests_union", None) or [])
    seen = set(related_test_paths(existing))
    for item in related:
        if isinstance(item, dict):
            path = str(item.get("path") or "").replace("\\", "/").lstrip("./")
            if not path or path in seen:
                continue
            cmd = str(item.get("command") or "").strip()
            if not cmd:
                from app.structural.related_tests import pytest_command_for

                cmd = pytest_command_for(path)
            existing.append({"path": path, "command": cmd})
            seen.add(path)
        elif isinstance(item, str) and item.strip():
            path = item.replace("\\", "/").lstrip("./")
            if not path or path in seen:
                continue
            from app.structural.related_tests import pytest_command_for

            existing.append({"path": path, "command": pytest_command_for(path)})
            seen.add(path)
        if len(existing) >= _RELATED_CAP:
            break
    state.related_tests_union = existing[:_RELATED_CAP]


def should_inject_writing_delivery_hold(state: Any, *, reserve_steps: int = 1) -> bool:
    """Turn 将结束时 manifest 仍开过程门或篇幅不足 → 注入交付门 receipt。"""
    if bool(getattr(state, "cancelled", False)):
        return False
    if bool(getattr(state, "budget_exceeded", False)):
        return False
    if bool(getattr(state, "writing_delivery_hold_sent", False)):
        return False
    if str(getattr(state, "scenario_id", "") or "") != "writing":
        return False
    remaining = _remaining_steps(state)
    if remaining < 1:
        return False
    from app.writing.delivery_gate import manifest_delivery_blockers, read_turn_manifest

    manifest = read_turn_manifest(
        getattr(state, "turn_id", None),
        getattr(state, "session_id", None),
    )
    return bool(manifest_delivery_blockers(manifest))


def build_writing_delivery_hold_text(state: Any) -> str:
    from app.writing.delivery_gate import (
        delivery_hold_notice,
        manifest_book_scope,
        manifest_delivery_blockers,
        read_turn_manifest,
    )

    manifest = read_turn_manifest(
        getattr(state, "turn_id", None),
        getattr(state, "session_id", None),
    )
    blockers = manifest_delivery_blockers(manifest)
    return delivery_hold_notice(blockers, book_scope=manifest_book_scope(manifest))


def mark_writing_delivery_hold_injected(state: Any) -> None:
    state.writing_delivery_hold_sent = True
