-- Enable pgvector for optional RETRIEVAL_BACKEND=pgvector (docs/17 S3 A10).
-- Runs only on first DB init; store.ensure_schema() also CREATE EXTENSION IF NOT EXISTS.
CREATE EXTENSION IF NOT EXISTS vector;
