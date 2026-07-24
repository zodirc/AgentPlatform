-- HM2: append-only raw message snapshots (never model-facing)
CREATE TABLE IF NOT EXISTS session_raw_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn_id UUID NOT NULL,
    step_index INT NOT NULL DEFAULT 0,
    messages JSONB NOT NULL DEFAULT '[]'::jsonb,
    tools_fingerprint TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_session_raw_snapshots_turn
    ON session_raw_snapshots (turn_id, step_index);

CREATE INDEX IF NOT EXISTS idx_session_raw_snapshots_session
    ON session_raw_snapshots (session_id, created_at DESC);
