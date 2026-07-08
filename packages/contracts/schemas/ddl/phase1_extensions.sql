-- Phase 1 extensions: checkpoints, session_views, artifacts metadata
-- Authority: docs/07-domain-model.md §6-7, docs/contracts.md §7

CREATE TABLE IF NOT EXISTS checkpoints (
    run_id              UUID PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    turn_id             UUID NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    step_index          INTEGER NOT NULL DEFAULT 0,
    state_json          JSONB NOT NULL,
    interrupt_payload   JSONB,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_turn_id ON checkpoints(turn_id);

CREATE TABLE IF NOT EXISTS session_views (
    session_id          UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    default_scenario_id VARCHAR(32) NOT NULL,
    status              VARCHAR(32) NOT NULL DEFAULT 'active',
    turn_count          INTEGER NOT NULL DEFAULT 0,
    last_turn_id        UUID,
    last_turn_status    VARCHAR(32),
    context_summary     JSONB,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS artifacts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id             UUID NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    artifact_type       VARCHAR(64) NOT NULL,
    ref_path            TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_artifacts_turn_id ON artifacts(turn_id);

CREATE TABLE IF NOT EXISTS approval_views (
    turn_id             UUID PRIMARY KEY REFERENCES turns(id) ON DELETE CASCADE,
    tool_call_id        TEXT NOT NULL,
    tool_name           TEXT,
    status              VARCHAR(32) NOT NULL DEFAULT 'pending',
    reason              TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
