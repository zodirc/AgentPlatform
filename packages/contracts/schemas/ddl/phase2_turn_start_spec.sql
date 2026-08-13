-- Phase 2: unified pull StartSpec + per-turn model secret escrow.
-- Claim loads ops_eval/model_mode + one-shot decrypt of override (no HTTP push fork).

ALTER TABLE runs
    ADD COLUMN IF NOT EXISTS ops_eval BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE runs
    ADD COLUMN IF NOT EXISTS model_mode VARCHAR(32);

CREATE TABLE IF NOT EXISTS turn_model_secrets (
    run_id          UUID PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    turn_id         UUID NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
    ciphertext      BYTEA NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    consumed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_turn_model_secrets_expires
    ON turn_model_secrets (expires_at)
    WHERE consumed_at IS NULL;
