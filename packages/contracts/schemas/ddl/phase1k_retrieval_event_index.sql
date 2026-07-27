-- A13 (docs/35): ops retrieval audit filters turn_events by
-- type = 'retrieval.completed', which otherwise full-scans the busiest table.
-- Partial index keeps it tiny: only retrieval rows, ordered for both the
-- per-turn audit (turn_id prefix) and the recent-turns listing (ts).
CREATE INDEX IF NOT EXISTS idx_turn_events_retrieval_completed
ON turn_events (turn_id, ts)
WHERE type = 'retrieval.completed';
