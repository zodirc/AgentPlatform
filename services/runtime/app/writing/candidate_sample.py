"""作品候选：并行短方向搜索 → 选二 → 独立成文 → title+pitch 卡片。"""

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
from app.writing.subject_pool import (
    SubjectSeed,
    request_is_long_novel,
    select_seeds,
    serves_urban_pool,
)
from app.writing.work_reconstruction import (
    CANDIDATE_SCHEMA,
    candidate_fingerprint,
    form_messages,
    genre_label,
    obvious_meta_text,
    parse_card,
    topic_of,
)
from app.writing.premise_gate import GATE_SCHEMA, gate_messages, parse_gate_payload
from app.writing.candidate_search import (
    CARD_SELECTION_SCHEMA,
    DIRECTION_SET_SCHEMA,
    RENDER_SCHEMA,
    card_selection_messages,
    direction_set_messages,
    diversify_selected_cards,
    listing_affinity,
    parse_card_selection,
    parse_direction_set,
    render_messages,
)

logger = logging.getLogger(__name__)

CompleteFn = Callable[[list[dict[str, Any]]], Awaitable[str]]
_CANDIDATE_MODEL_ROUTE = ("writing", "book_candidates")

_SAMPLE_POOL = 2
_SEARCH_PASSES = 2
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
    """候选 child 只取写作温度，不继承场景 system，也不开内部搜索。"""
    # 候选需要写作温度；此前误用 agent 温度，两个独立槽很容易落到同一模板。
    base = GenerationParams.from_settings(scenario_id="writing")
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


def gate_generation() -> GenerationParams:
    return replace(
        _isolated_generation(256),
        temperature=0.0,
        response_schema=GATE_SCHEMA,
    )


def direction_generation() -> GenerationParams:
    # 略抬温度，让四个方向更可能离开同一高概率模板。
    return replace(
        _isolated_generation(1400),
        temperature=0.95,
        response_schema=DIRECTION_SET_SCHEMA,
    )


def selection_generation() -> GenerationParams:
    return replace(
        _isolated_generation(128),
        temperature=0.0,
        response_schema=CARD_SELECTION_SCHEMA,
    )


def render_generation() -> GenerationParams:
    # 正例已把分布拉向短简介；再压输出预算，减少滑向第一卷梗概的续写空间。
    return replace(
        _isolated_generation(320),
        temperature=0.7,
        response_schema=RENDER_SCHEMA,
    )


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
    raw = _sample_turn_id.get()
    if raw is None:
        return None
    from app.controller.event_writer import get_event_writer as get_buffered

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
    model_route: tuple[str, str] | None = None,
) -> CompleteResult:
    from app.model.config import resolve_model_config, resolve_routed_model_config
    from app.model.factory import create_gateway
    from app.tenant_context import current_owner_user_id

    owner = current_owner_user_id()
    if model_route is None:
        config = await resolve_model_config(owner_user_id=owner)
    else:
        config = await resolve_routed_model_config(
            owner_user_id=owner,
            scenario_id=model_route[0],
            role=model_route[1],
        )
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
    model_route: tuple[str, str] | None = None,
) -> CompleteResult:
    if complete is not None:
        return CompleteResult(text=(await complete(messages)).strip())
    return await _gateway_complete(
        messages,
        generation=generation,
        think_char_budget=think_char_budget,
        model_route=model_route,
    )


def _card_payload(
    *,
    sample_id: str,
    parsed: dict[str, Any],
) -> dict[str, Any]:
    pitch = parsed["pitch"]
    return {
        "id": sample_id,
        "sample_id": sample_id,
        # premise 是形成材料，不进入 UI 的 work/raw 投影。
        "raw": json.dumps(
            {"title": parsed["title"], "pitch": pitch}, ensure_ascii=False
        ),
        "title": parsed["title"],
        "flavor": parsed.get("flavor") or "",
        "opening": pitch,
        "pitch": pitch,
        "work": pitch,
    }


