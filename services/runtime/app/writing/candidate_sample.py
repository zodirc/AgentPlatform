"""作品候选内部采样：两次独立 form→compress，B 看不到 A。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from contextvars import ContextVar
from typing import Any, Awaitable, Callable
from uuid import UUID

from app.engine.state import user_message
from app.model.gateway import ModelResponse, StreamActivity
from app.writing.opening_ponds import candidate_mode_block

logger = logging.getLogger(__name__)

CompleteFn = Callable[[list[dict[str, Any]]], Awaitable[str]]

_INTERNAL_SLOT_TRIES = 2
_SEED_MAX = 1600
_THINKING_DELTA_MAX = 8192
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_sample_turn_id: ContextVar[object | None] = ContextVar(
    "candidate_sample_turn_id", default=None
)

_FORM_USER = """用户要写：{user_text}

如果这是你接下来真正要连载的一本书，它到底是什么？

用一段话写下这本书。不要写书名，不要写简介，不要写第一章。
不要对照另一本书。这一次只形成这一本。"""

_COMPRESS_USER = """下面是已经形成的一本书：

{work_seed}

现在把这本已经形成的书压成书名和书页简介。

title：2–8字。可以不出现在 pitch 中。
pitch：100–220字。pitch 是这本书的入口，不是构思过程，也不是第一章。

不要解释作品为什么成立。不要自我评价。不要总结整个后续剧情。

