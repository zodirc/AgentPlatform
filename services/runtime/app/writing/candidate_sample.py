"""作品候选：独立采样 ×2 → title+pitch 卡片。无 selector / renderer。"""

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
from app.writing.subject_pool import draw_subjects
from app.writing.work_reconstruction import (
    CANDIDATE_SCHEMA,
    candidate_fingerprint,
    form_messages,
    genre_label,
    genre_of,
    obvious_meta_text,
    parse_card,
    topic_of,
)

logger = logging.getLogger(__name__)

CompleteFn = Callable[[list[dict[str, Any]]], Awaitable[str]]

_SAMPLE_POOL = 2
_SLOT_RETRIES = 1
_THINKING_DELTA_MAX = 8192
_FORM_MAX_OUTPUT_TOKENS = 1024
_FORM_THINK_CHAR_BUDGET = 4000
_sample_turn_id: ContextVar[object | None] = ContextVar(
    "candidate_sample_turn_id", default=None
)
_think_emit_lock = asyncio.Lock()

_genre_label = genre_label
_topic_of = topic_of


@dataclass
class CompleteResult:
    text: str
    reasoning: str = ""
    output_tokens: int = 0
    think_chars: int = 0
    aborted: bool = False


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
    return replace(
        _isolated_generation(_FORM_MAX_OUTPUT_TOKENS),
        response_schema=CANDIDATE_SCHEMA,
    )


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
                "output_tokens_form": output_tokens_form,
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
    async with _think_emit_lock:
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


def _text_from_tool_calls(calls: list[dict[str, Any]] | None) -> str:
    for call in calls or []:
        if not isinstance(call, dict):
            continue
        payload = call.get("input")
        if payload is None:
            raw_args = call.get("arguments")
            if isinstance(raw_args, str) and raw_args.strip():
                try:
                    payload = json.loads(raw_args)
                except json.JSONDecodeError:
                    return raw_args.strip()
            elif isinstance(raw_args, dict):
                payload = raw_args
        if isinstance(payload, dict):
            return json.dumps(payload, ensure_ascii=False)
        if isinstance(payload, str) and payload.strip():
            return payload.strip()
    return ""


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
            blob = _text_from_tool_calls(chunk.tool_calls)
            if blob:
                collected = blob
            elif chunk.text and not collected:
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


def _card_payload(
    *,
    sample_id: str,
    raw: str,
    parsed: dict[str, str],
) -> dict[str, Any]:
    pitch = parsed["pitch"]
    return {
        "id": sample_id,
        "sample_id": sample_id,
        "raw": raw,
        "title": parsed["title"],
        "flavor": parsed.get("flavor") or "",
        "opening": pitch,
        "pitch": pitch,
        "work": pitch,
    }


def _is_excluded(
    parsed: dict[str, str],
    *,
    exclude_ids: set[str],
    exclude_fingerprints: set[str],
    exclude_titles: set[str],
    sample_id: str,
) -> bool:
    # c01/c02 是采样槽位名，不是作品身份。旧池把槽位写进 id 时不得把新采样整槽扔掉。
    _ = (exclude_ids, sample_id)
    title = str(parsed.get("title") or "").strip().casefold()
    if title and title in exclude_titles:
        return True
    fps = {
        candidate_fingerprint(parsed.get("pitch") or ""),
        candidate_fingerprint(parsed.get("title") or "", parsed.get("pitch") or ""),
    }
    return bool(fps & exclude_fingerprints)


