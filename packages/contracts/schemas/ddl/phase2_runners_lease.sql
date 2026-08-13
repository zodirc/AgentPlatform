-- Phase 2 runners registry + run lease (backend-scaling O3 / WP1).
-- runners: replica heartbeat; runs.lease_expires_at: crash reclaim by api.

CREATE TABLE IF NOT EXISTS runners (
    runner_id           TEXT PRIMARY KEY,
    kind                TEXT NOT NULL CHECK (kind IN ('runtime', 'ast_indexer', 'bench')),
    node                TEXT NOT NULL DEFAULT '',
    last_heartbeat_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    capacity            INTEGER NOT NULL DEFAULT 0,
    inflight            INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_runners_kind_heartbeat
    ON runners (kind, last_heartbeat_at);

ALTER TABLE runs
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_runs_lease_expires
    ON runs (lease_expires_at)
    WHERE status IN ('running', 'interrupted') AND lease_expires_at IS NOT NULL;
