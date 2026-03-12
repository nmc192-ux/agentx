"""010 — reputation engine

Revision ID: 010
Revises: 009
Create Date: 2026-03-12
"""
from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS trust_events (
            event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id UUID REFERENCES agents(agent_id),
            agent_did TEXT,
            event_type TEXT NOT NULL,
            event_value DOUBLE PRECISION NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_trust_agent
            ON trust_events(agent_did, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_trust_agent")
    op.execute("DROP TABLE IF EXISTS trust_events")
