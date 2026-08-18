-- Duplicate of UNIQUE (turn_id, sequence). Drop CONCURRENTLY (no txn).
-- Alembic 0025 uses autocommit_block.
DROP INDEX CONCURRENTLY IF EXISTS idx_turn_events_turn_sequence;
