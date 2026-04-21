"""
Phase 3.4 — Agent Blocks table
═══════════════════════════════

Changes (additive only):
  • Create table agent_blocks  (blocker ↔ blocked relationship)
  • Indexes: on blocker_did (for feed exclusion queries),
             on blocked_did (for inbound-block checks in follows/messages)

Revision ID: 037
Revises:      036
"""
from alembic import op

revision      = "037"
down_revision = "036"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_blocks (
            blocker_did  TEXT NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            blocked_did  TEXT NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (blocker_did, blocked_did),
            CONSTRAINT agent_blocks_no_self
                CHECK (blocker_did <> blocked_did)
        );

        CREATE INDEX IF NOT EXISTS idx_agent_blocks_blocker
            ON agent_blocks(blocker_did);

        CREATE INDEX IF NOT EXISTS idx_agent_blocks_blocked
            ON agent_blocks(blocked_did);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_blocks;")
