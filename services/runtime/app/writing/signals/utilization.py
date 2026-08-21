"""Writing reward-utilization ledger from product turn_events (no I/O).

Join tool.completed writing probes with usage.reported. Not an official_suite.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

_PROSE_TOOLS = frozenset({"draft_section", "propose_patch", "apply_patch"})


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    blob = event.get("payload")
    return blob if isinstance(blob, dict) else {}


def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("type") or event.get("event_type") or "")


def _span_hit(repair_old: str, patch_old: str) -> bool:
    a = (repair_old or "").strip()
    b = (patch_old or "").strip()
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def summarize_prose_cycle(
    tools: list[dict[str, Any]],
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> dict[str, Any] | None:
    """First scored draft vs later patch on one chapter (or one Turn if unsplit)."""
    scored = [p for p in tools if p.get("net_signal") is not None]
    if not scored:
        return None
    first_weak: dict[str, Any] | None = None
    acted = False
    span_hit = False
    for payload in tools:
        if first_weak is None and payload.get("writing_weak"):
            first_weak = payload
            continue
        if first_weak is not None and payload.get("tool_name") == "propose_patch":
            acted = True
            span_hit = _span_hit(
                str(first_weak.get("old_text") or ""),
                str(payload.get("old_text") or ""),
            )
            break
    first_net = float(scored[0]["net_signal"])
    last_net = float(scored[-1]["net_signal"])
    delta_net = round(last_net - first_net, 4) if len(scored) >= 2 else None
    composites = [p for p in scored if p.get("composite") is not None]
    first_composite = _as_float(composites[0]["composite"]) if composites else None
    last_composite = _as_float(composites[-1]["composite"]) if composites else None
    delta_composite = None
    if first_composite is not None and last_composite is not None and len(composites) >= 2:
        delta_composite = round(last_composite - first_composite, 4)
    last = scored[-1]
    last_reward_sum = _as_float(last.get("reward_sum"))
    last_penalty_sum = _as_float(last.get("penalty_sum"))
    last_comp = _as_float(last.get("composite"))
    clamp_hit = None
    if last_comp is not None:
        clamp_hit = last_net >= 0.999 and last_comp < 0.999
    abandoned_weak = bool(last.get("writing_weak"))
    tokens = input_tokens + output_tokens
    tokens_per_delta = None
    if delta_net is not None and abs(delta_net) >= 1e-6 and tokens > 0:
        tokens_per_delta = round(tokens / abs(delta_net), 1)
    tokens_per_delta_composite = None
    if delta_composite is not None and abs(delta_composite) >= 1e-6 and tokens > 0:
        tokens_per_delta_composite = round(tokens / abs(delta_composite), 1)
    return {
        "scored": True,
        "weak": first_weak is not None,
        "acted": acted,
        "span_hit": span_hit if acted else None,
        "abandoned_weak": abandoned_weak,
        "clamp_hit": clamp_hit,
        "first_net": first_net,
        "last_net": last_net,
        "delta_net": delta_net,
        "first_composite": first_composite,
        "last_composite": last_composite,
        "delta_composite": delta_composite,
        "last_reward_sum": last_reward_sum,
        "last_penalty_sum": last_penalty_sum,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tokens": tokens,
        "tokens_per_delta": tokens_per_delta,
        "tokens_per_delta_composite": tokens_per_delta_composite,
        "repair_key": (first_weak or {}).get("repair_key"),
        "rewrite_policy": scored[0].get("rewrite_policy"),
    }


def summarize_turn(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """One Turn: first scored draft vs later patch. None if no writing score."""
    ordered = sorted(
        events,
        key=lambda e: (
            int(e.get("sequence") or 0),
            str(e.get("created_at") or ""),
        ),
    )
    tools: list[dict[str, Any]] = []
    input_tokens = 0
    output_tokens = 0
    for event in ordered:
        kind = _event_type(event)
        payload = _payload(event)
        if kind == "usage.reported":
            try:
                input_tokens += int(payload.get("step_input_tokens") or 0)
            except (TypeError, ValueError):
                pass
            try:
                output_tokens += int(payload.get("step_output_tokens") or 0)
            except (TypeError, ValueError):
                pass
            continue
        if kind != "tool.completed":
            continue
        if payload.get("tool_name") in _PROSE_TOOLS:
            tools.append(payload)
    return summarize_prose_cycle(
        tools, input_tokens=input_tokens, output_tokens=output_tokens
    )


def _tools_by_section(tools: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    last = ""
    for payload in tools:
        sid = str(payload.get("section_id") or "").strip()
        if sid:
            last = sid
        buckets[sid or last or "_"].append(payload)
    return buckets


def summarize_writing_turns(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_turn: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        turn_id = str(event.get("turn_id") or "").strip()
        if turn_id:
            by_turn[turn_id].append(event)
    cases: list[dict[str, Any]] = []
    section_cases: list[dict[str, Any]] = []
    n_scored = n_weak = n_acted = n_span_hit = 0
    delta_vals: list[float] = []
    token_vals: list[int] = []
    tpd_vals: list[float] = []
    for turn_id, group in sorted(by_turn.items()):
        row = summarize_turn(group)
        if row is None:
            continue
        n_scored += 1
        if row["weak"]:
            n_weak += 1
            if row["acted"]:
                n_acted += 1
                if row["span_hit"]:
                    n_span_hit += 1
        if row["delta_net"] is not None:
            delta_vals.append(float(row["delta_net"]))
        token_vals.append(int(row["tokens"]))
        if row["tokens_per_delta"] is not None:
            tpd_vals.append(float(row["tokens_per_delta"]))
        cases.append({"turn_id": turn_id, **row})

        tools = [
            _payload(event)
            for event in sorted(
                group,
                key=lambda e: (int(e.get("sequence") or 0), str(e.get("created_at") or "")),
            )
            if _event_type(event) == "tool.completed"
            and _payload(event).get("tool_name") in _PROSE_TOOLS
        ]
        for section_id, bucket in _tools_by_section(tools).items():
            section_row = summarize_prose_cycle(bucket)
            if section_row is None:
                continue
            section_cases.append(
                {"turn_id": turn_id, "section_id": section_id, **section_row}
            )

    n_sec = n_sec_weak = n_sec_acted = n_sec_span = 0
    n_abandoned = n_clamp = n_clamp_known = 0
    section_deltas: list[float] = []
    section_composites: list[float] = []
    for row in section_cases:
        n_sec += 1
        if row["weak"]:
            n_sec_weak += 1
            if row["acted"]:
                n_sec_acted += 1
                if row["span_hit"]:
                    n_sec_span += 1
            if row.get("abandoned_weak"):
                n_abandoned += 1
        if row["clamp_hit"] is not None:
            n_clamp_known += 1
            if row["clamp_hit"]:
                n_clamp += 1
        if row["delta_net"] is not None:
            section_deltas.append(float(row["delta_net"]))
        if row.get("delta_composite") is not None:
            section_composites.append(float(row["delta_composite"]))

    def _rate(num: int, den: int) -> float | None:
        if den <= 0:
            return None
        return round(num / den, 4)

    def _mean(vals: list[float]) -> float | None:
        if not vals:
            return None
        return round(sum(vals) / len(vals), 4)

    return {
        "n_turns_scored": n_scored,
        "n_weak": n_weak,
        "n_acted": n_acted,
        "n_span_hit": n_span_hit,
        "weak_rate": _rate(n_weak, n_scored),
        "acted_rate": _rate(n_acted, n_weak),
        "span_hit_rate": _rate(n_span_hit, n_acted),
        "mean_delta_net": _mean(delta_vals),
        "mean_tokens": _mean([float(v) for v in token_vals]),
        "mean_tokens_per_delta": _mean(tpd_vals),
        "n_sections_scored": n_sec,
        "n_sections_weak": n_sec_weak,
        "n_sections_acted": n_sec_acted,
        "section_weak_rate": _rate(n_sec_weak, n_sec),
        "section_acted_rate": _rate(n_sec_acted, n_sec_weak),
        "section_span_hit_rate": _rate(n_sec_span, n_sec_acted),
        "mean_section_delta_net": _mean(section_deltas),
        "mean_section_delta_composite": _mean(section_composites),
        "n_abandoned_weak": n_abandoned,
        "abandoned_weak_rate": _rate(n_abandoned, n_sec_weak),
        "n_clamp_hit": n_clamp,
        "clamp_hit_rate": _rate(n_clamp, n_clamp_known),
        "cases": cases,
        "section_cases": section_cases,
    }
