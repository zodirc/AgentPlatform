-- One row per work_gc mark. Sweep stays off, so deleted stays 0.
-- A pending work_gc job is unique per work until it leaves the queue.

CREATE TABLE IF NOT EXISTS gc_runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_id       UUID NOT NULL,
    abort_reason  TEXT,
    candidates    INTEGER NOT NULL DEFAULT 0,
    deleted       INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_outbox_work_gc_inflight
    ON outbox_jobs ((payload->>'work_id'))
    WHERE job_type = 'work_gc'
      AND status IN ('pending', 'retry', 'processing');
