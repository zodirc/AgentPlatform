-- Per-user run_command prefixes that skip approval (settings-deletable).

CREATE TABLE IF NOT EXISTS command_allow_prefixes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id   UUID NOT NULL REFERENCES end_users(id) ON DELETE CASCADE,
    prefix          TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT command_allow_prefixes_prefix_len
        CHECK (char_length(prefix) BETWEEN 1 AND 200)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_command_allow_prefixes_owner_prefix
    ON command_allow_prefixes (owner_user_id, prefix);

CREATE INDEX IF NOT EXISTS idx_command_allow_prefixes_owner
    ON command_allow_prefixes (owner_user_id, created_at DESC);
