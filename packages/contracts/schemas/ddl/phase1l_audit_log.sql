-- B17 (docs/35): sensitive operations (approve/deny/cancel/patch/delete
-- session) previously left no record of the acting user.
CREATE TABLE IF NOT EXISTS audit_log (
    id             BIGSERIAL PRIMARY KEY,
    ts             TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_user_id  UUID,
    actor_username TEXT,
    action         VARCHAR(64) NOT NULL,
    resource_type  VARCHAR(32) NOT NULL,
    resource_id    TEXT,
    detail         JSONB
);

CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log (ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log (actor_user_id, ts DESC);
