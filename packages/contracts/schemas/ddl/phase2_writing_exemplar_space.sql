-- Style metric space: curated exemplars + per-fragment prototypes.
-- Independent of RAG source_chunks. Platform source of truth remains git markdown;
-- these tables are the projection (account / work overlay + replay).

CREATE TABLE IF NOT EXISTS writing_exemplars (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope                 TEXT NOT NULL CHECK (scope IN ('platform', 'account', 'work')),
    owner_user_id         UUID REFERENCES end_users(id) ON DELETE CASCADE,
    work_id               UUID REFERENCES works(id) ON DELETE CASCADE,
    fragment              TEXT NOT NULL,
    slug                  TEXT NOT NULL,
    author                TEXT NOT NULL DEFAULT '',
    work_title            TEXT NOT NULL DEFAULT '',
    beat                  TEXT NOT NULL DEFAULT '',
    license               TEXT NOT NULL DEFAULT 'public_domain',
    source_uri            TEXT,
    text_sha256           TEXT NOT NULL,
    feature_schema_id     TEXT NOT NULL,
    signature             JSONB NOT NULL,
    embedding             JSONB,
    embedding_model       TEXT,
    weight                REAL NOT NULL DEFAULT 1.0,
    enabled               BOOLEAN NOT NULL DEFAULT TRUE,
    promoted_from_eval_id UUID REFERENCES writing_fragment_evaluations(id) ON DELETE SET NULL,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT writing_exemplars_scope_keys CHECK (
        (scope = 'platform' AND owner_user_id IS NULL AND work_id IS NULL)
        OR (scope = 'account' AND owner_user_id IS NOT NULL AND work_id IS NULL)
        OR (scope = 'work' AND work_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS writing_exemplars_platform_slug
    ON writing_exemplars (fragment, slug, feature_schema_id)
    WHERE scope = 'platform';

CREATE UNIQUE INDEX IF NOT EXISTS writing_exemplars_account_slug
    ON writing_exemplars (owner_user_id, fragment, slug, feature_schema_id)
    WHERE scope = 'account';

CREATE UNIQUE INDEX IF NOT EXISTS writing_exemplars_work_slug
    ON writing_exemplars (work_id, fragment, slug, feature_schema_id)
    WHERE scope = 'work';

CREATE INDEX IF NOT EXISTS writing_exemplars_lookup
    ON writing_exemplars (scope, fragment, feature_schema_id)
    WHERE enabled;

CREATE TABLE IF NOT EXISTS writing_exemplar_prototypes (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope             TEXT NOT NULL CHECK (scope IN ('platform', 'account', 'work')),
    owner_user_id     UUID REFERENCES end_users(id) ON DELETE CASCADE,
    work_id           UUID REFERENCES works(id) ON DELETE CASCADE,
    fragment          TEXT NOT NULL,
    feature_schema_id TEXT NOT NULL,
    centroid          JSONB NOT NULL,
    scale             JSONB NOT NULL,
    medoid_slug       TEXT NOT NULL DEFAULT '',
    n                 INT NOT NULL,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT writing_prototypes_scope_keys CHECK (
        (scope = 'platform' AND owner_user_id IS NULL AND work_id IS NULL)
        OR (scope = 'account' AND owner_user_id IS NOT NULL AND work_id IS NULL)
        OR (scope = 'work' AND work_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS writing_prototypes_platform
    ON writing_exemplar_prototypes (fragment, feature_schema_id)
    WHERE scope = 'platform';

CREATE UNIQUE INDEX IF NOT EXISTS writing_prototypes_account
    ON writing_exemplar_prototypes (owner_user_id, fragment, feature_schema_id)
    WHERE scope = 'account';

CREATE UNIQUE INDEX IF NOT EXISTS writing_prototypes_work
    ON writing_exemplar_prototypes (work_id, fragment, feature_schema_id)
    WHERE scope = 'work';

ALTER TABLE writing_fragment_evaluations
    ADD COLUMN IF NOT EXISTS feature_schema_id TEXT,
    ADD COLUMN IF NOT EXISTS signature JSONB,
    ADD COLUMN IF NOT EXISTS prototype_scope TEXT,
    ADD COLUMN IF NOT EXISTS nearest_exemplar_slug TEXT;
