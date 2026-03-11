"""005 — phase 2 agent post fields on posts

Revision ID: 005
Revises: 004
Create Date: 2026-03-11
"""
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE posts
            ADD COLUMN IF NOT EXISTS agent_id UUID REFERENCES agents(agent_id)
    """)
    op.execute("""
        ALTER TABLE posts
            ADD COLUMN IF NOT EXISTS type TEXT
    """)
    op.execute("""
        ALTER TABLE posts
            ADD COLUMN IF NOT EXISTS topic TEXT
    """)
    op.execute("""
        ALTER TABLE posts
            ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_posts_agent_id
            ON posts(agent_id, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_posts_agent_id")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS confidence")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS topic")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS type")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS agent_id")
