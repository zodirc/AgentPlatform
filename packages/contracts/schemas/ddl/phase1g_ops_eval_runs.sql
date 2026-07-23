-- Ops Eval Console: persisted run history (docs/29)

CREATE TABLE IF NOT EXISTS ops_eval_runs (
    id                UUID PRIMARY KEY,
    status            TEXT NOT NULL,
    mode              TEXT NOT NULL,
    restart_runtime   BOOLEAN NOT NULL DEFAULT false,
    created_at        TIMESTAMPTZ NOT NULL,
    finished_at       TIMESTAMPTZ,
    error             TEXT,
    -- Never store live api_key; optional provider/model_name only.
    model_meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary           JSONB NOT NULL DEFAULT '{}'::jsonb,
    cases             JSONB NOT NULL DEFAULT '[]'::jsonb,
    logs              JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ops_eval_runs_created_at
    ON ops_eval_runs (created_at DESC);
