-- Phase 1b: per-profile model context window (ADR-019 extension)
ALTER TABLE model_provider_profiles
    ADD COLUMN IF NOT EXISTS context_window_tokens INTEGER;
