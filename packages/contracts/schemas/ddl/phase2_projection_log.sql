-- Projection failure audit trail (docs/09-event-projection-pipeline.md §6.1)
-- Records projection errors so async projection failures are observable and
-- recoverable rather than silently swallowed.

CREATE TABLE IF NOT EXISTS projection_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id             UUID,
    last_event_sequence BIGINT NOT NULL DEFAULT 0,
    error               TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projection_log_turn ON projection_log (turn_id, created_at DESC);
