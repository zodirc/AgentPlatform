"""Shared list filters for Ops recent-turn browse APIs."""

from __future__ import annotations

from typing import Any

# UI `within` values → hours. ``all`` / empty → no time window.
_WITHIN_HOURS: dict[str, int] = {
    "1": 1,
    "24": 24,
    "168": 168,
    "720": 720,
}


def normalize_page(
    *,
    limit: int = 40,
    offset: int = 0,
    max_limit: int = 100,
) -> tuple[int, int]:
    return max(1, min(int(limit), max_limit)), max(0, int(offset))


def parse_within_hours(within: str | None) -> int | None:
    """Parse Ops list ``within`` (1 / 24 / 168 / 720 / all) to hours."""
    raw = (within or "").strip().lower()
    if not raw or raw in {"all", "*"}:
        return None
    raw = raw.rstrip("h")
    if raw in _WITHIN_HOURS:
        return _WITHIN_HOURS[raw]
    try:
        hours = int(raw)
    except ValueError:
        return None
    if hours <= 0:
        return None
    return min(hours, 24 * 90)


def append_since_hours(
    clauses: list[str],
    args: list[Any],
    *,
    column: str,
    hours: int | None,
) -> None:
    """Require ``column > now() - N hours`` (e.g. ``e.created_at``, ``e.ts``)."""
    if hours is None or hours <= 0:
        return
    args.append(int(hours))
    clauses.append(f"{column} > now() - make_interval(hours => ${len(args)})")


def append_turn_filters(
    clauses: list[str],
    args: list[Any],
    *,
    status: str | None = None,
    scenario: str | None = None,
    q: str | None = None,
    extra_q_sql: str | None = None,
) -> None:
    """Append AND-able SQL fragments for turn list filters.

    Uses ``t`` / ``s`` aliases (turns / sessions). ``extra_q_sql`` is OR'd into
    the search clause (already uses the next placeholder as ``$N`` via ``?``).
    """

    def add(clause: str, value: Any) -> None:
        args.append(value)
        clauses.append(clause.replace("?", f"${len(args)}"))

    if status and status.strip():
        add("t.status = ?", status.strip().lower())
    if scenario and scenario.strip():
        add("t.scenario_id = ?", scenario.strip())
    needle = (q or "").strip()
    if needle:
        args.append(f"%{needle}%")
        n = len(args)
        parts = [
            f"t.id::text ILIKE ${n}",
            f"t.session_id::text ILIKE ${n}",
            f"COALESCE(t.user_input, '') ILIKE ${n}",
        ]
        if extra_q_sql:
            parts.append(extra_q_sql.replace("?", f"${n}"))
        clauses.append("(" + " OR ".join(parts) + ")")


def where_sql(clauses: list[str]) -> str:
    return f"WHERE {' AND '.join(clauses)}" if clauses else ""
