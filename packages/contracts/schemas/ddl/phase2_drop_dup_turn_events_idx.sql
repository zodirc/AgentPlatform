-- Duplicate of UNIQUE (turn_id, sequence).
-- Transactional DROP (API Alembic runs inside begin_transaction).
-- Alembic 0025 runs these as two op.execute calls.
ALTER TABLE alembic_version ALTER COLUMN version_num TYPE varchar(64);
DROP INDEX IF EXISTS idx_turn_events_turn_sequence;
