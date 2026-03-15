"""022_agent_bus - Agent Bus

Revision ID: 022
Revises: 021
Create Date: 2026-03-15

Adds the Agent Bus messaging layer: direct agent-to-agent messages
(separate from the legacy /messages system), named channels, and
session tracking for stream connections.
"""

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------- agent_messages
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_messages (
            message_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            sender_did    TEXT        NOT NULL,
            sender_id     UUID        REFERENCES agents(agent_id) ON DELETE SET NULL,
            receiver_did  TEXT        NOT NULL,
            receiver_id   UUID        REFERENCES agents(agent_id) ON DELETE SET NULL,
            content       TEXT        NOT NULL,
            channel       TEXT        NOT NULL DEFAULT 'default',
            metadata      JSONB,
            status        TEXT        NOT NULL DEFAULT 'sent',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'agent_messages'
                  AND indexname = 'ix_agent_messages_receiver_did'
            ) THEN
                CREATE INDEX ix_agent_messages_receiver_did
                    ON agent_messages(receiver_did, created_at DESC);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'agent_messages'
                  AND indexname = 'ix_agent_messages_sender_did'
            ) THEN
                CREATE INDEX ix_agent_messages_sender_did
                    ON agent_messages(sender_did, created_at DESC);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'agent_messages'
                  AND indexname = 'ix_agent_messages_channel'
            ) THEN
                CREATE INDEX ix_agent_messages_channel
                    ON agent_messages(channel, created_at DESC);
            END IF;
        END $$
    """)

    # -------------------------------------------------------- agent_channels
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_channels (
            channel_id   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            name         TEXT        NOT NULL UNIQUE,
            description  TEXT,
            created_by   TEXT        NOT NULL,
            creator_id   UUID        REFERENCES agents(agent_id) ON DELETE SET NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'agent_channels'
                  AND indexname = 'ix_agent_channels_name'
            ) THEN
                CREATE INDEX ix_agent_channels_name ON agent_channels(name);
            END IF;
        END $$
    """)

    # -------------------------------------------------------- agent_sessions
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_sessions (
            session_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_did      TEXT        NOT NULL,
            agent_id       UUID        REFERENCES agents(agent_id) ON DELETE SET NULL,
            session_token  TEXT        NOT NULL UNIQUE,
            connected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at     TIMESTAMPTZ,
            is_active      BOOLEAN     NOT NULL DEFAULT TRUE
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'agent_sessions'
                  AND indexname = 'ix_agent_sessions_agent_did'
            ) THEN
                CREATE INDEX ix_agent_sessions_agent_did
                    ON agent_sessions(agent_did, is_active);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'agent_sessions'
                  AND indexname = 'ix_agent_sessions_token'
            ) THEN
                CREATE INDEX ix_agent_sessions_token ON agent_sessions(session_token);
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_channels CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_messages CASCADE")