只交 JSON 对象：{{"title": "...", "pitch": "..."}}"""


def _content_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
    return "\n".join(parts)


def form_messages(user_text: str) -> list[dict[str, Any]]:
    """只含候选模式 + 用户题材。没有正文原则，也没有另一本候选。"""
    request = (user_text or "").strip() or "写一篇长篇都市修真小说"
    body = (
        f"{candidate_mode_block()}\n\n---\n\n"
        f"{_FORM_USER.format(user_text=request)}"
    )
    return [user_message(body)]


def compress_messages(work_seed: str) -> list[dict[str, Any]]:
    seed = (work_seed or "").strip()[:_SEED_MAX]
    return [user_message(_COMPRESS_USER.format(work_seed=seed))]


def parse_title_pitch(raw: str) -> dict[str, str] | None:
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
        if not isinstance(data, dict):
            continue
        title = str(data.get("title") or "").strip()
        pitch = str(data.get("pitch") or data.get("opening") or "").strip()
        if title and pitch:
            return {"title": title, "pitch": pitch}
    title_m = re.search(r"(?:title|书名)\s*[:：]\s*(.+)", text)
    pitch_m = re.search(r"(?:pitch|简介)\s*[:：]\s*(.+)", text, re.S)
    if title_m and pitch_m:
        title = title_m.group(1).strip().strip("「」\"'").splitlines()[0][:16]
        pitch = pitch_m.group(1).strip()
        if title and pitch:
            return {"title": title, "pitch": pitch}
    return None


async def _emit_thinking_delta(text: str) -> None:
    """把内层 DS 思考链接到当前 Turn 的 thinking UI。"""
    delta = (text or "")[:_THINKING_DELTA_MAX]
    if not delta:
        return
    from app.controller.runtime_context import get_event_writer

    writer = get_event_writer()
    if writer is None:
        return
    try:
        await writer(
            event_type="turn.thinking.delta",
            payload={"delta": delta, "step_index": 0},
            step_index=0,
        )
    except Exception:
        logger.debug("candidate thinking emit failed", exc_info=True)


async def _mark_candidate_thinking() -> None:
    from app.controller.runtime_context import get_event_writer

    writer = get_event_writer()
    if writer is None:
        return
    try:
        await writer(
            event_type="turn.thinking",
            payload={"step_index": 0, "label": "candidate-sample"},
            step_index=0,
        )
    except Exception:
        logger.debug("candidate thinking mark failed", exc_info=True)


def _buffered_writer():
    from app.controller.event_writer import get_event_writer as get_buffered

    raw = _sample_turn_id.get()
    if raw is None:
        return None
    try:
        turn_id = raw if isinstance(raw, UUID) else UUID(str(raw))
    except (TypeError, ValueError):
        return None
    return get_buffered(turn_id)


async def collect_complete_text(stream: Any) -> str:
    """消费一次无工具生成：思考链回灌 UI，正文才进 work_seed / pitch。"""
    collected = ""
    async for chunk in stream:
        if isinstance(chunk, StreamActivity):
            if chunk.kind == "reasoning" and chunk.text:
                await _emit_thinking_delta(str(chunk.text))
            continue
        if isinstance(chunk, str):
            collected += chunk
        elif isinstance(chunk, ModelResponse) and chunk.text:
            if not collected:
                collected = chunk.text
    return collected.strip()


async def _gateway_complete(messages: list[dict[str, Any]]) -> str:
    from app.model.config import resolve_model_config
    from app.model.factory import create_gateway
    from app.tenant_context import current_owner_user_id

    owner = current_owner_user_id()
    config = await resolve_model_config(owner_user_id=owner)
    gateway = create_gateway(config, messages=messages, scenario_id="writing")
    try:
        return await collect_complete_text(gateway.stream(messages=messages, tools=[]))
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("candidate sample complete failed")
        return ""


async def sample_one_candidate(
    user_text: str,
    *,
    complete: CompleteFn | None = None,
) -> dict[str, str] | None:
    """一次独立采样：先形成书，再压成 title + pitch。"""
    run = complete or _gateway_complete
    formed = await run(form_messages(user_text))
    seed = (formed or "").strip()
    if not seed:
        return None
    raw = await run(compress_messages(seed))
    parsed = parse_title_pitch(raw)
    if parsed is None:
        logger.info("candidate compress did not yield title+pitch")
        return None
    return parsed


async def _sample_passing_item(
    user_text: str,
    *,
    complete: CompleteFn | None,
    gate: bool,
) -> dict[str, Any] | None:
    from app.writing.excerpt_job import keep_passing_pond_items
    from app.writing.opening_ponds import fill_pond_defaults, normalize_pond_items

    for _ in range(_INTERNAL_SLOT_TRIES):
        raw = await sample_one_candidate(user_text, complete=complete)
        if raw is None:
            continue
        items = fill_pond_defaults(normalize_pond_items([raw]))
        if not items:
            continue
        if not gate:
            return items[0]
        passing, dropped = keep_passing_pond_items(items)
        if dropped:
            code = dropped[0][0] if dropped[0] else ""
            logger.info("candidate sample dropped internally code=%s", code)
        if passing:
            return passing[0]
    return None


async def sample_independent_pair(
    user_text: str,
    *,
    held: list[dict[str, Any]] | None = None,
    complete: CompleteFn | None = None,
    gate: bool = True,
    need: int | None = None,
    turn_id: object | None = None,
) -> list[dict[str, Any]]:
    """两次独立采样（可并行）。失败的那张内部重采，不把失败码喂给模型。"""

    token = _sample_turn_id.set(turn_id)
    buffered = _buffered_writer()
    if buffered is not None:
        buffered.start_stream_liveness(0)
    await _mark_candidate_thinking()
    try:
        return await _sample_independent_pair_body(
            user_text,
            held=held,
            complete=complete,
            gate=gate,
            need=need,
        )
    finally:
        if buffered is not None:
            await buffered.stop_stream_liveness()
        _sample_turn_id.reset(token)


async def _sample_independent_pair_body(
    user_text: str,
    *,
    held: list[dict[str, Any]] | None,
    complete: CompleteFn | None,
    gate: bool,
    need: int | None,
) -> list[dict[str, Any]]:
    from app.writing.opening_ponds import merge_held_pond_items, pick_distinct_pond_pair

    pool = [dict(it) for it in (held or [])]
    slot_need = max(0, 2 - len(pool) if need is None else need)
    if slot_need:
        fresh = await asyncio.gather(
            *[
                _sample_passing_item(user_text, complete=complete, gate=gate)
                for _ in range(slot_need)
            ]
        )
        for item in fresh:
            if item:
                pool = merge_held_pond_items(pool, [item])
    extra = 0
    while extra < 2 and pick_distinct_pond_pair(pool) is None:
        extra += 1
        item = await _sample_passing_item(user_text, complete=complete, gate=gate)
        if item:
            pool = merge_held_pond_items(pool, [item])
    pair = pick_distinct_pond_pair(pool)
    return pair or pool
