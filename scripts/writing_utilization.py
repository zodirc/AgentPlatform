#!/usr/bin/env python3
"""Writing reward-utilization ledger.

Reads product turn_events (JSON or Postgres) and writes
eval/reports/writing/latest_utilization.json. Primary quality column is
delta_composite (clamped net is appendix). Not an official_suite; does not
gate merge.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_APP = ROOT / "services" / "runtime"
DEFAULT_OUT = ROOT / "eval" / "reports" / "writing" / "latest_utilization.json"

if str(RUNTIME_APP) not in sys.path:
    sys.path.insert(0, str(RUNTIME_APP))

from app.writing.signals.utilization import summarize_writing_turns  # noqa: E402

_EVENT_SQL = """
SELECT turn_id::text AS turn_id,
       sequence,
       type,
       payload,
       created_at
FROM turn_events
WHERE type IN ('tool.completed', 'usage.reported')
  AND (
        type = 'usage.reported'
        OR payload->>'tool_name' IN ('draft_section', 'propose_patch', 'apply_patch')
      )
  AND created_at >= now() - ($1::text)::interval
ORDER BY turn_id, sequence
"""


def _load_events_json(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("events"), list):
        return list(raw["events"])
    if isinstance(raw, list):
        return list(raw)
    raise ValueError(f"expected list or {{events: []}} in {path}")


async def _load_events_db(dsn: str, since: str) -> list[dict[str, Any]]:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(_EVENT_SQL, since)
    finally:
        await conn.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        out.append(
            {
                "turn_id": row["turn_id"],
                "sequence": row["sequence"],
                "type": row["type"],
                "payload": payload,
                "created_at": row["created_at"].isoformat()
                if row["created_at"] is not None
                else None,
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--events",
        type=Path,
        help="JSON list of turn_events (or {events: [...]})",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="Postgres DSN (default DATABASE_URL). Ignored when --events is set.",
    )
    parser.add_argument(
        "--since",
        default="7 days",
        help="Postgres lookback interval (default: 7 days)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output path (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args(argv)

    if args.events:
        events = _load_events_json(args.events)
        source = str(args.events)
    elif args.database_url:
        events = asyncio.run(_load_events_db(args.database_url, args.since))
        source = "postgres"
    else:
        parser.error("pass --events JSON or --database-url / DATABASE_URL")
        return 2

    summary = summarize_writing_turns(events)
    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "since": None if args.events else args.since,
        "n_events": len(events),
        **summary,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: doc[k] for k in (
        "n_turns_scored",
        "n_weak",
        "n_acted",
        "weak_rate",
        "acted_rate",
        "span_hit_rate",
        "mean_delta_net",
        "mean_tokens_per_delta",
        "n_sections_scored",
        "section_weak_rate",
        "section_acted_rate",
        "mean_section_delta_net",
        "mean_section_delta_composite",
        "abandoned_weak_rate",
        "clamp_hit_rate",
    )}, ensure_ascii=False))
    print(str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
