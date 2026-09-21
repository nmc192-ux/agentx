"""007 — agent messages DID fix

Revision ID: 007
Revises: 006
Create Date: 2026-03-12
"""
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reconciliation (Sep 2026): backfills are guarded so this is a no-op on the
    # DID-based init-db.sql baseline, which never had the *_agent_id columns.
    op.execute("""
        ALTER TABLE messages
            ADD COLUMN IF NOT EXISTS sender_agent_did TEXT
    """)
    op.execute("""
        ALTER TABLE messages
            ADD COLUMN IF NOT EXISTS receiver_agent_did TEXT
    """)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = 'messages'
                         AND column_name = 'sender_agent_id') THEN
                UPDATE messages m SET sender_agent_did = a.agent_did FROM agents a WHERE m.sender_agent_id = a.agent_id AND m.sender_agent_did IS NULL;
            END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_schema = 'public' AND table_name = 'messages'
                         AND column_name = 'receiver_agent_id') THEN
                UPDATE messages m SET receiver_agent_did = a.agent_did FROM agents a WHERE m.receiver_agent_id = a.agent_id AND m.receiver_agent_did IS NULL;
            END IF;
        END $$
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_did
            ON messages(sender_agent_did, receiver_agent_did, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_messages_did")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS receiver_agent_did")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS sender_agent_did")
