-- Phase 1f: works + session.work_id (docs/27 multi-tenancy MT1)
-- Default-on Work scope; no TENANT_MODE switch.

CREATE TABLE IF NOT EXISTS works (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id   UUID NOT NULL REFERENCES end_users(id),
    name            VARCHAR(128) NOT NULL DEFAULT 'default',
    work_root       TEXT NOT NULL,
    is_default      BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_works_owner_default
    ON works (owner_user_id)
    WHERE is_default;

CREATE INDEX IF NOT EXISTS idx_works_owner
    ON works (owner_user_id);

-- Legacy claim: one shared /workspace root for existing session owners (personal continuity).
-- New users after migrate get /data/works/{id} via application ensure_default_work.
INSERT INTO works (id, owner_user_id, name, work_root, is_default)
SELECT
    gen_random_uuid(),
    u.id,
    'default',
    '/workspace',
    true
FROM end_users u
WHERE NOT EXISTS (
    SELECT 1 FROM works w WHERE w.owner_user_id = u.id AND w.is_default
);

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS work_id UUID REFERENCES works(id);

UPDATE sessions s
SET work_id = w.id
FROM works w
WHERE s.owner_user_id = w.owner_user_id
  AND w.is_default
  AND s.work_id IS NULL;

-- Sessions must have a work; create orphans under system default if any remain.
UPDATE sessions s
SET work_id = (
    SELECT w.id FROM works w
    WHERE w.owner_user_id = '00000000-0000-4000-8000-000000000099'
      AND w.is_default
    LIMIT 1
)
WHERE s.work_id IS NULL;

ALTER TABLE sessions
    ALTER COLUMN work_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sessions_work
    ON sessions (work_id);
