"""
035 — Nested threading: add root_post_id, depth to posts
"""

revision = "035"
down_revision = "034"

from alembic import op


def upgrade():
    op.execute("""
        ALTER TABLE posts ADD COLUMN IF NOT EXISTS root_post_id UUID REFERENCES posts(post_id);
        ALTER TABLE posts ADD COLUMN IF NOT EXISTS depth INT DEFAULT 0;
        CREATE INDEX IF NOT EXISTS idx_posts_root ON posts(root_post_id) WHERE root_post_id IS NOT NULL;
    """)


def downgrade():
    op.execute("""
        DROP INDEX IF EXISTS idx_posts_root;
        ALTER TABLE posts DROP COLUMN IF EXISTS depth;
        ALTER TABLE posts DROP COLUMN IF EXISTS root_post_id;
    """)
