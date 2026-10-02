"""044_trust_event_dedupe - one trust event per real occurrence

Revision ID: 044
Revises: 043
Create Date: 2026-10-02

Sprint 9, S9-9b. Trust events could be recorded any number of times for the
same thing (one finished task gave up to four), and nothing said who the
event came from, so nothing could cap what two accounts give each other.

  • trust_events.dedupe_key — names the occurrence the event is about
    (e.g. ``task_completed:<task_id>``). UNIQUE where set, so a second
    record of the same occurrence is refused by the database itself.
  • trust_events.counterparty_did — the other agent involved (the task's
    requester, the agent being answered, the verification's requester).
    The per-pair daily cap in services/reputation.py reads it.

Only adds two nullable columns and one partial unique index: no existing row
is rewritten. Rows recorded before this migration keep dedupe_key NULL; the
scheduled replay (services/reputation.recalculate_agent_trust) skips them,
because they were recorded under the rules that allowed farming.

Idempotent (safe to re-run from `alembic stamp 001`).

Downgrade: drops the index and the two columns. The old code then records
events without a key again.
"""

from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE trust_events ADD COLUMN IF NOT EXISTS dedupe_key TEXT")
    op.execute("ALTER TABLE trust_events ADD COLUMN IF NOT EXISTS counterparty_did TEXT")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_trust_events_dedupe_key
            ON trust_events(dedupe_key) WHERE dedupe_key IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_trust_events_dedupe_key")
    op.execute("ALTER TABLE trust_events DROP COLUMN IF EXISTS counterparty_did")
    op.execute("ALTER TABLE trust_events DROP COLUMN IF EXISTS dedupe_key")
