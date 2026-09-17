"""作品候选：独立采样 ×2 → 冻结 → 判尺 → 渲染卡片。"""

from __future__ import annotations

import asyncio
import json
import logging
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable
from uuid import UUID

from app.model.gateway import ModelResponse, StreamActivity
from app.model.generation import GenerationParams
from app.writing.work_reconstruction import (
    form_messages,
    freeze_work,
    genre_label,
    parse_card,
    parse_selector_ids,
    parse_work,
    render_messages,
    selector_messages,
    topic_of,
)

logger = logging.getLogger(__name__)

CompleteFn = Callable[[list[dict[str, Any]]], Awaitable[str]]

_SAMPLE_POOL = 2
_THINKING_DELTA_MAX = 8192
_FORM_MAX_OUTPUT_TOKENS = 4096
_FORM_THINK_CHAR_BUDGET = 8000
_SELECT_MAX_OUTPUT_TOKENS = 512
_SELECT_THINK_CHAR_BUDGET = 4000
_RENDER_MAX_OUTPUT_TOKENS = 1200
_RENDER_THINK_CHAR_BUDGET = 2500
_RENDER_OUT_MAX = 1200
_sample_turn_id: ContextVar[object | None] = ContextVar(
    "candidate_sample_turn_id", default=None
)

_genre_label = genre_label
_topic_of = topic_of
pitch_messages = render_messages


@dataclass
class CompleteResult:
    text: str
    reasoning: str = ""
    output_tokens: int = 0
    think_chars: int = 0
    aborted: bool = False


@dataclass
class WorkSample:
    sample_id: str
    sample_raw: str
    work: str
    think_chars: int = 0
    output_tokens: int = 0
    aborted: bool = False
    selected: bool = False


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


def _clip_draft(text: str, limit: int) -> str:
    body = (text or "").strip()
    if len(body) <= limit:
        return body
    return body[:limit].rstrip()


def _isolated_generation(max_output_tokens: int) -> GenerationParams:
    """候选 child 不继承 writing 场景温度/system，也不开内部搜索。"""
    base = GenerationParams.from_settings(scenario_id=None)
    return replace(
        base,
        max_output_tokens=max_output_tokens,
        tool_choice="none",
        thinking_enabled=False,
        reasoning_effort="none",
    )


def form_generation() -> GenerationParams:
    return _isolated_generation(_FORM_MAX_OUTPUT_TOKENS)


def selector_generation() -> GenerationParams:
    return _isolated_generation(_SELECT_MAX_OUTPUT_TOKENS)


def render_generation() -> GenerationParams:
    return _isolated_generation(_RENDER_MAX_OUTPUT_TOKENS)


def pitch_generation() -> GenerationParams:
    return render_generation()


def candidate_generation() -> GenerationParams:
    return form_generation()


def _log_candidate_trace(
    *,
    sample_id: str = "",
    sample_raw: str = "",
    work: str = "",
    selected: bool = False,
    title: str = "",
    flavor: str = "",
    opening: str = "",
    think_chars_form: int = 0,
    think_chars_render: int = 0,
    output_tokens_form: int = 0,
    output_tokens_render: int = 0,
    aborted: bool = False,
) -> None:
    logger.info(
        "candidate_trace %s",
        json.dumps(
            {
                "sample_id": sample_id,
                "sample_raw": sample_raw,
                "pitch_raw": work,
                "work": work,
                "selected": selected,
                "title": title,
                "flavor": flavor,
                "opening": opening,
                "think_chars_form": think_chars_form,
                "think_chars_render": think_chars_render,
                "output_tokens_form": output_tokens_form,
                "output_tokens_render": output_tokens_render,
                "aborted": aborted,
            },
            ensure_ascii=False,
        ),
    )


async def _emit_thinking_delta(text: str) -> None:
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


