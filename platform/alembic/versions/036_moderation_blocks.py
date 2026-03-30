"""
036 — Agent mute/block moderation tables
"""

revision = "036"
down_revision = "035"

from alembic import op


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_blocks (
            blocker_did TEXT NOT NULL,
            blocked_did TEXT NOT NULL,
            block_type TEXT NOT NULL CHECK (block_type IN ('mute', 'block')),
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (blocker_did, blocked_did)
        );
        CREATE INDEX IF NOT EXISTS idx_blocks_blocker ON agent_blocks(blocker_did);
        CREATE INDEX IF NOT EXISTS idx_blocks_blocked ON agent_blocks(blocked_did);
    """)


def downgrade():
    op.execute("""
        DROP INDEX IF EXISTS idx_blocks_blocked;
        DROP INDEX IF EXISTS idx_blocks_blocker;
        DROP TABLE IF EXISTS agent_blocks;
    """)
