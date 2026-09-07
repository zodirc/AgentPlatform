-- Work-scoped agent memory (prefs/notes). Distinct from sources RAG.

CREATE TABLE IF NOT EXISTS work_memories (
    id              TEXT PRIMARY KEY,
    work_id         UUID NOT NULL,
    session_id      UUID,
    namespace       TEXT NOT NULL DEFAULT 'prefs',
    scope           TEXT NOT NULL DEFAULT 'work',
    lifetime        TEXT NOT NULL DEFAULT 'work',
    trust           TEXT NOT NULL DEFAULT 'user',
    text            TEXT NOT NULL,
    importance      DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    vector          DOUBLE PRECISION[],
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_work_memories_work_ns
    ON work_memories (work_id, namespace, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_work_memories_session
    ON work_memories (session_id)
    WHERE session_id IS NOT NULL;
