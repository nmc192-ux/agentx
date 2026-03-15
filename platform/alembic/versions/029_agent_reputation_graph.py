"""029 — Agent Reputation Graph

Phase 20: Agent Reputation Graph

Tracks pairwise trust relationships between agents based on economic
interactions (task completions, contract collaborations, verifications).

New table: agent_reputation_graph
  graph_id         — surrogate PK
  agent_id         — the agent whose perspective this edge belongs to
  peer_agent_id    — the collaborator / counterparty
  trust_weight     — computed edge weight in [0.0, 1.0] (higher = more trusted)
  interaction_count — raw count of interactions between the pair
  last_interaction — timestamp of the most recent interaction
  created_at       — row creation timestamp
  UNIQUE(agent_id, peer_agent_id) — one edge per ordered pair

Revision ID: 029
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_reputation_graph (
            graph_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id          UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            peer_agent_id     UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            trust_weight      FLOAT   NOT NULL DEFAULT 0.0,
            interaction_count INTEGER NOT NULL DEFAULT 0,
            last_interaction  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_agent_peer UNIQUE (agent_id, peer_agent_id),
            CONSTRAINT chk_different_agents CHECK (agent_id <> peer_agent_id),
            CONSTRAINT chk_trust_weight_range CHECK (trust_weight >= 0.0 AND trust_weight <= 1.0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_rep_graph_agent_id
            ON agent_reputation_graph (agent_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_rep_graph_peer_id
            ON agent_reputation_graph (peer_agent_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_rep_graph_trust_weight
            ON agent_reputation_graph (agent_id, trust_weight DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_reputation_graph CASCADE")
