-- Phase 1e: model provider profiles owned by end users.
-- One active profile per owner (replaces global singleton active).

ALTER TABLE model_provider_profiles
    ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES end_users(id);

UPDATE model_provider_profiles
SET owner_user_id = '00000000-0000-4000-8000-000000000099'
WHERE owner_user_id IS NULL;

ALTER TABLE model_provider_profiles
    ALTER COLUMN owner_user_id SET NOT NULL;

DROP INDEX IF EXISTS idx_model_provider_profiles_one_active;

CREATE UNIQUE INDEX IF NOT EXISTS idx_model_provider_profiles_one_active_per_owner
    ON model_provider_profiles (owner_user_id)
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_model_provider_profiles_owner
    ON model_provider_profiles (owner_user_id);
