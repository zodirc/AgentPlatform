-- Phase 2: pull start context (ops isolation + plan_phase persistence).
-- pull_eligible=false → HTTP push-start only (ops_eval / model_override).
-- turns.plan_phase → pull claim can restore Web planning/executing.

ALTER TABLE runs
    ADD COLUMN IF NOT EXISTS pull_eligible BOOLEAN NOT NULL DEFAULT true;

CREATE INDEX IF NOT EXISTS idx_runs_pull_claimable
    ON runs (created_at ASC)
    WHERE status = 'accepted' AND pull_eligible;

ALTER TABLE turns
    ADD COLUMN IF NOT EXISTS plan_phase VARCHAR(32);

-- Soft-disable golden placeholder as __system active profile so accidental
-- pull/fallback paths do not call OpenAI with sk-eval-test-key-0001.
UPDATE model_provider_profiles
SET is_active = false, updated_at = now()
WHERE owner_user_id = '00000000-0000-4000-8000-000000000099'
  AND label = 'eval-openai'
  AND is_active;

-- Prefer a non-eval __system profile when one exists (e.g. deepseek「默认」).
UPDATE model_provider_profiles p
SET is_active = true, updated_at = now()
WHERE p.id = (
    SELECT id
    FROM model_provider_profiles
    WHERE owner_user_id = '00000000-0000-4000-8000-000000000099'
      AND label IS DISTINCT FROM 'eval-openai'
    ORDER BY
        CASE WHEN provider = 'deepseek' THEN 0 ELSE 1 END,
        updated_at DESC
    LIMIT 1
)
AND NOT EXISTS (
    SELECT 1
    FROM model_provider_profiles
    WHERE owner_user_id = '00000000-0000-4000-8000-000000000099'
      AND is_active
);
