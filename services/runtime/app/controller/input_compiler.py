"""用户输入编译：斜杠命令展开、元数据提取与 @path 预读。

English: User input compiler — slash expansion, metadata extraction, optional @path preread.

在 turn 进入引擎前，将原始用户消息规范化为 ``CompiledInput``（消息列表 + metadata）。
职责包括：

- 写作/Agent 斜杠（``/polish``、``/outline``、``/test``、``/lint``）展开为确定性用户侧指令（docs/14 §6.4、docs/30 AQ2），**不**修改 system prefix（C3）。
- 提取 plan hint、选区、``@path`` 引用、recall 轻提示等 metadata。
- 可选 ``enrich_with_preread``：在预算与超时内将 @path 文件片段追加到用户消息。
- ``should_query``：本地可响应的斜杠（``/help``、``/version`` 等）与空消息拦截，决定是否走模型。
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from app.engine.state import user_message
from app.settings import settings
from app.controller.plan_suggest import detect_plan_hint

_SLASH_HELP = re.compile(r"^\s*/help\b", re.I)
_SLASH_VERSION = re.compile(r"^\s*/version\b", re.I)
_SLASH_COMPACT = re.compile(r"^\s*/compact\b", re.I)
_SLASH_VERIFY = re.compile(r"^\s*/verify\b", re.I)
_SLASH_POLISH = re.compile(r"^\s*/polish(?:\s+(.*))?$", re.I | re.S)
_SLASH_OUTLINE = re.compile(r"^\s*/outline(?:\s+(.*))?$", re.I | re.S)
_SLASH_TEST = re.compile(r"^\s*/test(?:\s+(.*))?$", re.I | re.S)
_SLASH_LINT = re.compile(r"^\s*/lint(?:\s+(.*))?$", re.I | re.S)
_PATH_REF = re.compile(r"@([\w./-]+\.(?:md|txt|py|ts|json|yaml|yml)|[\w./-]+)")
# HM9: 轻量 recall 提示（不自动注入记忆）。
_RECALL_HINT = re.compile(
    r"(记得|上次|之前说过|之前说的|recall|remember\s+when|last\s+time)",
    re.I,
)

# 确定性用户侧展开（docs/14 §6.4）。禁止改动 system prefix（C3）。
POLISH_EXPAND = (
    "[polish] 只改文风与节奏；禁改专名、情节、[cite:*]；"
    "禁止调用 search_sources；逐段 propose_patch。"
)
OUTLINE_EXPAND = (
    "[outline] 只产出或修改 outline.md，不写正文；"
    "禁止调用 search_sources；使用 update_outline。"
    "用户要几章就写几章。"
    "默认写章纲（每章几句这场干什么即可；不要写成小正文，也不要先写完一卷）。"
    "点明本章推进什么。纲用直说。"
    "短篇/单篇：纲可选；不要写成风格契约或世界法。"
    "长篇：先写眼前这一池（跟着谁、站在哪、眼下要什么），"
    "前几章还在同一池子里往前；后面的海不要写进开篇。"
    "经典文学（literary）：第一章环境托人物，机构专名不要当开篇第一词；身世不进第一章。"
    "连载网文（web_serial）：只给题材时先写 2～3 个互不换皮的近池候选，点了再订第一章；"
    "第一章前三分之一交到这场要的得到或发现。设定随事露头，勿提前兑卷末大高潮。"
    "长篇须点明：主线（故事往哪走即可，顶点可后补）、近几章职务。"
    "不要另套一张「要/挡」总表，也不要先交全书规则。"
    "仅当用户要「简略/目录」时才可只写标题。"
    "批量扩章用 append；写清这场即可，不必为凑字加厚。"
)
# Agent 斜杠展开（docs/30 AQ2）。
TEST_EXPAND = (
    "[test] 运行项目测试并报告失败项；优先调用 run_tests；"
    "仅当标准测试命令不适用时才用 run_command；不要改代码除非用户要求修失败。"
)
LINT_EXPAND = (
    "[lint] 对工作区调用 read_lints；汇总诊断；"
    "若存在你引入的问题再 edit_file 修复；不要无关重构。"
)


def expand_writing_slash(message: str) -> tuple[str, str | None]:
    """将 ``/polish`` 或 ``/outline`` 展开为用户消息后缀。

    参数:
        message: 原始用户输入（会先 ``strip``）。

    返回:
        ``(展开后文本, 斜杠名)``；未匹配时 ``(原 message, None)``。
    """
    text = message.strip()
    m = _SLASH_POLISH.match(text)
    if m:
        rest = (m.group(1) or "").strip()
        expanded = f"{POLISH_EXPAND}" + (f"\n{rest}" if rest else "")
        return expanded, "polish"
    m = _SLASH_OUTLINE.match(text)
    if m:
        rest = (m.group(1) or "").strip()
        expanded = f"{OUTLINE_EXPAND}" + (f"\n{rest}" if rest else "")
        return expanded, "outline"
    return message, None


def expand_agent_slash(message: str) -> tuple[str, str | None]:
    """将 ``/test`` 或 ``/lint`` 展开为明确的 Agent 侧指令（docs/30 AQ2）。

    参数:
        message: 原始用户输入（会先 ``strip``）。

    返回:
        ``(展开后文本, 斜杠名)``；未匹配时 ``(原 message, None)``。
    """
    text = message.strip()
    m = _SLASH_TEST.match(text)
    if m:
        rest = (m.group(1) or "").strip()
        expanded = f"{TEST_EXPAND}" + (f"\n{rest}" if rest else "")
        return expanded, "test"
    m = _SLASH_LINT.match(text)
    if m:
        rest = (m.group(1) or "").strip()
        expanded = f"{LINT_EXPAND}" + (f"\n{rest}" if rest else "")
        return expanded, "lint"
    return message, None


@dataclass
class CompiledInput:
    """编译后的用户输入：引擎可读消息列表与旁路 metadata。"""

    messages: list[dict]
    metadata: dict


class InputCompiler:
    """将原始用户消息编译为 ``CompiledInput``。"""

    def compile(
        self,
        message: str,
        *,
        selection: str | None = None,
        scenario_id: str | None = None,
    ) -> CompiledInput:
        """展开斜杠、附加选区与 @path 块，并收集 metadata。

        参数:
            message: 用户原始文本。
            selection: 编辑器选区；非空时追加 ``[selection]`` 块并设 ``has_selection``。
            scenario_id: 场景 ID，传给 ``detect_plan_hint``。

        返回:
            含单条 ``user`` 消息与 metadata 的 ``CompiledInput``。
        """
        text = message.strip()
        metadata: dict = {}
        text, slash = expand_writing_slash(text)
        if not slash:
            text, slash = expand_agent_slash(text)
        if slash:
            metadata["slash_expand"] = slash
            text = text.strip()
        plan_hint = detect_plan_hint(text, scenario_id=scenario_id)
        if plan_hint:
            metadata["plan_hint"] = plan_hint
        if selection:
            text = f"{text}\n\n[selection]\n{selection}"
            metadata["has_selection"] = True
        path_refs = _PATH_REF.findall(text)
        if path_refs:
            metadata["path_refs"] = path_refs
            refs_block = "\n".join(f"- {path}" for path in path_refs)
            text = f"{text}\n\n[file_refs]\n{refs_block}"
        if _RECALL_HINT.search(text):
            metadata["recall_hint"] = True
        return CompiledInput(messages=[user_message(text)], metadata=metadata)

    async def enrich_with_preread(
        self,
        compiled: CompiledInput,
        *,
        abort: asyncio.Event | None = None,
    ) -> CompiledInput:
        """在预算与超时内将 @path 文件片段预读并追加到用户消息。

        超时或取消时保留原有 ``[file_refs]`` 指针，仅更新 metadata 状态。

        参数:
            compiled: ``compile`` 产出；须含 ``metadata["path_refs"]`` 才有预读。
            abort: 可选取消事件；已 set 则标记 ``path_preread=cancelled`` 并返回。

        返回:
            新 ``CompiledInput``；无 path_refs 时原样返回同一结构。
        """
        path_refs = list(compiled.metadata.get("path_refs") or [])
        if not path_refs:
            return compiled
        max_files = max(1, settings.path_preread_max_files)
        budget = max(200, settings.path_preread_max_chars)
        timeout_s = max(0.05, settings.path_preread_timeout_seconds)
        try:
            snippets = await asyncio.wait_for(
                asyncio.to_thread(
                    _preread_paths,
                    path_refs[:max_files],
                    budget,
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            compiled.metadata["path_preread"] = "timeout"
            return compiled
        if abort is not None and abort.is_set():
            compiled.metadata["path_preread"] = "cancelled"
            return compiled
        if not snippets:
            compiled.metadata["path_preread"] = "empty"
            return compiled
        block = "\n\n".join(snippets)
        compiled.metadata["path_preread"] = "ok"
        compiled.metadata["hot_files"] = [s.split("\n", 1)[0].replace("## ", "").strip() for s in snippets]
        # 预读块追加到最后一条 user 消息的 text 块末尾。
        messages = [dict(m) for m in compiled.messages]
        for msg in reversed(messages):
            if msg.get("role") != "user":
                continue
            content = list(msg.get("content") or [])
            for i, block_item in enumerate(content):
                if block_item.get("type") == "text":
                    content[i] = {
                        **block_item,
                        "text": f"{block_item.get('text', '')}\n\n[preread]\n{block}",
                    }
                    break
            msg["content"] = content
            break
        return CompiledInput(messages=messages, metadata=compiled.metadata)


def _preread_paths(paths: list[str], budget: int) -> list[str]:
    """同步读取 workspace 内相对路径文件头，受字符预算约束。

    参数:
        paths: 相对 workspace_root 的路径列表（已截断数量由调用方控制）。
        budget: 全部 snippet 合计最大字符数。

    返回:
        ``## {rel}\\n{snippet}`` 字符串列表；越界路径或非文件跳过。
    """
    root = Path(settings.workspace_root).resolve()
    snippets: list[str] = []
    used = 0
    for rel in paths:
        remaining = budget - used
        if remaining <= 0:
            break
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            # 路径逃逸 workspace，跳过。
            continue
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        head = "\n".join(lines[:80])
        snippet = head[:remaining]
        snippets.append(f"## {rel}\n{snippet}")
        used += len(snippet)
    return snippets


@dataclass
class ShouldQueryResult:
    """``should_query`` 判定结果：是否走模型及本地短路响应。"""

    should_query: bool
    local_response: str | None = None
    failure_reason: str | None = None
    slash_command: str | None = None


def should_query(message: str, *, has_model_key: bool) -> ShouldQueryResult:
    """判断用户消息是否应发起模型 turn，或本地/斜杠短路。

    参数:
        message: 用户原始文本。
        has_model_key: 是否配置模型 API key；无 key 时 stub 模式仍 ``should_query=True``。

    返回:
        ``ShouldQueryResult``：``should_query=False`` 时看 ``local_response`` 或 ``slash_command``。
    """
    text = message.strip()
    if not text:
        return ShouldQueryResult(False, failure_reason="empty_message")
    if _SLASH_HELP.match(text):
        return ShouldQueryResult(
            False,
            local_response=(
                "Agent Platform — commands:\n"
                "  /help — this message\n"
                "  /version — platform version\n"
                "  /compact — compact session context into summary\n"
                "  /verify — fact-check drafts/exports (does not mutate drafts)\n"
                "  /polish — style-only polish pass (no search_sources; propose_patch)\n"
                "  /outline — outline-only pass (update_outline; no prose)\n"
                "  /test — run project tests (run_tests; report failures)\n"
                "  /lint — read_lints and fix introduced issues\n"
                "Send any other message to start a turn."
            ),
        )
    if _SLASH_VERSION.match(text):
        return ShouldQueryResult(False, local_response="Agent Platform v1.0.0")
    if _SLASH_COMPACT.match(text):
        return ShouldQueryResult(False, slash_command="compact")
    if _SLASH_VERIFY.match(text):
        return ShouldQueryResult(False, slash_command="verify")
    if not has_model_key:
        # 无 key 仍走引擎，使用确定性 stub provider。
        return ShouldQueryResult(True)
    return ShouldQueryResult(True)
