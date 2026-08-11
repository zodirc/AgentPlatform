-- Agent workspace AST index (docs/plan/agent-workspace-ast-index.md §5.1).
-- Independent of RAG source_chunks / source_index_meta. Definitions-only snapshot;
-- memory projection is the query surface; these tables are restart recovery only.

CREATE TABLE IF NOT EXISTS work_ast_index_meta (
    work_id        UUID PRIMARY KEY REFERENCES works(id) ON DELETE CASCADE,
    owner_user_id  TEXT NOT NULL,
    status         TEXT NOT NULL,          -- cold|building|ready|stale|error
    generation     BIGINT NOT NULL DEFAULT 0,
    files_total    INTEGER NOT NULL DEFAULT 0,
    files_done     INTEGER NOT NULL DEFAULT 0,
    error          TEXT,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_work_ast_index_meta_owner
    ON work_ast_index_meta (owner_user_id);

CREATE TABLE IF NOT EXISTS work_ast_files (
    work_id       UUID NOT NULL REFERENCES works(id) ON DELETE CASCADE,
    path          TEXT NOT NULL,            -- relative to work_root
    lang          TEXT NOT NULL,            -- python|…|skipped
    content_hash  TEXT NOT NULL,
    mtime_ns      BIGINT NOT NULL,
    size          BIGINT NOT NULL,
    symbols       JSONB NOT NULL,           -- [{"n","k","l","c","el"}, …]
    generation    BIGINT NOT NULL,
    PRIMARY KEY (work_id, path)
);

CREATE INDEX IF NOT EXISTS idx_work_ast_files_work_gen
    ON work_ast_files (work_id, generation);
