-- Phase 1d: end users + session ownership (docs/20-user-session-history-plan.md)
-- Purges pre-ownership sessions (product-approved cutover).

CREATE TABLE IF NOT EXISTS end_users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(64) NOT NULL,
    password_hash   TEXT NOT NULL,
    status          VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_end_users_username_lower
    ON end_users (lower(username));

-- System actor for admin/eval session bypass (login disabled).
INSERT INTO end_users (id, username, password_hash, status)
VALUES (
    '00000000-0000-4000-8000-000000000099',
    '__system',
    '!',
    'disabled'
)
ON CONFLICT (id) DO NOTHING;

-- Purge session graph from before ownership (FK order; no CASCADE on phase0 turns).
DELETE FROM turn_events;
DELETE FROM checkpoints;
DELETE FROM artifacts;
DELETE FROM approval_views;
DELETE FROM turn_views;
DELETE FROM runs;
DELETE FROM turns;
DELETE FROM session_views;
DELETE FROM session_transcripts;
DELETE FROM sessions;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES end_users(id);

UPDATE sessions
SET owner_user_id = '00000000-0000-4000-8000-000000000099'
WHERE owner_user_id IS NULL;

ALTER TABLE sessions
    ALTER COLUMN owner_user_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sessions_owner_updated
    ON sessions (owner_user_id, updated_at DESC);
