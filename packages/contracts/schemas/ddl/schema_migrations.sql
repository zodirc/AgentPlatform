-- Migration version ledger (api service applies DDL; see services/api/app/db/migrate.py).
CREATE TABLE IF NOT EXISTS schema_migrations (
    name VARCHAR(128) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
