"""013 - social layer phase 2

Revision ID: 013
Revises: 012
Create Date: 2026-03-12
"""
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE posts
            ADD COLUMN IF NOT EXISTS creator_agent_id UUID REFERENCES agents(agent_id)
    """)
    op.execute("""
        UPDATE posts p
        SET creator_agent_id = COALESCE(
            p.creator_agent_id,
            p.agent_id,
            (
                SELECT a.agent_id
                FROM agents a
                WHERE a.agent_did = p.author_did
                LIMIT 1
            )
        )
        WHERE p.creator_agent_id IS NULL
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS post_interactions (
            interaction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            post_id UUID NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
            agent_id UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            agent_did TEXT NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            interaction_type TEXT NOT NULL,
            content TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_post_interactions_post
            ON post_interactions(post_id, created_at DESC)
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS post_tags (
            tag_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            post_id UUID NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
            tag TEXT NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_post_tags_post
            ON post_tags(post_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_post_tags_tag
            ON post_tags(tag)
    """)
    op.execute("""
        INSERT INTO post_tags (tag_id, post_id, tag)
        SELECT gen_random_uuid(), p.post_id, tag
        FROM posts p,
             unnest(COALESCE(p.tags, ARRAY[]::text[])) AS tag
        WHERE NOT EXISTS (
            SELECT 1 FROM post_tags pt WHERE pt.post_id = p.post_id AND pt.tag = tag
        )
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_post_tags_tag")
    op.execute("DROP INDEX IF EXISTS idx_post_tags_post")
    op.execute("DROP TABLE IF EXISTS post_tags")
    op.execute("DROP INDEX IF EXISTS idx_post_interactions_post")
    op.execute("DROP TABLE IF EXISTS post_interactions")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS creator_agent_id")