async def consume_complete(
    stream: Any,
    *,
    abort: Callable[[], None] | None = None,
    think_char_budget: int = _FORM_THINK_CHAR_BUDGET,
) -> CompleteResult:
    collected = ""
    reasoning_parts: list[str] = []
    think_chars = 0
    aborted = False
    output_tokens = 0
    async for chunk in stream:
        if isinstance(chunk, StreamActivity):
            if chunk.kind == "reasoning" and chunk.text:
                piece = str(chunk.text)
                if think_chars < think_char_budget:
                    reasoning_parts.append(piece)
                    think_chars += len(piece)
                    await _emit_thinking_delta(piece)
                if (
                    think_chars >= think_char_budget
                    and not collected
                    and abort is not None
                    and not aborted
                ):
                    aborted = True
                    abort()
                    break
            continue
        if isinstance(chunk, str):
            collected += chunk
        elif isinstance(chunk, ModelResponse):
            if chunk.text and not collected:
                collected = chunk.text
            if chunk.output_tokens:
                output_tokens = int(chunk.output_tokens)
    return CompleteResult(
        text=collected.strip(),
        reasoning="".join(reasoning_parts).strip(),
        output_tokens=output_tokens,
        think_chars=think_chars,
        aborted=aborted,
    )


async def collect_complete_text(stream: Any) -> str:
    return (await consume_complete(stream)).text


