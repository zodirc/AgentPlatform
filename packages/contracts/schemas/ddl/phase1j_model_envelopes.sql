-- HM4: sampled model request envelopes (Ops replay)
CREATE TABLE IF NOT EXISTS model_request_envelopes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id UUID NOT NULL,
    session_id UUID,
    step_index INT NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    fill_ratio DOUBLE PRECISION,
    envelope JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_model_request_envelopes_turn
    ON model_request_envelopes (turn_id, step_index);
