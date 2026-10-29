-- Written in the same transaction that deletes the works row.
-- The work directory on disk is not removed here.

CREATE TABLE IF NOT EXISTS work_tombstones (
    work_id     UUID PRIMARY KEY,
    deleted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