async def _gateway_complete(
    messages: list[dict[str, Any]],
    *,
    generation: GenerationParams,
    think_char_budget: int,
) -> CompleteResult:
    from app.model.config import resolve_model_config
    from app.model.factory import create_gateway
    from app.tenant_context import current_owner_user_id

    owner = current_owner_user_id()
    config = await resolve_model_config(owner_user_id=owner)
    gateway = create_gateway(
        config,
        messages=messages,
        scenario_id=None,
        generation=generation,
    )
    try:
        return await consume_complete(
            gateway.stream(messages=messages, tools=[]),
            abort=gateway.abort_stream,
            think_char_budget=think_char_budget,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("candidate sample complete failed")
        return CompleteResult(text="")


async def _run_complete(
    messages: list[dict[str, Any]],
    *,
    complete: CompleteFn | None,
    generation: GenerationParams,
    think_char_budget: int,
) -> CompleteResult:
    if complete is not None:
        return CompleteResult(text=(await complete(messages)).strip())
    return await _gateway_complete(
        messages,
        generation=generation,
        think_char_budget=think_char_budget,
    )


def _rendered_card(sample: WorkSample, parsed: dict[str, str]) -> dict[str, Any]:
    opening = parsed["opening"]
    return {
        "id": sample.sample_id,
        "title": parsed["title"],
        "flavor": parsed.get("flavor") or "",
        "opening": opening,
        "pitch": opening,
        "work": sample.work,
    }


async def form_one_work(
    user_text: str,
    *,
    complete: CompleteFn | None = None,
    sample_id: str = "",
) -> WorkSample | None:
    await _emit_thinking_delta("\n—— 独立采样 ——\n")
    formed = await _run_complete(
        form_messages(user_text),
        complete=complete,
        generation=form_generation(),
        think_char_budget=_FORM_THINK_CHAR_BUDGET,
    )
    sample_raw = formed.reasoning or formed.text
    if formed.aborted and not formed.text:
        _log_candidate_trace(
            sample_id=sample_id,
            sample_raw=sample_raw,
            aborted=True,
            think_chars_form=formed.think_chars,
            output_tokens_form=formed.output_tokens,
        )
        return None
    work = parse_work(formed.text)
    if work is None:
        _log_candidate_trace(
            sample_id=sample_id,
            sample_raw=sample_raw,
            think_chars_form=formed.think_chars,
            output_tokens_form=formed.output_tokens,
            aborted=formed.aborted,
        )
        logger.info("candidate work discarded id=%s", sample_id)
        return None
    sample = WorkSample(
        sample_id=sample_id,
        sample_raw=sample_raw,
        work=freeze_work(work),
        think_chars=formed.think_chars,
        output_tokens=formed.output_tokens,
        aborted=formed.aborted,
    )
    _log_candidate_trace(
        sample_id=sample.sample_id,
        sample_raw=sample.sample_raw,
        work=sample.work,
        selected=False,
        think_chars_form=sample.think_chars,
        output_tokens_form=sample.output_tokens,
        aborted=sample.aborted,
    )
    return sample


async def render_card(
    sample: WorkSample,
    *,
    complete: CompleteFn | None = None,
) -> dict[str, str] | None:
    rendered = await _run_complete(
        render_messages(sample.work),
        complete=complete,
        generation=render_generation(),
        think_char_budget=_RENDER_THINK_CHAR_BUDGET,
    )
    if rendered.aborted and not rendered.text:
        logger.info("candidate render aborted at think budget chars=%s", rendered.think_chars)
        return None
    return parse_card(_clip_draft(rendered.text, _RENDER_OUT_MAX))


async def _select_ids(
    pool: list[WorkSample],
    *,
    complete: CompleteFn | None,
) -> list[str]:
    if len(pool) < 2:
        return [it.sample_id for it in pool]
    raw = await _run_complete(
        selector_messages([(it.sample_id, it.work) for it in pool]),
        complete=complete,
        generation=selector_generation(),
        think_char_budget=_SELECT_THINK_CHAR_BUDGET,
    )
    if raw.aborted and not raw.text:
        logger.info("candidate selector aborted at think budget chars=%s", raw.think_chars)
        return []
    return parse_selector_ids(raw.text, [it.sample_id for it in pool])


async def sample_one_candidate(
    user_text: str,
    *,
    complete: CompleteFn | None = None,
) -> dict[str, Any] | None:
    """单样本：只形成并冻结一稿。"""
    sample = await form_one_work(
        user_text,
        complete=complete,
        sample_id="c01",
    )
    if sample is None:
        return None
    return {
        "id": sample.sample_id,
        "title": sample.sample_id,
        "work": sample.work,
        "opening": sample.work,
    }


async def sample_independent_pair(
    user_text: str,
    *,
    held: list[dict[str, Any]] | None = None,
    complete: CompleteFn | None = None,
    gate: bool = True,
    need: int | None = None,
    turn_id: object | None = None,
) -> list[dict[str, Any]]:
    """同一个极简 prompt 各采一稿，冻结后由判尺选 2，再渲染卡片。旧卡不进 child。"""

    _ = (held, gate)
    token = _sample_turn_id.set(turn_id)
    buffered = _buffered_writer()
    if buffered is not None:
        buffered.start_stream_liveness(0)
    await _mark_candidate_thinking()
    try:
        return await _sample_independent_pair_body(
            user_text,
            complete=complete,
            need=need,
        )
    finally:
        if buffered is not None:
            await buffered.stop_stream_liveness()
        _sample_turn_id.reset(token)


async def _sample_independent_pair_body(
    user_text: str,
    *,
    complete: CompleteFn | None,
    need: int | None,
) -> list[dict[str, Any]]:
    target = _SAMPLE_POOL if need is None else max(0, need)
    pool: list[WorkSample] = []
    misses = 0
    while len(pool) < target and misses < target + 4:
        sample_id = f"c{len(pool) + 1:02d}"
        sample = await form_one_work(
            user_text,
            complete=complete,
            sample_id=sample_id,
        )
        if sample is None:
            misses += 1
            continue
        pool.append(sample)
    picks = await _select_ids(pool, complete=complete)
    if len(picks) < min(2, len(pool)):
        picks = [it.sample_id for it in pool[:2]]
    chosen: list[WorkSample] = []
    by_id = {it.sample_id: it for it in pool}
    for sid in picks:
        if sid in by_id and by_id[sid] not in chosen:
            chosen.append(by_id[sid])
        if len(chosen) == 2:
            break
    picked = {it.sample_id for it in chosen}
    for sample in pool:
        sample.selected = sample.sample_id in picked
        _log_candidate_trace(
            sample_id=sample.sample_id,
            sample_raw=sample.sample_raw,
            work=sample.work,
            selected=sample.selected,
        )
    cards: list[dict[str, Any]] = []
    for sample in chosen:
        parsed = await render_card(sample, complete=complete)
        if parsed is None:
            parsed = {
                "title": sample.sample_id,
                "flavor": "",
                "opening": sample.work,
            }
        _log_candidate_trace(
            sample_id=sample.sample_id,
            sample_raw=sample.sample_raw,
            work=sample.work,
            selected=True,
            title=parsed["title"],
            flavor=parsed.get("flavor") or "",
            opening=parsed["opening"],
        )
        cards.append(_rendered_card(sample, parsed))
    return cards
