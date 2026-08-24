"""上下文组装引擎：Turn 消息压缩、预算估算与工具执行门面。

English: Context assembly engine — message compaction, budget estimation, and tool
dispatch facade for each LLM call.

``ContextEngine`` 在每次 LLM 调用前将 ``TurnState.messages`` 与 system/project/runtime/
volatile 前缀合并，按 ``CompactionPolicy`` 的 fill 档位（默认 0.80 / 0.90 / 0.95）
依次执行 read 折叠、tool 结果截断、microcompact、collapse、snip、autocompact，
并输出 provider 可消费的 message 列表。

``ToolExecutor`` 负责单工具 dispatch：审批 sticky、schema 校验、超时与 handler 调用。

模块级 ``estimate_*`` 函数供预算报表与 observability 复用同一 token 启发式。

组窗顺序（HM6/WT5）
-------------------
system（字节稳定，利于 prompt cache）→ project → volatile → 压缩后 history →
runtime（含 step=N，必须 trailing，避免每步破坏 append-only 前缀缓存）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from app.context.policy import CompactionPolicy
from app.context.project import build_runtime_context, load_project_context
from app.context.summary import structured_summary_from_messages
from app.engine.state import TurnState
from app.tools.registry import (
    EXEC_APPROVAL_STICKY_TOOLS,
    ToolSpec,
    WRITE_APPROVAL_STICKY_TOOLS,
)

logger = logging.getLogger(__name__)

# Settings 不可 import 时（单测隔离）的 tool_result 字符预算兜底。
TOOL_RESULT_CHAR_BUDGET = 4_000
TOOL_RESULT_LATEST_READ_CHAR_BUDGET = 32_000
SHORT_TOOL_RESULT_MAX_CHARS = 800


class ToolExecutor:
    """工具注册表上的 sync/async 执行器；封装审批门、校验与 handler 调用。

    English: Dispatches registered tool handlers with approval gates, JSON Schema
    validation, timeouts, and ops_eval / sticky-write shortcuts.
    """

    def __init__(self, specs: list[ToolSpec]) -> None:
        """按工具名索引 ``ToolSpec`` 处理器。

        English: Build name → ToolSpec map from the scenario-scoped tool list.

        参数:
            specs: 场景 bootstrap 注入的完整工具规格列表。
        """
        self._specs = {s.name: s for s in specs}

    async def run(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        arguments: dict[str, Any],
        state: TurnState,
        force_approval: bool = False,
    ) -> dict[str, Any]:
        """执行单次工具调用并返回结构化结果 dict。

        English: Run one tool call end-to-end. Returns handler result or structured
        error / approval_required / invalid_arguments / timeout payloads.

        审批逻辑：未知工具直接 error；需审批时检查 ops_eval、同 Turn sticky
        （writes_preapproved / exec_preapproved）、run_command allowlist；否则
        返回 ``approval_required``。通过后可选 schema 校验，再 ``wait_for`` handler。

        参数:
            tool_name: 注册工具名。
            tool_call_id: 与 assistant tool_use 关联的 id（审批 payload 用）。
            arguments: 模型给出的 JSON 参数。
            state: 当前 Turn 状态（传 turn_id/run_id 等给 handler）。
            force_approval: True 时跳过人工审批门（checkpoint 恢复等路径）。

        返回:
            工具 handler 返回值，或 error/timeout/approval_required/invalid_arguments。
        """
        spec = self._specs.get(tool_name)
        if spec is None:
            return {"error": f"Tool not available: {tool_name}"}
        if spec.requires_approval and not force_approval:
            # Ops L1 / official bench Turns are unattended — never block on human approve.
            if bool(getattr(state, "ops_eval", False)):
                pass
            else:
                # Same-Turn sticky: one write approval covers further file mutations.
                # Shell: ops_eval exec_preapproved, or a saved command-prefix allow list.
                write_sticky = bool(getattr(state, "writes_preapproved", False))
                exec_sticky = bool(getattr(state, "exec_preapproved", False))
                if write_sticky and tool_name in WRITE_APPROVAL_STICKY_TOOLS:
                    pass
                elif exec_sticky and tool_name in EXEC_APPROVAL_STICKY_TOOLS:
                    pass
                elif tool_name == "run_command":
                    from app.tools.command_allowlist import command_is_allowlisted

                    if await command_is_allowlisted(state, arguments):
                        pass
                    else:
                        return {
                            "status": "approval_required",
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                        }
                else:
                    return {
                        "status": "approval_required",
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                    }

        from app.settings import settings
        from app.tools.validate import validate_tool_arguments

        if settings.tool_schema_validate:
            invalid = validate_tool_arguments(
                tool_name=tool_name,
                arguments=arguments,
                parameters=spec.parameters,
            )
            if invalid is not None:
                from app.observability.metrics import record_tool_misuse

                record_tool_misuse(kind="invalid_arguments", tool_name=tool_name)
                return invalid

        timeout_s = spec.timeout_s
        try:
            result = await asyncio.wait_for(
                spec.handler(
                    **arguments,
                    turn_id=state.turn_id,
                    run_id=state.run_id,
                    session_id=state.session_id,
                    plan_phase=state.plan_phase,
                    scenario_id=state.scenario_id,
                    turn_user_text=getattr(state, "turn_user_text", "") or "",
                ),
                timeout=timeout_s,
            )
            return result
        except asyncio.TimeoutError:
            return {
                "status": "timeout",
                "summary": f"tool {tool_name} timed out after {timeout_s:.0f}s",
            }
        except TypeError as exc:
            # Defensive: unexpected kwargs / missing positional after schema gate.
            return {
                "error": "invalid_arguments",
                "tool_name": tool_name,
                "summary": f"Tool {tool_name} rejected arguments: {exc}",
                "details": [str(exc)],
                "missing": [],
            }
        except Exception as exc:
            return {"error": str(exc)}


@dataclass
class ContextEnvelope:
    """``_build_envelope`` 的中间产物：压缩后的 messages 与预算/追踪元数据。"""

    messages: list[dict[str, Any]]
    budget_report: dict[str, Any] = field(default_factory=dict)
    compaction_trace: list[dict[str, str]] = field(default_factory=list)
    project_context: str = ""
    runtime_context: str = ""
    volatile_context: str = ""
    included_tools: list[str] = field(default_factory=list)
    assemble_ms: float = 0.0
    system_prompt: str = ""


class ContextEngine:
    """Turn 级上下文组装与压缩 orchestrator。

    English: Orchestrates per-turn context assembly and compaction. Sync ``assemble``
    is deterministic-only; ``assemble_async`` may call LLM or precompact cache when
    fill hits autocompact. Exposes ``last_*`` for observability and Web budget UI.
    """

    def __init__(
        self,
        *,
        policy: CompactionPolicy | None = None,
        token_budget: int | None = None,
    ) -> None:
        """构造引擎；三选一指定压缩策略来源。

        参数:
            policy: 显式 ``CompactionPolicy``；优先于 token_budget。
            token_budget: 旧单测 API；映射为 ``legacy_messages_budget``。
            二者皆 None 时从 ``settings`` 加载。
        """
        if policy is not None:
            self._policy = policy
        elif token_budget is not None:
            self._policy = CompactionPolicy.legacy_messages_budget(token_budget)
        else:
            self._policy = CompactionPolicy.from_settings()
        self.last_compaction_trace: list[dict[str, str]] = []
        self.last_budget_report: dict[str, Any] = {
            "tokens_before": 0,
            "tokens_after": 0,
            "token_budget": self._policy.model_window_tokens,
            "fill_ratio": 0.0,
        }
        self.last_assemble_ms: float = 0.0
        self._reuse_fingerprint: str | None = None
        self._reuse_messages: list[dict[str, Any]] | None = None

    def assemble(
        self,
        *,
        system_prompt: str,
        state: TurnState,
        tools: list[dict[str, Any]] | None = None,
        model_name: str | None = None,
        volatile_context: str = "",
    ) -> list[dict]:
        """同步组装 LLM 请求消息列表（无 LLM autocompact）。

        English: Deterministic compaction path only — no gateway LLM summarization.

        参数:
            system_prompt: 场景 system.md 正文（缓存友好前缀）。
            state: Turn 状态；读取 messages/step/plan_hint 等。
            tools: 可选 OpenAI tools schema 列表（计入 token 预算）。
            model_name: 写入 runtime_context 的模型展示名。
            volatile_context: 写作 cards/focus 等易变块（不进 system）。

        返回:
            完整 message 列表：system → project → volatile → 压缩后 history → runtime。
        """
        started = time.monotonic()
        envelope = self._build_envelope(
            state=state,
            system_prompt=system_prompt,
            tools=tools,
            model_name=model_name,
            volatile_context=volatile_context,
        )
        envelope.assemble_ms = (time.monotonic() - started) * 1000
        self._finalize_envelope(envelope, state.turn_id)
        return self._materialize_messages(envelope)

    async def assemble_async(
        self,
        *,
        system_prompt: str,
        state: TurnState,
        gateway: Any | None = None,
        tools: list[dict[str, Any]] | None = None,
        model_name: str | None = None,
        abort: Any | None = None,
        volatile_context: str = "",
    ) -> list[dict]:
        """异步组装；fill 触顶且 defer 时可 LLM/缓存 autocompact。

        English: Full assembly path with optional LLM/deterministic autocompact when
        fill exceeds policy. Reuses cached assembled messages when fingerprint matches
        and no autocompact_pending remains.

        指纹命中且无 pending autocompact 时零成本复用 ``_reuse_messages``。
        gateway 非 None 且 trace 含 ``autocompact_pending`` 时：优先 precompact 缓存，
        否则按 ``context_hard_autocompact_allow_llm`` 选 LLM 或确定性摘要。

        参数:
            system_prompt: 场景 system 正文。
            state: Turn 状态。
            gateway: 可选 LLM gateway（autocompact 用）；None 则仅确定性路径。
            tools: tools schema。
            model_name: runtime 块展示用。
            abort: 可选 asyncio.Event 式对象；已 set 时早退不重试 autocompact。
            volatile_context: 易变写作上下文。

        返回:
            同 ``assemble`` 的最终 message 列表。
        """
        from app.context.compact_summarizer import summarize_messages_with_gateway
        from app.settings import settings

        started = time.monotonic()
        fingerprint = _assemble_fingerprint(
            system_prompt, state, tools, volatile_context=volatile_context
        )
        if (
            self._reuse_fingerprint == fingerprint
            and self._reuse_messages is not None
            and not any(
                t.get("detail") == "autocompact_pending"
                for t in (self.last_compaction_trace or [])
            )
        ):
            # Reuse only when fingerprint matches and no pending LLM compact needed.
            self.last_assemble_ms = 0.0
            self.last_budget_report = {
                **self.last_budget_report,
                "assemble_ms": 0.0,
            }
            return [dict(m) for m in self._reuse_messages]

        defer = gateway is not None
        envelope = self._build_envelope(
            state=state,
            system_prompt=system_prompt,
            tools=tools,
            defer_autocompact=defer,
            model_name=model_name,
            volatile_context=volatile_context,
        )
        trace = list(envelope.compaction_trace)
        messages = list(envelope.messages)

        if abort is not None and getattr(abort, "is_set", lambda: False)():
            envelope.assemble_ms = (time.monotonic() - started) * 1000
            self._finalize_envelope(envelope, state.turn_id)
            return self._materialize_messages(envelope)

        if gateway is not None and any(t.get("detail") == "autocompact_pending" for t in trace):
            # HM1: prefer soft-precompact cache; else deterministic summary.
            # Sync compact LLM is opt-in (context_hard_autocompact_allow_llm).
            used_cache = False
            try:
                from app.context.precompact_cache import (
                    load_precompact_cache,
                    summary_from_cache_record,
                )

                cached = await load_precompact_cache(state.session_id)
                if cached:
                    summary = summary_from_cache_record(cached)
                    if summary.narrative or summary.task:
                        messages = [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": summary.to_autocompact_text(),
                                    }
                                ],
                            }
                        ]
                        used_cache = True
                        trace = [t for t in trace if t.get("detail") != "autocompact_pending"]
                        trace.append({"strategy": "compact", "detail": "autocompact_cached"})
            except Exception:
                used_cache = False

            if not used_cache:
                if settings.context_hard_autocompact_allow_llm:
                    compact_gateway = gateway
                    if settings.compact_model_name.strip():
                        from app.controller.session_context import load_session_owner_user_id
                        from app.model.config import resolve_model_config
                        from app.model.factory import create_gateway

                        owner_user_id = await load_session_owner_user_id(state.session_id)
                        cfg = await resolve_model_config(owner_user_id=owner_user_id)
                        compact_gateway = create_gateway(
                            cfg,
                            messages=[],
                            scenario_id=state.scenario_id,
                            for_compact=True,
                        )
                    messages = [
                        await summarize_messages_with_gateway(compact_gateway, state.messages)
                    ]
                    detail = "autocompact_llm"
                else:
                    messages = [_summarize_messages(list(state.messages))]
                    detail = "autocompact_deterministic"
                trace = [t for t in trace if t.get("detail") != "autocompact_pending"]
                trace.append({"strategy": "compact", "detail": detail})
            fill_ratio, window = _window_fill(
                messages=messages,
                system_prompt=system_prompt,
                tools=tools,
                policy=self._policy,
                project_context=envelope.project_context,
                runtime_context=envelope.runtime_context,
                volatile_context=envelope.volatile_context,
            )
            envelope.budget_report = {
                **envelope.budget_report,
                "tokens_after": window["tokens_after"],
                "messages_tokens": window["messages_tokens"],
                "fill_ratio": round(fill_ratio, 4),
            }
            envelope.messages = messages
            envelope.compaction_trace = trace

        envelope.assemble_ms = (time.monotonic() - started) * 1000
        self._finalize_envelope(envelope, state.turn_id)
        result = self._materialize_messages(envelope)
        self._reuse_fingerprint = fingerprint
        self._reuse_messages = [dict(m) for m in result]
        return result

    def _materialize_messages(self, envelope: ContextEnvelope) -> list[dict[str, Any]]:
        """将 envelope 转为 provider 顺序的最终 messages。

        English: Materialize ContextEnvelope to provider message list.

        HM6/WT5：system.md 字节稳定以利 prompt cache；runtime（含 step=N）必须
        trailing 在历史之后，避免每步破坏 append-only 前缀缓存。
        """
        out = _prefix_messages(
            system_prompt=envelope.system_prompt,
            project_context=envelope.project_context,
            volatile_context=envelope.volatile_context,
        )
        out.extend(envelope.messages)
        runtime_msg = _runtime_user_message(envelope.runtime_context)
        if runtime_msg is not None:
            out.append(runtime_msg)
        return out

    def _finalize_envelope(self, envelope: ContextEnvelope, turn_id: Any) -> None:
        """把 envelope 的 trace/budget/assemble_ms 写入实例 ``last_*`` 并打日志。"""
        self.last_compaction_trace = envelope.compaction_trace
        self.last_budget_report = dict(envelope.budget_report)
        self.last_budget_report["assemble_ms"] = envelope.assemble_ms
        self.last_budget_report["project_tokens"] = estimate_payload_tokens(
            envelope.project_context
        )
        self.last_budget_report["runtime_tokens"] = estimate_payload_tokens(
            envelope.runtime_context
        )
        self.last_budget_report["volatile_tokens"] = estimate_payload_tokens(
            envelope.volatile_context
        )
        self.last_assemble_ms = envelope.assemble_ms
        if envelope.compaction_trace:
            logger.info(
                "context compaction turn_id=%s strategies=%s before=%s after=%s fill=%s",
                turn_id,
                [t.get("strategy") for t in envelope.compaction_trace],
                envelope.budget_report.get("tokens_before"),
                envelope.budget_report.get("tokens_after"),
                envelope.budget_report.get("fill_ratio"),
            )

    def _build_envelope(
        self,
        *,
        state: TurnState,
        system_prompt: str,
        tools: list[dict[str, Any]] | None,
        defer_autocompact: bool = False,
        model_name: str | None = None,
        volatile_context: str = "",
    ) -> ContextEnvelope:
        """核心压缩流水线：fold → budget → microcompact → collapse → snip → autocompact。

        参数:
            state: Turn 状态；messages 拷贝自 state.messages，evicted_paths 可能原地更新。
            system_prompt: 场景 system。
            tools: tools schema。
            defer_autocompact: True 时在 fill_autocompact 处只打 pending 标记，不立刻摘要。
            model_name: runtime_context 用。
            volatile_context: 写作 volatile 块。

        返回:
            含压缩后 messages、budget_report、compaction_trace 的 ``ContextEnvelope``。
        """
        policy = self._policy
        messages = [dict(m) for m in state.messages]
        trace: list[dict[str, str]] = []
        project_context = load_project_context(session_id=state.session_id)
        runtime_context = build_runtime_context(
            scenario_id=state.scenario_id,
            step_count=state.step_count,
            max_steps=state.max_steps,
            model_name=model_name,
            plan_hint=state.plan_hint,
        )
        included_tools = [str(t.get("name", "")) for t in (tools or []) if t.get("name")]
        volatile = (volatile_context or "").strip()

        _, window_before = _window_fill(
            messages=messages,
            system_prompt=system_prompt,
            tools=tools,
            policy=policy,
            project_context=project_context,
            runtime_context=runtime_context,
            volatile_context=volatile,
        )
        tokens_before = window_before["tokens_after"]

        # C-1: fold stale reads first, then apply differential budgets so the
        # latest read_file body can keep up to latest_read budget (default 32k).
        messages, folded_reads, folded_paths = _fold_stale_read_file_results(
            messages, keep_last_per_path=1
        )
        if folded_reads:
            trace.append(
                {"strategy": "read_fold", "detail": f"folded_{folded_reads}_read_file_results"}
            )
        evicted: set[str] = set(folded_paths)

        messages, budgeted, truncated_by_tool = _apply_tool_result_budget(
            messages,
            preserve_short=True,
        )
        if budgeted:
            trace.append({"strategy": "budget", "detail": f"truncated_{budgeted}_tool_results"})

        messages, micro = _microcompact_tool_results(messages)
        if micro:
            trace.append({"strategy": "microcompact", "detail": f"folded_{micro}_tool_results"})

        fill_ratio, _ = _window_fill(
            messages=messages,
            system_prompt=system_prompt,
            tools=tools,
            policy=policy,
            project_context=project_context,
            runtime_context=runtime_context,
            volatile_context=volatile,
        )
        if fill_ratio >= policy.fill_collapse and len(messages) > 4:
            before_collapse = messages
            messages = _collapse_tool_history(
                messages,
                trace,
                system_prompt=system_prompt,
                tools=tools,
                policy=policy,
                volatile_context=volatile,
            )
            if messages is not before_collapse:
                evicted |= _read_paths_missing_after(before_collapse, messages)

        while len(messages) > 1:
            fill_ratio, _ = _window_fill(
                messages=messages,
                system_prompt=system_prompt,
                tools=tools,
                policy=policy,
                project_context=project_context,
                runtime_context=runtime_context,
                volatile_context=volatile,
            )
            if fill_ratio < policy.fill_snip:
                break
            protect_from = _protected_tail_start(messages)
            before_snip = list(messages)
            if not _pop_oldest_message_group(messages, protect_from=protect_from):
                break
            trace.append({"strategy": "snip", "detail": "dropped_oldest_message"})
            evicted |= _read_paths_missing_after(before_snip, messages)

        # C1: paths whose bodies left the visible window may be re-read once.
        if evicted:
            state.evicted_paths |= {
                p for p in evicted if p not in state.evicted_reread_used
            }

        fill_ratio, _ = _window_fill(
            messages=messages,
            system_prompt=system_prompt,
            tools=tools,
            policy=policy,
            project_context=project_context,
            runtime_context=runtime_context,
            volatile_context=volatile,
        )
        if fill_ratio >= policy.fill_autocompact and messages:
            if defer_autocompact:
                trace.append({"strategy": "compact", "detail": "autocompact_pending"})
            else:
                messages = [_summarize_messages(messages)]
                trace.append({"strategy": "compact", "detail": "autocompact_summary"})

        fill_ratio, window_after = _window_fill(
            messages=messages,
            system_prompt=system_prompt,
            tools=tools,
            policy=policy,
            project_context=project_context,
            runtime_context=runtime_context,
            volatile_context=volatile,
        )
        reserve_tokens = (
            policy.output_reserve_tokens
            + window_after["system_tokens"]
            + window_after["tools_tokens"]
        )
        return ContextEnvelope(
            messages=messages,
            budget_report={
                "tokens_before": tokens_before,
                "tokens_after": window_after["tokens_after"],
                "messages_tokens": window_after["messages_tokens"],
                "system_tokens": window_after["system_tokens"],
                "tools_tokens": window_after["tools_tokens"],
                "project_tokens": window_after.get("project_tokens", 0),
                "runtime_tokens": window_after.get("runtime_tokens", 0),
                "volatile_tokens": window_after.get("volatile_tokens", 0),
                "token_budget": policy.model_window_tokens,
                "reserve_tokens": reserve_tokens,
                "fill_ratio": round(fill_ratio, 4),
                # C3 audit: budget_truncated incidence by tool name.
                "budget_truncated_n": int(budgeted),
                "budget_truncated_by_tool": dict(truncated_by_tool),
                "estimated_tokens": int(window_after["tokens_after"]),
            },
            compaction_trace=trace,
            project_context=project_context,
            runtime_context=runtime_context,
            volatile_context=volatile,
            included_tools=included_tools,
            system_prompt=system_prompt,
        )




def _system_message(system_prompt: str) -> dict[str, Any]:
    """构造单条 system 角色消息。"""
    return {"role": "system", "content": [{"type": "text", "text": system_prompt}]}


def _volatile_user_message(volatile_context: str) -> dict[str, Any] | None:
    """将 volatile 写作上下文包装为带 ``[writing_context]`` 前缀的 user 消息。"""
    text = (volatile_context or "").strip()
    if not text:
        return None
    if not text.startswith("[writing_context]"):
        text = f"[writing_context]\n{text}"
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def _project_user_message(project_context: str) -> dict[str, Any] | None:
    """将工作区 project 摘要包装为带 ``[project_context]`` 前缀的 user 消息。"""
    text = (project_context or "").strip()
    if not text:
        return None
    if not text.startswith("[project_context]"):
        text = f"[project_context]\n{text}"
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def _runtime_user_message(runtime_context: str) -> dict[str, Any] | None:
    """构造 trailing runtime 块（step/plan_hint 等每步可变，不进 system 前缀）。"""
    text = (runtime_context or "").strip()
    if not text:
        return None
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def _prefix_messages(
    *,
    system_prompt: str,
    project_context: str = "",
    volatile_context: str = "",
) -> list[dict[str, Any]]:
    """可缓存前缀：system → project → volatile（不含 per-step runtime）。

    参数:
        system_prompt: 场景 system.md。
        project_context: 工作区派生上下文。
        volatile_context: 写作易变块。

    返回:
        0–3 条前缀消息。
    """
    out: list[dict[str, Any]] = [_system_message(system_prompt)]
    project_msg = _project_user_message(project_context)
    if project_msg is not None:
        out.append(project_msg)
    volatile_msg = _volatile_user_message(volatile_context)
    if volatile_msg is not None:
        out.append(volatile_msg)
    return out


def _assemble_fingerprint(
    system_prompt: str,
    state: TurnState,
    tools: list[dict[str, Any]] | None,
    *,
    volatile_context: str = "",
) -> str:
    """assemble 结果复用指纹：system/volatile/step/messages 长度/scenario/tools。"""
    tool_names = ",".join(str(t.get("name", "")) for t in (tools or []))
    return (
        f"{hash(system_prompt)}|{hash(volatile_context or '')}|{state.step_count}|"
        f"{len(state.messages)}|{state.scenario_id}|{tool_names}|{state.max_steps}"
    )


def _window_fill(
    *,
    messages: list[dict[str, Any]],
    system_prompt: str,
    tools: list[dict[str, Any]] | None,
    policy: CompactionPolicy,
    project_context: str = "",
    runtime_context: str = "",
    volatile_context: str = "",
) -> tuple[float, dict[str, int]]:
    """估算当前 messages + 前缀 + runtime 相对可用窗口的 fill 比例。

    参数:
        messages: 待评估的对话历史（不含前缀与 runtime）。
        system_prompt: system 正文。
        tools: tools schema。
        policy: 压缩策略（窗口与 output reserve）。
        project_context / runtime_context / volatile_context: 各附加块正文。

    返回:
        ``(fill_ratio, window_dict)``；fill_ratio = tokens_after / usable_window。
    """
    assembled = _prefix_messages(
        system_prompt=system_prompt,
        project_context=project_context,
        volatile_context=volatile_context,
    )
    assembled.extend(messages)
    runtime_msg = _runtime_user_message(runtime_context)
    if runtime_msg is not None:
        assembled.append(runtime_msg)
    window = estimate_assembled_window(messages=assembled, tools=tools)
    project_tokens = estimate_payload_tokens(project_context)
    runtime_tokens = estimate_payload_tokens(runtime_context)
    volatile_tokens = estimate_payload_tokens(volatile_context)
    window = {
        **window,
        "project_tokens": project_tokens,
        "runtime_tokens": runtime_tokens,
        "volatile_tokens": volatile_tokens,
    }
    usable = max(1, policy.model_window_tokens - policy.output_reserve_tokens)
    fill_ratio = window["tokens_after"] / usable
    return fill_ratio, window


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """对 message 列表做 token 粗估（至少 1）。"""
    return max(1, estimate_payload_tokens(messages))


# 匹配 ord > 0x2E80 的字符（CJK 等），与旧 Python 逐字循环分类一致，C 层更快。
_CJK_CHAR_PATTERN = re.compile(r"[^\u0000-\u2e80]")


@lru_cache(maxsize=2048)
def _estimate_text_tokens(text: str) -> int:
    """单段文本 token 估计（LRU 缓存；每步 _window_fill 会重复估算未变消息）。

    参数:
        text: 原始字符串。

    返回:
        CJK≈1 token/字，ASCII≈1/4 字节的启发式计数（至少 1）。
    """
    cjk = len(text) - len(_CJK_CHAR_PATTERN.sub("", text))
    other = len(text) - cjk
    return max(1, cjk + (other + 2) // 3)


def estimate_payload_tokens(payload: Any) -> int:
    """对 str 或 JSON 序列化对象做偏保守的 token 粗估（AH4）。

    参数:
        payload: 字符串或可 ``json.dumps`` 的对象；None 视为 0。

    返回:
        估计 token 数（CJK 约 1/字，ASCII 约 1/4 字节，避免 chars/4 乐观溢出）。
    """
    if payload is None:
        return 0
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False)
    if not text:
        return 0
    return _estimate_text_tokens(text)


def estimate_assembled_window(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """估算实际 LLM 请求窗口的 token 分项（provider 计费口径）。

    含 system/user/assistant/tool 消息与 tools schema，而非仅 TurnState.messages。

    参数:
        messages: 已含前缀/runtime 的完整 assembled 列表，或部分列表。
        tools: OpenAI tools 定义。

    返回:
        system/tools/messages/tokens_after 分项 dict。
    """
    system_tokens = 0
    message_tokens = 0
    for msg in messages:
        toks = estimate_payload_tokens(msg)
        if msg.get("role") == "system":
            system_tokens += toks
        else:
            message_tokens += toks
    tools_tokens = estimate_payload_tokens(tools or [])
    return {
        "system_tokens": system_tokens,
        "tools_tokens": tools_tokens,
        "messages_tokens": message_tokens,
        "tokens_after": system_tokens + tools_tokens + message_tokens,
    }


def _message_text(msg: dict[str, Any]) -> str:
    """拼接单条消息中所有 text content block。"""
    parts: list[str] = []
    for block in msg.get("content", []):
        if block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return " ".join(parts).strip()


def estimate_window_breakdown(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """将 assembled 窗口 token 按 Cursor 式类别拆分（Web 预算条用）。

    参数:
        messages: assembled message 列表。
        tools: tools schema。

    返回:
        system/tools/session/user/assistant/tool_results/compaction 等分项。
    """
    window = estimate_assembled_window(messages=messages, tools=tools)
    breakdown = {
        "system": 0,
        "tools": window["tools_tokens"],
        "session": 0,
        "user": 0,
        "assistant": 0,
        "tool_results": 0,
        "compaction": 0,
        "project": 0,
        "runtime": 0,
        "volatile": 0,
    }
    for msg in messages:
        role = msg.get("role")
        toks = estimate_payload_tokens(msg)
        if role == "system":
            breakdown["system"] += toks
            continue
        text = _message_text(msg)
        lower = text.lower()
        if role == "tool":
            breakdown["tool_results"] += toks
        elif text.startswith("[project_context]"):
            breakdown["project"] += toks
        elif text.startswith("[runtime_context]"):
            breakdown["runtime"] += toks
        elif text.startswith("[writing_context]"):
            breakdown["volatile"] += toks
        elif "session context" in lower:
            breakdown["session"] += toks
        elif text.startswith("[") and any(
            marker in lower
            for marker in ("microcompact", "collapsed", "autocompact", "pinned tool")
        ):
            breakdown["compaction"] += toks
        elif role == "user":
            breakdown["user"] += toks
        elif role == "assistant":
            breakdown["assistant"] += toks
    return breakdown


def _tool_result_text(msg: dict[str, Any]) -> str:
    """从 tool 角色消息提取第一个 tool_result 块的 content 字符串。"""
    if msg.get("role") != "tool":
        return ""
    for block in msg.get("content", []):
        if block.get("type") == "tool_result":
            return str(block.get("content", ""))
    return ""


def _is_pinned_short_tool_result(text: str) -> bool:
    """只读目录/列表/搜索等短 JSON 结果在压缩中保持可见（pinned）。"""
    if not text or len(text) > SHORT_TOOL_RESULT_MAX_CHARS:
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    if "entries" in data and "path" in data:
        return True
    if "files" in data and "pattern" in data:
        return True
    if "matches" in data or "hits" in data:
        return True
    if "error" in data:
        return True
    return False


def _pinned_tool_digest(messages: list[dict[str, Any]]) -> str:
    """从消息历史收集 pinned 短 tool 结果摘要，供 collapse 指针附注。"""
    snippets: list[str] = []
    for msg in messages:
        body = _tool_result_text(msg)
        if _is_pinned_short_tool_result(body):
            snippets.append(body.replace("\n", " ")[:160])
    if not snippets:
        return ""
    joined = " | ".join(snippets[:6])
    return f"[pinned tool results preserved: {joined}]"


def _dropped_tools_summary(messages: list[dict[str, Any]]) -> str:
    """统计被 collapse 段内 tool_use 名称与次数（确定性，无重要性排序）。"""
    counts: dict[str, int] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []) or []:
            if block.get("type") != "tool_use":
                continue
            name = str(block.get("name") or "unknown")
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return ""
    parts = [
        f"{name}×{count}"
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return "dropped tools: " + ", ".join(parts)


def _budget_limits() -> tuple[int, int, bool]:
    """读取 tool_result 字符预算与 snip 保护开关。

    返回:
        ``(default_budget, latest_read_budget, snip_protect_latest_read)``；
        settings 不可用时用模块级常量兜底。
    """
    try:
        from app.settings import settings

        return (
            int(settings.tool_result_char_budget),
            int(settings.tool_result_latest_read_char_budget),
            bool(settings.context_snip_protect_latest_read),
        )
    except Exception:  # noqa: BLE001
        return (
            TOOL_RESULT_CHAR_BUDGET,
            TOOL_RESULT_LATEST_READ_CHAR_BUDGET,
            True,
        )


def _latest_read_file_tool_use_ids(messages: list[dict[str, Any]]) -> set[str]:
    """时间序上最后一条 read_file tool_result 的 tool_use_id 集合（0 或 1 个）。"""
    name_by_id = _tool_use_name_by_id(messages)
    latest_id: str | None = None
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        for block in msg.get("content", []) or []:
            if block.get("type") != "tool_result":
                continue
            tid = str(block.get("tool_use_id") or "")
            if name_by_id.get(tid) == "read_file":
                latest_id = tid
    return {latest_id} if latest_id else set()


def _protected_tail_start(messages: list[dict[str, Any]]) -> int:
    """受保护尾部起始下标：当前 user 指令 + 最新 read_file 周期不可 snip/collapse。

    ``messages[:start]`` 可被 snip；``[start:]`` 在 ``context_snip_protect_latest_read``
    开启时必须保留。
    """
    _, _, protect = _budget_limits()
    if not protect or not messages:
        return 0

    last_user = 0
    for i, msg in enumerate(messages):
        if msg.get("role") == "user":
            last_user = i

    name_by_id = _tool_use_name_by_id(messages)
    latest_read_msg: int | None = None
    for i, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        for block in msg.get("content", []) or []:
            if block.get("type") != "tool_result":
                continue
            tid = str(block.get("tool_use_id") or "")
            if name_by_id.get(tid) == "read_file":
                latest_read_msg = i

    protect_at = last_user
    if latest_read_msg is not None:
        j = latest_read_msg
        while j > 0 and messages[j].get("role") == "tool":
            j -= 1
        if _message_has_tool_use(messages[j]):
            protect_at = min(protect_at, j)
        else:
            protect_at = min(protect_at, latest_read_msg)
    return max(0, protect_at)


def _middle_truncate_text(text: str, limit: int) -> str:
    """超长 tool_result 中间截断，保留 head/tail（X-2 budget_truncated 标记）。"""
    if limit <= 0 or len(text) <= limit:
        return text
    marker = "\n...[budget_truncated]...\n"
    keep = (limit - len(marker)) // 2
    if keep < 64:
        return text[: max(0, limit - len("\n...[budget_truncated]"))] + "\n...[budget_truncated]"
    return text[:keep] + marker + text[-keep:]


def _apply_tool_result_budget(
    messages: list[dict[str, Any]],
    char_budget: int | None = None,
    *,
    preserve_short: bool = False,
    latest_read_budget: int | None = None,
) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    """按字符预算截断 oversized tool_result 正文。

    最新 read_file 可使用更大 ``latest_read_budget``；pinned 短结果与
    writing_section_extract 章节不截断。

    参数:
        messages: 对话历史。
        char_budget: 覆盖默认字符上限；None 用 settings。
        preserve_short: True 时跳过 pinned 短 JSON。
        latest_read_budget: 覆盖最新 read 的字符上限。

    返回:
        ``(messages, truncated_count, truncated_by_tool)``，后者供 C3 审计。
    """
    default_budget, read_budget, _ = _budget_limits()
    if char_budget is not None:
        default_budget = int(char_budget)
    if latest_read_budget is not None:
        read_budget = int(latest_read_budget)

    latest_ids = _latest_read_file_tool_use_ids(messages)
    name_by_id = _tool_use_name_by_id(messages)
    out: list[dict[str, Any]] = []
    truncated = 0
    truncated_by_tool: dict[str, int] = {}
    for msg in messages:
        if msg.get("role") != "tool":
            out.append(msg)
            continue
        content = msg.get("content", [])
        new_blocks = []
        for block in content:
            if block.get("type") != "tool_result":
                new_blocks.append(block)
                continue
            text = str(block.get("content", ""))
            if preserve_short and _is_pinned_short_tool_result(text):
                new_blocks.append(block)
                continue
            if _preserve_writing_section_extract(text):
                # docs/24: chapter extracts stay intact; do not budget-truncate mid-chapter.
                new_blocks.append(block)
                continue
            tid = str(block.get("tool_use_id") or "")
            limit = (
                read_budget
                if tid in latest_ids and name_by_id.get(tid) == "read_file"
                else default_budget
            )
            if len(text) > limit:
                text = _middle_truncate_text(text, limit)
                truncated += 1
                tool_name = name_by_id.get(tid) or "unknown"
                truncated_by_tool[tool_name] = truncated_by_tool.get(tool_name, 0) + 1
            new_blocks.append({**block, "content": text})
        out.append({**msg, "content": new_blocks})
    return out, truncated, truncated_by_tool


def _preserve_writing_section_extract(text: str) -> bool:
    """docs/24：章节 extract 标记的结果不参与 budget 截断。"""
    return (
        '"writing_section_extract": true' in text
        or '"writing_section_extract":true' in text
    )


def _tool_use_name_by_id(messages: list[dict[str, Any]]) -> dict[str, str]:
    """扫描 assistant 消息，建立 tool_use id → 工具名映射。"""
    mapping: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []) or []:
            if block.get("type") != "tool_use":
                continue
            tid = str(block.get("id") or "")
            name = str(block.get("name") or "")
            if tid and name:
                mapping[tid] = name
    return mapping


def _read_paths_in_messages(messages: list[dict[str, Any]]) -> set[str]:
    """收集仍含真实 read_file 正文（未 _folded_read）的规范化路径集合。"""
    from app.engine.read_registry import normalize_read_path

    name_by_id = _tool_use_name_by_id(messages)
    paths: set[str] = set()
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        for block in msg.get("content", []) or []:
            if block.get("type") != "tool_result":
                continue
            tid = str(block.get("tool_use_id") or "")
            if name_by_id.get(tid) != "read_file":
                continue
            text = str(block.get("content") or "")
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or data.get("_folded_read"):
                continue
            content = data.get("content")
            if not isinstance(content, str) or len(content) < 80:
                continue
            path = normalize_read_path(str(data.get("path") or ""))
            if path:
                paths.add(path)
    return paths


def _read_paths_missing_after(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> set[str]:
    """压缩前后 diff：哪些 read 路径的正文离开了可见窗口（供 C1 evicted_paths）。"""
    return _read_paths_in_messages(before) - _read_paths_in_messages(after)


def _fold_stale_read_file_results(
    messages: list[dict[str, Any]],
    *,
    keep_last_per_path: int = 1,
    min_content_chars: int = 400,
) -> tuple[list[dict[str, Any]], int, set[str]]:
    """docs/34 RC4：每路径仅保留最新 read_file 完整正文，旧读折叠为 stub。

    参数:
        messages: 对话历史。
        keep_last_per_path: 每路径保留完整 body 的条数（默认 1）。
        min_content_chars: 低于此长度的 read 不参与折叠。

    返回:
        ``(messages, folded_count, folded_paths)``；folded_paths 写入 TurnState.evicted_paths。
    """
    from app.engine.read_registry import normalize_read_path, omit_read_file_content_payload

    name_by_id = _tool_use_name_by_id(messages)
    # (msg_index, block_index, path)
    candidates: list[tuple[int, int, str]] = []
    for mi, msg in enumerate(messages):
        if msg.get("role") != "tool":
            continue
        for bi, block in enumerate(msg.get("content", []) or []):
            if block.get("type") != "tool_result":
                continue
            tid = str(block.get("tool_use_id") or "")
            if name_by_id.get(tid) != "read_file":
                continue
            text = str(block.get("content") or "")
            if len(text) < min_content_chars:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            if data.get("error") or data.get("_folded_read") or data.get("writing_section_extract"):
                continue
            content = data.get("content")
            if not isinstance(content, str) or len(content) < min_content_chars:
                continue
            path = normalize_read_path(str(data.get("path") or "")) or f"__anon_{tid}"
            candidates.append((mi, bi, path))

    if not candidates:
        return messages, 0, set()

    by_path: dict[str, list[tuple[int, int]]] = {}
    for mi, bi, path in candidates:
        by_path.setdefault(path, []).append((mi, bi))

    fold_keys: set[tuple[int, int]] = set()
    folded_paths: set[str] = set()
    keep = max(1, int(keep_last_per_path))
    for path, items in by_path.items():
        for mi, bi in items[:-keep]:
            fold_keys.add((mi, bi))
            if not path.startswith("__anon_"):
                folded_paths.add(path)

    if not fold_keys:
        return messages, 0, set()

    out: list[dict[str, Any]] = []
    folded = 0
    for mi, msg in enumerate(messages):
        if msg.get("role") != "tool":
            out.append(msg)
            continue
        content = msg.get("content", [])
        new_blocks: list[dict[str, Any]] = []
        changed = False
        for bi, block in enumerate(content or []):
            if (mi, bi) not in fold_keys:
                new_blocks.append(block)
                continue
            text = str(block.get("content") or "")
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                new_blocks.append(block)
                continue
            if not isinstance(data, dict):
                new_blocks.append(block)
                continue
            slim = omit_read_file_content_payload(data)
            new_blocks.append({**block, "content": json.dumps(slim, ensure_ascii=False)})
            folded += 1
            changed = True
        out.append({**msg, "content": new_blocks} if changed else msg)
    return out, folded, folded_paths


def _message_has_tool_use(msg: dict[str, Any]) -> bool:
    """assistant 消息是否含至少一个 tool_use block。"""
    return msg.get("role") == "assistant" and any(
        block.get("type") == "tool_use" for block in msg.get("content", [])
    )


def _microcompact_tool_results(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """将连续多条 tool 消息折叠为一条 microcompact 指针（保留 assistant/tool 配对）。

    紧接 assistant tool_use 之后的 tool 运行不折叠——OpenAI 兼容 provider 要求
    每个 tool_call_id 有对应 tool 消息。
    """
    if len(messages) < 3:
        return messages, 0
    out: list[dict[str, Any]] = []
    folded = 0
    index = 0
    while index < len(messages):
        msg = messages[index]
        prev = out[-1] if out else None
        if msg.get("role") == "tool" and prev is not None and _message_has_tool_use(prev):
            while index < len(messages) and messages[index].get("role") == "tool":
                out.append(messages[index])
                index += 1
            continue
        if msg.get("role") != "tool":
            out.append(msg)
            index += 1
            continue
        run = [msg]
        next_index = index + 1
        while next_index < len(messages) and messages[next_index].get("role") == "tool":
            run.append(messages[next_index])
            next_index += 1
        if len(run) >= 2:
            bodies = [_tool_result_text(m) for m in run]
            if bodies and all(_is_pinned_short_tool_result(b) for b in bodies):
                out.extend(run)
            else:
                folded += len(run) - 1
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"[microcompact: folded {len(run)} tool results; "
                                    "re-read with tools if needed]"
                                ),
                            }
                        ],
                    }
                )
        else:
            out.append(msg)
        index = next_index
    return out, folded


def _pop_oldest_message_group(
    messages: list[dict[str, Any]],
    *,
    protect_from: int | None = None,
) -> bool:
    """丢弃最旧一组连贯消息，避免 orphan tool 消息。

    ``protect_from`` 为 C-1 snip 下界时，仅允许删除 ``messages[:protect_from]`` 内的组。

    参数:
        messages: 原地修改的列表。
        protect_from: 受保护尾部起始下标；None 表示无保护。

    返回:
        是否成功删除一组。
    """
    limit = len(messages) if protect_from is None else max(0, min(protect_from, len(messages)))
    if limit <= 0:
        return False

    # Trim leading orphan tool messages only inside the unprotected prefix.
    while messages and messages[0].get("role") == "tool":
        if protect_from is not None and protect_from <= 0:
            return False
        messages.pop(0)
        if protect_from is not None:
            protect_from -= 1
            limit = max(0, min(protect_from, len(messages)))
            if limit <= 0:
                return False

    if len(messages) <= 1 or limit <= 1:
        return False

    if messages[0].get("role") == "assistant" and _message_has_tool_use(messages[0]):
        end = 1
        while end < len(messages) and messages[end].get("role") == "tool":
            end += 1
        if end >= len(messages) or end > limit:
            return False
        del messages[0:end]
        return True
    if messages[0].get("role") == "user":
        end = 1
        while end < len(messages) and messages[end].get("role") != "user":
            end += 1
        if end >= len(messages) or end > limit:
            return False
        del messages[0:end]
        return True
    if limit < 1:
        return False
    messages.pop(0)
    return True


def _align_tail_start(messages: list[dict[str, Any]], tail_start: int) -> int:
    """回退 tail 起点，避免从 tool 结果 run 中间切开。"""
    index = max(0, min(tail_start, len(messages) - 1))
    while index > 0 and messages[index].get("role") == "tool":
        index -= 1
    if index >= 0 and _message_has_tool_use(messages[index]):
        return index
    return max(1, tail_start)


def _tail_start_for_token_budget(messages: list[dict[str, Any]], hot_budget: int) -> int:
    """从尾部向前累计 token 直到 hot_budget，得到 collapse 热区起点。"""
    total = 0
    index = len(messages)
    while index > 0 and total < hot_budget:
        index -= 1
        total += _estimate_tokens([messages[index]])
    return _align_tail_start(messages, index)


def _collapse_tool_history(
    messages: list[dict[str, Any]],
    trace: list[dict[str, str]],
    *,
    system_prompt: str,
    tools: list[dict[str, Any]] | None,
    policy: CompactionPolicy,
    volatile_context: str = "",
) -> list[dict[str, Any]]:
    """将较旧中间段折叠为单条 pointer user 消息，保留 head + 热区 tail。

    不破坏 assistant/tool 配对；受 ``_protected_tail_start`` 约束不折叠当前指令周期。
    """
    fill_ratio, window = _window_fill(
        messages=messages,
        system_prompt=system_prompt,
        tools=tools,
        policy=policy,
        volatile_context=volatile_context,
    )
    if fill_ratio < policy.fill_collapse or len(messages) <= 4:
        return messages

    working = max(
        1,
        policy.model_window_tokens
        - policy.output_reserve_tokens
        - window["system_tokens"]
        - window["tools_tokens"],
    )
    hot_budget = max(1, int(working * policy.hot_zone_ratio))
    tail_start = _tail_start_for_token_budget(messages, hot_budget)
    # C-1: never collapse away the current instruction / latest read cycle.
    protect = _protected_tail_start(messages)
    if protect > 0:
        tail_start = min(tail_start, protect)
    head = messages[:1] if messages and messages[0].get("role") == "user" else []
    middle = messages[len(head) : tail_start]
    tail = messages[tail_start:]
    if len(head) + len(tail) >= len(messages) or not middle:
        return messages
    collapsed = len(messages) - len(head) - len(tail)
    trace.append({"strategy": "collapse", "detail": f"collapsed_{collapsed}_messages"})
    dropped = _dropped_tools_summary(middle)
    pinned = _pinned_tool_digest(middle)
    parts = [f"[collapsed {collapsed} earlier messages"]
    if dropped:
        parts.append(f"; {dropped}")
    parts.append("; recent context preserved]")
    pointer_text = "".join(parts)
    if pinned:
        pointer_text = f"{pointer_text} {pinned}"
    pointer = {
        "role": "user",
        "content": [{"type": "text", "text": pointer_text}],
    }
    return [*head, pointer, *tail]


def _summarize_messages(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """确定性 autocompact：结构化摘要合并为单条 user 消息（HM3 增量 merge）。

    参数:
        messages: 待压缩历史。

    返回:
        含 ``[autocompact]`` 正文的 user message dict。
    """
    from app.context.summary import incremental_summary_from_messages
    from app.settings import settings

    summary = incremental_summary_from_messages(messages)
    if settings.context_layered_summary_enabled and len(summary.narrative) > 600:
        # HM8: fold current summary into L1 layer when narrative is long (default off).
        layer = {
            "level": 1,
            "summary": {
                "task": summary.task[:200],
                "narrative": summary.narrative[:400],
                "files_touched": summary.files_touched[:8],
            },
        }
        summary.layers = [*summary.layers[-2:], layer]
        summary.narrative = summary.narrative[:400]
    if not summary.narrative:
        summary.narrative = f"{len(messages)} earlier messages compacted"
    return {
        "role": "user",
        "content": [{"type": "text", "text": summary.to_autocompact_text()}],
    }
