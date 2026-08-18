-- Duplicate of UNIQUE (turn_id, sequence).
-- Transactional DROP (API Alembic runs inside begin_transaction).
-- Widen alembic_version.version_num first: revision ids can exceed varchar(32).
ALTER TABLE alembic_version ALTER COLUMN version_num TYPE varchar(64);
DROP INDEX IF EXISTS idx_turn_events_turn_sequence;
