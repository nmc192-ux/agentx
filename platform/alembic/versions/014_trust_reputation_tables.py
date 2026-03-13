"""014 — trust reputation tables

Revision ID: 014
Revises: 013
Create Date: 2026-03-13
"""
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trust_scores (
            agent_id UUID PRIMARY KEY REFERENCES agents(agent_id) ON DELETE CASCADE,
            current_score DOUBLE PRECISION NOT NULL DEFAULT 0.5,
            last_updated TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        ALTER TABLE trust_events
        ADD COLUMN IF NOT EXISTS agent_did TEXT
        """
    )
    op.execute(
        """
        ALTER TABLE trust_events
        ADD COLUMN IF NOT EXISTS event_weight DOUBLE PRECISION
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_reputation_history (
            history_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            score_before DOUBLE PRECISION NOT NULL,
            score_after DOUBLE PRECISION NOT NULL,
            event_id UUID NOT NULL REFERENCES trust_events(event_id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_reputation_history_agent
            ON agent_reputation_history(agent_id, created_at DESC)
        """
    )
    op.execute(
        """
        UPDATE trust_events
        SET event_weight = COALESCE(event_weight, event_value)
        WHERE event_weight IS NULL
        """
    )
    op.execute(
        """
        UPDATE trust_events te
        SET agent_did = a.agent_did
        FROM agents a
        WHERE a.agent_id = te.agent_id
          AND te.agent_did IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO trust_scores (agent_id, current_score, last_updated)
        SELECT
            agent_id,
            COALESCE(trust_score, 0.5),
            CURRENT_TIMESTAMP
        FROM agents
        ON CONFLICT (agent_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_agent_reputation_history_agent")
    op.execute("DROP TABLE IF EXISTS agent_reputation_history")
    op.execute("DROP TABLE IF EXISTS trust_scores")
    op.execute("ALTER TABLE trust_events DROP COLUMN IF EXISTS event_weight")
    op.execute("ALTER TABLE trust_events DROP COLUMN IF EXISTS agent_did")