async def judge_candidate_shadow(
    user_text: str,
    parsed: dict[str, Any],
    *,
    complete: CompleteFn | None = None,
) -> list[str]:
    """独立模型只标注原因码；不改写候选，也不决定是否保留。"""
    judged = await _run_complete(
        gate_messages(
            user_text,
            title=str(parsed.get("title") or ""),
            pitch=str(parsed.get("pitch") or ""),
            premise=parsed.get("premise") if isinstance(parsed.get("premise"), dict) else None,
        ),
        complete=complete,
        generation=gate_generation(),
        think_char_budget=512,
    )
    return parse_gate_payload(judged.text)


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
    taken_title: str = "",
) -> dict[str, Any] | None:
    """一个 sample job：题材已经抽定，只交这本书的 {title, pitch}。格式失败或撞车后再交一次。"""
    await _emit_thinking_delta("\n—— 独立采样 ——\n")
    last_raw = ""
    for _attempt in range(_SLOT_RETRIES + 1):
        formed = await _run_complete(
            form_messages(user_text, subject=subject, taken_title=taken_title),
            complete=complete,
            generation=form_generation(),
            think_char_budget=_FORM_THINK_CHAR_BUDGET,
            model_route=_CANDIDATE_MODEL_ROUTE,
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
        if parsed is not None and (
            obvious_meta_text(parsed["pitch"])
            or not 20 <= len(str(parsed.get("pitch") or "")) <= 180
        ):
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
        card = _card_payload(sample_id=sample_id, parsed=parsed)
        self_codes = [
            code
            for code in str(parsed.get("intent_codes") or "").split(",")
            if code
        ]
        # 测试注入的 complete 只模拟候选形成；生产路径另起全新 messages 独立判断。
        codes = (
            await judge_candidate_shadow(user_text, parsed)
            if complete is None
            else self_codes
        )
        if codes:
            logger.info(
                "candidate intent shadow id=%s codes=%s self_codes=%s",
                sample_id,
                ",".join(codes),
                ",".join(self_codes),
            )
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


def _longest_common(left: str, right: str) -> int:
    a = "".join(left.split())
    b = "".join(right.split())
    if len(a) < 12 or len(b) < 12:
        return 0
    best = 0
    for size in range(min(len(a), len(b), 48), 11, -1):
        if best >= size:
            break
        window = {a[i : i + size] for i in range(len(a) - size + 1)}
        if any(b[i : i + size] in window for i in range(len(b) - size + 1)):
            return size
    return best


def pitches_too_close(left: str, right: str) -> bool:
    """语义过近才重采。词法回退时，连续相同超过 40 字也算同一本书。"""
    from app.writing.pond_similarity import compute_pond_similarity, same_book_reject

    snap = compute_pond_similarity(
        [
            {"title": "left", "opening": left},
            {"title": "right", "opening": right},
        ],
        shadow=False,
    )
    if snap.get("usable") and same_book_reject(snap):
        return True
    return _longest_common(left, right) >= 40


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
    """有界铺开方向、独立成文，再按成文质量选出至多两本。"""

    _ = (held, gate)
    token = _sample_turn_id.set(turn_id)
    buffered = _buffered_writer()
    if buffered is not None:
        buffered.start_stream_liveness(0)
    await _mark_candidate_thinking()
    try:
        if complete is None:
            return await _search_candidate_pair(
                user_text,
                exclude_ids=set(exclude_ids or ()),
                exclude_fingerprints=set(exclude_fingerprints or ()),
                exclude_titles=set(exclude_titles or ()),
            )
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


async def _map_directions(user_text: str, *, discovery_pass: int) -> list[str]:
    for _attempt in range(_SLOT_RETRIES + 1):
        result = await _run_complete(
            direction_set_messages(user_text, discovery_pass=discovery_pass),
            complete=None,
            generation=direction_generation(),
            think_char_budget=512,
            model_route=_CANDIDATE_MODEL_ROUTE,
        )
        ideas = parse_direction_set(result.text)
        if len(ideas) >= 2:
            return ideas
    return []


async def _select_rendered_cards(
    user_text: str,
    cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not cards:
        return []
    selected = await _run_complete(
        card_selection_messages(user_text, cards),
        complete=None,
        generation=selection_generation(),
        think_char_budget=512,
        model_route=_CANDIDATE_MODEL_ROUTE,
    )
    chosen = [
        cards[index]
        for index in parse_card_selection(selected.text, len(cards))
        if 0 <= index < len(cards)
    ]
    return diversify_selected_cards(cards, chosen)


async def _render_direction(
    user_text: str,
    idea: str,
    *,
    sample_id: str,
    exclude_fingerprints: set[str],
    exclude_titles: set[str],
) -> dict[str, Any] | None:
    for _attempt in range(_SLOT_RETRIES + 1):
        rendered = await _run_complete(
            render_messages(user_text, idea),
            complete=None,
            generation=render_generation(),
            think_char_budget=512,
            model_route=_CANDIDATE_MODEL_ROUTE,
        )
        parsed = parse_card(rendered.text)
        pitch = str(parsed.get("pitch") or "") if parsed is not None else ""
        if (
            parsed is None
            or not 20 <= len(pitch) <= 180
            or obvious_meta_text(pitch)
        ):
            continue
        if _is_excluded(
            parsed,
            exclude_ids=set(),
            exclude_fingerprints=exclude_fingerprints,
            exclude_titles=exclude_titles,
            sample_id=sample_id,
        ):
            continue
        card = _card_payload(sample_id=sample_id, parsed=parsed)
        logger.info(
            "candidate render affinity id=%s score=%.2f",
            sample_id,
            listing_affinity(pitch),
        )
        _log_candidate_trace(
            sample_id=sample_id,
            sample_raw=rendered.text,
            work=card["pitch"],
            selected=False,
            title=card["title"],
            opening=card["pitch"],
            think_chars_form=rendered.think_chars,
            output_tokens_form=rendered.output_tokens,
        )
        return card
    return None


async def _search_candidate_pair(
    user_text: str,
    *,
    exclude_ids: set[str],
    exclude_fingerprints: set[str],
    exclude_titles: set[str],
) -> list[dict[str, Any]]:
    _ = exclude_ids
    if not (request_is_long_novel(user_text) or serves_urban_pool(user_text)):
        return []
    await _emit_thinking_delta("\n—— 短方向搜索 ——\n")
    accepted: list[dict[str, Any]] = []
    seen_fingerprints = set(exclude_fingerprints)
    seen_titles = set(exclude_titles)
    for discovery_pass in range(1, _SEARCH_PASSES + 1):
        ideas = await _map_directions(user_text, discovery_pass=discovery_pass)
        if len(ideas) < 2:
            logger.info(
                "candidate direction map too small pass=%s count=%s",
                discovery_pass,
                len(ideas),
            )
            continue
        rendered = await asyncio.gather(
            *(
                _render_direction(
                    user_text,
                    idea,
                    sample_id=f"p{discovery_pass}-{index + 1:02d}",
                    exclude_fingerprints=seen_fingerprints,
                    exclude_titles=seen_titles,
                )
                for index, idea in enumerate(ideas)
            )
        )
        available = [card for card in rendered if card is not None]
        chosen = await _select_rendered_cards(user_text, available)
        for card in chosen:
            title = str(card.get("title") or "").strip()
            pitch = str(card.get("pitch") or "").strip()
            if not title or not pitch:
                continue
            if any(
                title.casefold() == str(existing.get("title") or "").strip().casefold()
                or pitches_too_close(
                    pitch,
                    str(existing.get("pitch") or ""),
                )
                for existing in accepted
            ):
                continue
            accepted.append(card)
            seen_titles.add(title.casefold())
            seen_fingerprints.add(candidate_fingerprint(pitch))
            if len(accepted) >= _SAMPLE_POOL:
                break
        if len(accepted) >= _SAMPLE_POOL:
            break

    cards: list[dict[str, Any]] = []
    for index, card in enumerate(accepted[:_SAMPLE_POOL], start=1):
        final = {**card, "id": f"c{index:02d}", "sample_id": f"c{index:02d}"}
        cards.append(final)
        _log_candidate_trace(
            sample_id=final["sample_id"],
            work=str(final.get("pitch") or ""),
            selected=True,
            title=str(final.get("title") or ""),
            opening=str(final.get("pitch") or ""),
        )
    if cards:
        shadow_codes = await asyncio.gather(
            *(
                judge_candidate_shadow(
                    user_text,
                    {
                        "title": card.get("title"),
                        "pitch": card.get("pitch"),
                    },
                )
                for card in cards
            )
        )
        for card, codes in zip(cards, shadow_codes):
            if codes:
                logger.info(
                    "candidate intent shadow id=%s codes=%s",
                    card["sample_id"],
                    ",".join(codes),
                )
    return cards


async def resolve_sample_user_text(user_text: str, session_id: Any = None) -> str:
    """同一次选择里的用户原话整段留下。换卡令牌本身不代替前面的方向。"""
    from app.writing.work_reconstruction import sample_user_text

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


async def _sample_with_seed(
    user_text: str,
    *,
    complete: CompleteFn | None,
    sample_id: str,
    seed: SubjectSeed | None,
    exclude_ids: set[str],
    exclude_fingerprints: set[str],
    exclude_titles: set[str],
    taken_title: str = "",
) -> dict[str, Any] | None:
    return await sample_one_candidate(
        user_text,
        complete=complete,
        sample_id=sample_id,
        subject=seed.text if seed is not None else "",
        exclude_ids=exclude_ids,
        exclude_fingerprints=exclude_fingerprints,
        exclude_titles=exclude_titles,
        taken_title=taken_title,
    )


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
    chosen: list[SubjectSeed | None] = list(select_seeds(user_text, _SAMPLE_POOL))
    if len(chosen) < _SAMPLE_POOL:
        if not (request_is_long_novel(user_text) or serves_urban_pool(user_text)):
            return []
        # 点名了具体作品，或没有对应题材池：不塞参照，仍按用户原话各采一次。
        chosen = [None] * _SAMPLE_POOL
    await _emit_thinking_delta("\n—— 题材池 ——\n")
    first = await _sample_with_seed(
        user_text,
        complete=complete,
        sample_id="c01",
        seed=chosen[0],
        exclude_ids=exclude_ids,
        exclude_fingerprints=exclude_fingerprints,
        exclude_titles=exclude_titles,
    )
    second_exclude_titles = set(exclude_titles)
    if first is not None:
        first_title = str(first.get("title") or "").strip()
        if first_title:
            second_exclude_titles.add(first_title.casefold())
    second = await _sample_with_seed(
        user_text,
        complete=complete,
        sample_id="c02",
        seed=chosen[1],
        exclude_ids=exclude_ids,
        exclude_fingerprints=exclude_fingerprints,
        exclude_titles=second_exclude_titles,
    )
    if (
        first is not None
        and second is not None
        and pitches_too_close(str(first.get("pitch") or ""), str(second.get("pitch") or ""))
    ):
        replacement = chosen[1]
        used_seeds = [seed for seed in chosen if seed is not None]
        if used_seeds:
            alternatives = select_seeds(
                user_text,
                1,
                exclude_texts={seed.text for seed in used_seeds},
                exclude_families={seed.family for seed in used_seeds},
            )
            if alternatives:
                replacement = alternatives[0]
        second = await _sample_with_seed(
            user_text,
            complete=complete,
            sample_id="c02",
            seed=replacement,
            exclude_ids=exclude_ids,
            exclude_fingerprints=exclude_fingerprints,
            exclude_titles=second_exclude_titles,
        )
    sampled = [first, second]
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
