-- O7 / WP3: turn_events retention helpers (partition conversion is conditional in alembic).
-- Stream fine-grained events are short-lived; structural events keep longer.

COMMENT ON TABLE turn_events IS
  'Retention: stream deltas (turn.thinking.delta/turn.token/tool.delta/section.draft.delta) 7d after terminal; structural 90d (backend-scaling O7)';
