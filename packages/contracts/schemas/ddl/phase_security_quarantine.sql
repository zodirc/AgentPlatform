-- Quarantine is a separate store from turn_events. Raw bodies stay here.
-- The runtime role that inserts turn_events should not UPDATE or DELETE them.
-- Retention and session teardown use a different role, so this migration does
-- not revoke those privileges from the migration user.

CREATE TABLE IF NOT EXISTS quarantine_items (
    id uuid PRIMARY KEY,
    turn_id uuid,
    tool_name text NOT NULL,
    body_ciphertext bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    access_count integer NOT NULL DEFAULT 0
);

COMMENT ON TABLE quarantine_items IS
    'Encrypted tool bodies isolated by the injection detector. Not an audit log.';
