-- Pull claim restores structured writing intents (accept/reject patch, ponds, plan).

ALTER TABLE turns
    ADD COLUMN IF NOT EXISTS intent JSONB;
