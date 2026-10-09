-- Command allow rules are per user and per Work. A null work_id is a legacy row.
-- clear_context is set by the user, never by the model, and consumed on the next turn.

ALTER TABLE command_allow_prefixes
    ADD COLUMN IF NOT EXISTS work_id UUID;

CREATE INDEX IF NOT EXISTS idx_command_allow_prefixes_owner_work
    ON command_allow_prefixes (owner_user_id, work_id);

DROP INDEX IF EXISTS uq_command_allow_prefixes_owner_prefix;

CREATE UNIQUE INDEX IF NOT EXISTS uq_command_allow_prefixes_owner_prefix_legacy
    ON command_allow_prefixes (owner_user_id, prefix)
    WHERE work_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_command_allow_prefixes_owner_prefix_work
    ON command_allow_prefixes (owner_user_id, prefix, work_id)
    WHERE work_id IS NOT NULL;

ALTER TABLE turns
    ADD COLUMN IF NOT EXISTS clear_context BOOLEAN NOT NULL DEFAULT false;

-- The runtime role is insert-only. Retention keeps using the migration role.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_runtime_append') THEN
        CREATE ROLE agent_runtime_append NOLOGIN;
    END IF;
    GRANT INSERT ON turn_events TO agent_runtime_append;
    REVOKE UPDATE, DELETE ON turn_events FROM agent_runtime_append;
    GRANT agent_runtime_append TO CURRENT_USER;
EXCEPTION
    WHEN insufficient_privilege THEN
        NULL;
END $$;
