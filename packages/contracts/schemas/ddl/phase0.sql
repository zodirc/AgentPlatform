-- Phase 0 minimal schema. Apply via api migration tool (Alembic etc.) at implementation.
-- Authority: docs/contracts.md §7, docs/07-domain-model.md §7

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    default_scenario_id VARCHAR(32) NOT NULL DEFAULT 'writing',
    context_summary     JSONB,
    status              VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE turns (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID NOT NULL REFERENCES sessions(id),
    scenario_id         VARCHAR(32) NOT NULL,
    status              VARCHAR(32) NOT NULL DEFAULT 'pending',
    user_input          TEXT NOT NULL,
    client_request_id   UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, client_request_id)
);

CREATE INDEX idx_turns_session_id ON turns(session_id);

CREATE TABLE runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id             UUID NOT NULL UNIQUE REFERENCES turns(id),
    status              VARCHAR(32) NOT NULL DEFAULT 'accepted',
    termination_reason  VARCHAR(64),
    cancel_requested_at TIMESTAMPTZ,
    cancel_force        BOOLEAN NOT NULL DEFAULT false,
    runner_id           VARCHAR(128),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE turn_events (
    event_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    turn_id             UUID NOT NULL REFERENCES turns(id),
    stream_id           UUID NOT NULL,
    sequence            BIGINT NOT NULL,
    type                VARCHAR(64) NOT NULL,
    run_id              UUID NOT NULL REFERENCES runs(id),
    step_index          INTEGER NOT NULL DEFAULT 0,
    trace_id            UUID NOT NULL,
    causation_id        UUID,
    ts                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload             JSONB NOT NULL DEFAULT '{}',
    UNIQUE (turn_id, sequence)
);

CREATE INDEX idx_turn_events_turn_sequence ON turn_events(turn_id, sequence);

-- Phase 0+ NOTIFY trigger (apply at implementation). See docs/09-event-projection-pipeline.md §1, §6.0.
-- CREATE OR REPLACE FUNCTION notify_turn_event() RETURNS trigger AS $$
-- BEGIN
--   PERFORM pg_notify('turn_events_channel', NEW.turn_id::text);
--   RETURN NEW;
-- END;
-- $$ LANGUAGE plpgsql;
-- CREATE TRIGGER turn_events_notify AFTER INSERT ON turn_events
--   FOR EACH ROW EXECUTE FUNCTION notify_turn_event();

CREATE TABLE turn_views (
    turn_id                 UUID PRIMARY KEY REFERENCES turns(id),
    session_id              UUID NOT NULL REFERENCES sessions(id),
    scenario_id             VARCHAR(32) NOT NULL,
    status                  VARCHAR(32) NOT NULL,
    user_input              TEXT NOT NULL,
    latest_output           TEXT,
    tool_timeline           JSONB NOT NULL DEFAULT '[]',
    artifacts               JSONB NOT NULL DEFAULT '[]',
    last_event_sequence     BIGINT NOT NULL DEFAULT 0,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
