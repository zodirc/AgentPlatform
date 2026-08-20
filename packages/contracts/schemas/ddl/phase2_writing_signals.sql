-- Writing account prefs (cross-Work) + fragment evaluation history.

CREATE TABLE IF NOT EXISTS writing_account_prefs (
    owner_user_id   UUID PRIMARY KEY REFERENCES end_users(id) ON DELETE CASCADE,
    preset_label    VARCHAR(32) NOT NULL DEFAULT 'balanced',
    fragment_weights JSONB NOT NULL DEFAULT '{}'::jsonb,
    signal_penalties JSONB NOT NULL DEFAULT '{}'::jsonb,
    signal_rewards   JSONB NOT NULL DEFAULT '{}'::jsonb,
    schema_version  INT NOT NULL DEFAULT 1,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS writing_fragment_evaluations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id       UUID NOT NULL REFERENCES end_users(id) ON DELETE CASCADE,
    work_id             UUID REFERENCES works(id) ON DELETE SET NULL,
    session_id          UUID,
    turn_id             UUID,
    section_id          TEXT,
    fragment_declared   TEXT NOT NULL,
    fragment_detected   TEXT,
    writing_signals     JSONB NOT NULL,
    text_sha256         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_writing_fragment_evaluations_owner
    ON writing_fragment_evaluations (owner_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_writing_fragment_evaluations_work
    ON writing_fragment_evaluations (work_id, created_at DESC)
    WHERE work_id IS NOT NULL;
