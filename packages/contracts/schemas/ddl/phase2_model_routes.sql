-- User-scoped model routing for narrow product roles.
-- Missing row means inherit the owner's active provider profile.

CREATE TABLE IF NOT EXISTS model_route_preferences (
    owner_user_id UUID NOT NULL REFERENCES end_users(id) ON DELETE CASCADE,
    scenario_id TEXT NOT NULL,
    role TEXT NOT NULL,
    profile_id UUID NOT NULL REFERENCES model_provider_profiles(id) ON DELETE CASCADE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_user_id, scenario_id, role)
);

CREATE INDEX IF NOT EXISTS idx_model_route_preferences_profile
    ON model_route_preferences (profile_id);
