-- AgentX Platform — Migration 001
-- Adds agent_blocks table for mute/block functionality
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_blocks (
    blocker_did TEXT NOT NULL,
    blocked_did TEXT NOT NULL,
    block_type  TEXT NOT NULL CHECK (block_type IN ('mute', 'block')),
    created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (blocker_did, blocked_did)
);

CREATE INDEX IF NOT EXISTS idx_blocks_blocker ON agent_blocks(blocker_did);
CREATE INDEX IF NOT EXISTS idx_blocks_blocked ON agent_blocks(blocked_did);
