"""turn_events NOTIFY trigger"""

from alembic import op

revision = "0005_notify_trigger"
down_revision = "0004_phase2_outbox"
branch_labels = None
depends_on = None

NOTIFY_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION notify_turn_event() RETURNS trigger AS $$
BEGIN
  PERFORM pg_notify('turn_events_channel', NEW.turn_id::text);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS turn_events_notify ON turn_events;
CREATE TRIGGER turn_events_notify
  AFTER INSERT ON turn_events
  FOR EACH ROW EXECUTE FUNCTION notify_turn_event();
"""


def upgrade() -> None:
    op.execute(NOTIFY_TRIGGER_SQL)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS turn_events_notify ON turn_events;")
