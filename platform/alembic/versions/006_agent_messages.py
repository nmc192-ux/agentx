"""006 — agent messages

Revision ID: 006
Revises: 005
Create Date: 2026-03-11
"""
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            sender_agent_id UUID NOT NULL REFERENCES agents(agent_id),
            receiver_agent_id UUID NOT NULL REFERENCES agents(agent_id),
            message TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Reconciliation (Sep 2026): the init-db.sql baseline already has a
    # DID-based `messages` table without sender_agent_id, so the CREATE TABLE
    # above is a no-op there. Only build the legacy index when the column exists.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = 'messages'
                         AND column_name = 'sender_agent_id') THEN
                CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(sender_agent_id, receiver_agent_id, created_at DESC);
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_messages_agent")
    op.execute("DROP TABLE IF EXISTS messages")
