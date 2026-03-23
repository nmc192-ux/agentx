"""Add ACP envelope columns to agent_messages.

Revision ID: 034
Revises:     033
"""
from __future__ import annotations

from alembic import op

revision      = "034"
down_revision = "033"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # Add ACP-1.0 envelope columns to existing agent_messages table.
    # All columns are nullable for backwards-compat with rows written before
    # ACP enforcement (migration 022).  New rows will always carry all fields.
    op.execute("""
        ALTER TABLE agent_messages
            ADD COLUMN IF NOT EXISTS protocol_version TEXT    DEFAULT 'ACP-1.0',
            ADD COLUMN IF NOT EXISTS acp_message_id   UUID,
            ADD COLUMN IF NOT EXISTS acp_timestamp    TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS agent_id         TEXT,
            ADD COLUMN IF NOT EXISTS acp_type         TEXT,
            ADD COLUMN IF NOT EXISTS human_summary    TEXT,
            ADD COLUMN IF NOT EXISTS machine_payload  JSONB
    """)

    # Index on acp_type for efficient querying by message type
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'agent_messages'
                  AND indexname = 'ix_agent_messages_acp_type'
            ) THEN
                CREATE INDEX ix_agent_messages_acp_type
                    ON agent_messages(acp_type, created_at DESC);
            END IF;
        END $$
    """)

    # Index on acp_message_id for deduplication lookups
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'agent_messages'
                  AND indexname = 'ix_agent_messages_acp_message_id'
            ) THEN
                CREATE UNIQUE INDEX ix_agent_messages_acp_message_id
                    ON agent_messages(acp_message_id)
                    WHERE acp_message_id IS NOT NULL;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agent_messages_acp_type")
    op.execute("DROP INDEX IF EXISTS ix_agent_messages_acp_message_id")
    op.execute("""
        ALTER TABLE agent_messages
            DROP COLUMN IF EXISTS protocol_version,
            DROP COLUMN IF EXISTS acp_message_id,
            DROP COLUMN IF EXISTS acp_timestamp,
            DROP COLUMN IF EXISTS agent_id,
            DROP COLUMN IF EXISTS acp_type,
            DROP COLUMN IF EXISTS human_summary,
            DROP COLUMN IF EXISTS machine_payload
    """)
