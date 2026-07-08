-- Phase 1: model provider runtime configuration (ADR-019).
-- Apply after phase0.sql via api migration (Alembic etc.).
-- Authority: docs/contracts.md §7.1, docs/adr/019-model-provider-runtime-config.md

CREATE TABLE model_provider_profiles (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label               VARCHAR(128) NOT NULL,
    provider            VARCHAR(32) NOT NULL,
    model_name          VARCHAR(128) NOT NULL,
    api_key_ciphertext  BYTEA NOT NULL,
    base_url            TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT false,
    config_version      BIGINT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Exactly one active profile at a time (Phase 1).
CREATE UNIQUE INDEX idx_model_provider_profiles_one_active
    ON model_provider_profiles (is_active)
    WHERE is_active = true;

CREATE INDEX idx_model_provider_profiles_provider ON model_provider_profiles(provider);

-- Optional: notify runtime to invalidate ModelGateway cache (see ADR-019 §5).
-- CREATE OR REPLACE FUNCTION notify_provider_config_change() RETURNS trigger AS $$
-- BEGIN
--   PERFORM pg_notify('provider_config_channel', NEW.id::text);
--   RETURN NEW;
-- END;
-- $$ LANGUAGE plpgsql;
-- CREATE TRIGGER model_provider_profiles_notify
--   AFTER INSERT OR UPDATE ON model_provider_profiles
--   FOR EACH ROW EXECUTE FUNCTION notify_provider_config_change();