async def sample_one_candidate(
    user_text: str,
    *,
    complete: CompleteFn | None = None,
    sample_id: str = "c01",
    subject: str = "",
    exclude_ids: set[str] | None = None,
    exclude_fingerprints: set[str] | None = None,
    exclude_titles: set[str] | None = None,
) -> dict[str, Any] | None:
    """一个 sample job：题材已经抽定，只交这本书的 {title, pitch}。格式失败或撞车后再交一次。"""
    await _emit_thinking_delta("\n—— 独立采样 ——\n")
    last_raw = ""
    for _attempt in range(_SLOT_RETRIES + 1):
        formed = await _run_complete(
            form_messages(user_text, subject=subject),
            complete=complete,
            generation=form_generation(),
            think_char_budget=_FORM_THINK_CHAR_BUDGET,
        )
        last_raw = formed.text.strip()
        if formed.aborted and not last_raw:
            _log_candidate_trace(
                sample_id=sample_id,
                aborted=True,
                think_chars_form=formed.think_chars,
                output_tokens_form=formed.output_tokens,
            )
            return None
        parsed = parse_card(last_raw)
        if parsed is not None and obvious_meta_text(parsed["pitch"]):
            parsed = None
        if parsed is None:
            _log_candidate_trace(
                sample_id=sample_id,
                sample_raw=last_raw,
                think_chars_form=formed.think_chars,
                output_tokens_form=formed.output_tokens,
                aborted=formed.aborted,
            )
            continue
        if _is_excluded(
            parsed,
            exclude_ids=exclude_ids or set(),
            exclude_fingerprints=exclude_fingerprints or set(),
            exclude_titles=exclude_titles or set(),
            sample_id=sample_id,
        ):
            logger.info("candidate excluded id=%s title=%s", sample_id, parsed["title"])
            continue
        card = _card_payload(sample_id=sample_id, raw=last_raw, parsed=parsed)
        _log_candidate_trace(
            sample_id=sample_id,
            sample_raw=last_raw,
            work=card["pitch"],
            selected=True,
            title=card["title"],
            opening=card["pitch"],
            think_chars_form=formed.think_chars,
            output_tokens_form=formed.output_tokens,
        )
        return card
    logger.info("candidate schema miss id=%s", sample_id)
    return None


async def sample_independent_pair(
    user_text: str,
    *,
    held: list[dict[str, Any]] | None = None,
    complete: CompleteFn | None = None,
    gate: bool = True,
    need: int | None = None,
    turn_id: object | None = None,
    exclude_ids: set[str] | None = None,
    exclude_fingerprints: set[str] | None = None,
    exclude_titles: set[str] | None = None,
) -> list[dict[str, Any]]:
    """从该类型已有的题材池里无放回均匀抽两本。两张卡互不可见。无第三槽。"""

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
            exclude_ids=set(exclude_ids or ()),
            exclude_fingerprints=set(exclude_fingerprints or ()),
            exclude_titles=set(exclude_titles or ()),
        )
    finally:
        if buffered is not None:
            await buffered.stop_stream_liveness()
        _sample_turn_id.reset(token)


async def resolve_sample_user_text(user_text: str, session_id: Any = None) -> str:
    """本句是「我看看 / 我要其他的」时，类型仍用本会话里已经点过名的那一句。"""
    from app.writing.work_reconstruction import names_genre, sample_user_text

    if names_genre(user_text):
        return user_text
    priors: list[str] = []
    if session_id:
        try:
            sid = session_id if isinstance(session_id, UUID) else UUID(str(session_id))
            from app.controller.session_compact import load_session_turn_history

            rows = await load_session_turn_history(sid, limit=20)
            priors = [str(row.get("user_input") or "") for row in rows]
        except (TypeError, ValueError):
            priors = []
        except Exception:
            logger.debug("sample genre history failed", exc_info=True)
    return sample_user_text(user_text, priors)


async def _sample_independent_pair_body(
    user_text: str,
    *,
    complete: CompleteFn | None,
    need: int | None,
    exclude_ids: set[str],
    exclude_fingerprints: set[str],
    exclude_titles: set[str],
) -> list[dict[str, Any]]:
    _ = need
    chosen = draw_subjects(genre_of(user_text), _SAMPLE_POOL)
    if len(chosen) < _SAMPLE_POOL:
        return []
    await _emit_thinking_delta("\n—— 题材池 ——\n")
    sampled = await asyncio.gather(
        sample_one_candidate(
            user_text,
            complete=complete,
            sample_id="c01",
            subject=chosen[0],
            exclude_ids=exclude_ids,
            exclude_fingerprints=exclude_fingerprints,
            exclude_titles=exclude_titles,
        ),
        sample_one_candidate(
            user_text,
            complete=complete,
            sample_id="c02",
            subject=chosen[1],
            exclude_ids=exclude_ids,
            exclude_fingerprints=exclude_fingerprints,
            exclude_titles=exclude_titles,
        ),
    )
    seen_fps = set(exclude_fingerprints)
    seen_titles = set(exclude_titles)
    cards: list[dict[str, Any]] = []
    for card in sampled:
        if card is None:
            continue
        fp = candidate_fingerprint(card.get("pitch") or "")
        title = str(card.get("title") or "").strip().casefold()
        if fp and fp in seen_fps:
            continue
        if title and title in seen_titles:
            continue
        if fp:
            seen_fps.add(fp)
        if title:
            seen_titles.add(title)
        cards.append(card)
    return cards[:_SAMPLE_POOL]
