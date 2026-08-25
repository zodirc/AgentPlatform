-- Session hard-delete removes turn_events first, then runs. Without an index on
-- turn_events.run_id, Postgres FK checks for DELETE FROM runs seq-scan the whole
-- events table (multi-GB), so history bulk-delete appears to hang.
CREATE INDEX IF NOT EXISTS idx_turn_events_run_id ON turn_events (run_id);
