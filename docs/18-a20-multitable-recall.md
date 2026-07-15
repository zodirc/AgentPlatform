# A20 — Multi-table / business-record recall (blueprint)

> Status: design-first stub (docs/16 Q15 · docs/17 S3 A20).  
> Non-goals: LLM-per-query routing; graph nodes; per-turn vector pre-inject.

## Shape

```text
search_records(query, channel?, filters?)
  → rule router (entity keywords / scenario)   # deterministic
  → parallel channels (each ≤300ms)
  → ACL predicate per row
  → fused hits (path + id + excerpt) — empty if no backends
```

## Rate rules

- Tool-mediated only (model chooses to call).
- Channel timeouts degrade to remaining lanes or empty + `hint`.
- No join explosion across tenant boundaries.

## Current code

- Tool `search_records` registered as an **honest stub** returning
  `status=unimplemented` / empty hits until a real table backend is wired.
- Enabling a channel means implementing a `RecordChannel` behind the same tool;
  never a new LangGraph node.

## Next (product trigger)

1. Pick one business table + ACL columns.
2. Implement one channel with `asyncio.wait_for(..., 0.3)`.
3. Golden: ACL deny returns zero rows; timeout returns `degraded=true`.
