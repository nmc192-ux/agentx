"""015 — add repost columns to posts table

Revision ID: 015
Revises: 014
Create Date: 2026-03-29
"""
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE posts
            ADD COLUMN IF NOT EXISTS repost_of_id UUID REFERENCES posts(post_id)
    """)
    op.execute("""
        ALTER TABLE posts
            ADD COLUMN IF NOT EXISTS is_quote_post BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        ALTER TABLE posts
            ADD COLUMN IF NOT EXISTS repost_count INT NOT NULL DEFAULT 0
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_posts_repost_of_id
            ON posts(repost_of_id)
        WHERE repost_of_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_posts_repost_of_id")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS repost_count")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS is_quote_post")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS repost_of_id")
