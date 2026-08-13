-- Phase 2 run_commands channel (backend-scaling O2 / WP6).
-- Approve/deny/patch/cancel decisions: INSERT + NOTIFY; owner runtime consumes.

CREATE TABLE IF NOT EXISTS run_commands (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    type            TEXT NOT NULL CHECK (type IN (
                        'approve', 'deny', 'patch_accept', 'patch_reject', 'cancel'
                    )),
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'consumed', 'expired')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumed_at     TIMESTAMPTZ
);

-- At most one pending command of a given type per run (stronger than in-memory dedup).
CREATE UNIQUE INDEX IF NOT EXISTS uq_run_commands_pending_type
    ON run_commands (run_id, type)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_run_commands_pending_run
    ON run_commands (run_id, created_at)
    WHERE status = 'pending';
