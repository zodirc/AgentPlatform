-- Phase 1h: per-Work product seed corpus toggle (docs/15 · docs/27 TenantContext.visibility_seed)
ALTER TABLE works
    ADD COLUMN IF NOT EXISTS visibility_seed BOOLEAN NOT NULL DEFAULT true;

COMMENT ON COLUMN works.visibility_seed IS
    'When false, Turn TenantContext hides sources/seed/** from retrieval and path visibility.';
