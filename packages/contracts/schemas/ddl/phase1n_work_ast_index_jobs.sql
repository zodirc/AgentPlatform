-- A6: AST indexer job queue (docs/plan/agent-workspace-ast-index.md §0.4 / §3.0).
-- Runtime enqueues; agent-ast-indexer claims via FOR UPDATE SKIP LOCKED.
-- Isolated from RAG outbox / source_* tables.

CREATE TABLE IF NOT EXISTS work_ast_index_jobs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    work_id       UUID NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    owner_user_id TEXT NOT NULL,
    kind          TEXT NOT NULL,              -- cold_start | dirty | purge
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending|running|done|failed
    work_root     TEXT NOT NULL DEFAULT '',
    memory_only   BOOLEAN NOT NULL DEFAULT false,
    paths         JSONB NOT NULL DEFAULT '[]'::jsonb,
    attempts      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    locked_by     TEXT,
    locked_at     TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    finished_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_work_ast_index_jobs_pending
    ON work_ast_index_jobs (created_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_work_ast_index_jobs_work
    ON work_ast_index_jobs (work_id, status);
