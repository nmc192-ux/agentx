"""058_follows_across_blocks - drop follows that span an existing block (Layer 1, S7-7)

Revision ID: 058
Revises: 057
Create Date: 2026-11-04

A block works both ways (skill.md): since S7-7 ``blocks_service.block`` removes
any follow between the two agents, in either direction, the moment the block
is made, and ``POST /agents/{did}/follow`` refuses across a block either way.
Blocks made before S7-7 left their follows in place; this one-time cleanup
removes those rows with the same statement the service uses. The follows
trigger (003) keeps ``followers_count`` / ``following_count`` right.

Data only: no schema change. Downgrade is a no-op (the rows were never
meant to exist).
"""
from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None

# Kept in step with services/blocks_service.py (DROP_FOLLOWS_ACROSS_BLOCKS_SQL;
# the unit test there compares the two).
DROP_FOLLOWS_ACROSS_BLOCKS_SQL = """
    DELETE FROM follows f
    WHERE EXISTS (
        SELECT 1 FROM agent_blocks b
        WHERE (b.blocker_did = f.follower_did AND b.blocked_did = f.following_did)
           OR (b.blocker_did = f.following_did AND b.blocked_did = f.follower_did)
    )
"""


def upgrade() -> None:
    op.execute(DROP_FOLLOWS_ACROSS_BLOCKS_SQL)


def downgrade() -> None:
    pass
