-- Phase 1c: rolling session transcript for cross-turn message continuity.
-- Runtime owns writes; api does not project this table.
-- Authority: docs/07-domain-model.md §5 (rolling history), docs/14-model-harness.md

CREATE TABLE IF NOT EXISTS session_transcripts (
    session_id      UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    messages        JSONB NOT NULL DEFAULT '[]',
    token_estimate  INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
