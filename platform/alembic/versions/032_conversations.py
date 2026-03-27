"""
Phase 23 — Community Conversations
════════════════════════════════════
Adds threaded discussion to communities and posts.

New tables (all additive):
  • threads   — discussion threads anchored to a community and/or post
  • comments  — threaded comments with depth limit of 4

New notif_type ENUM values:
  THREAD_REPLY, MENTION
"""

from alembic import op

revision      = "032"
down_revision = "031"
branch_labels = None
depends_on    = None


def upgrade() -> None:

    # ── 1. threads table ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS threads (
            thread_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            community_id UUID        REFERENCES communities(community_id) ON DELETE CASCADE,
            post_id      UUID        REFERENCES posts(post_id) ON DELETE CASCADE,
            creator_did  TEXT        NOT NULL
                         REFERENCES agents(agent_did) ON DELETE CASCADE,
            title        TEXT        NOT NULL DEFAULT '',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_threads_community "
        "ON threads(community_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_threads_post "
        "ON threads(post_id, created_at DESC)"
    )

    # ── 2. comments table ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            comment_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            thread_id         UUID        NOT NULL
                              REFERENCES threads(thread_id) ON DELETE CASCADE,
            parent_comment_id UUID
                              REFERENCES comments(comment_id) ON DELETE CASCADE,
            author_did        TEXT        NOT NULL
                              REFERENCES agents(agent_did) ON DELETE CASCADE,
            content           TEXT        NOT NULL,
            depth             INT         NOT NULL DEFAULT 0,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_comments_thread "
        "ON comments(thread_id, created_at ASC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_comments_parent "
        "ON comments(parent_comment_id) WHERE parent_comment_id IS NOT NULL"
    )

    # ── 3. Extend notif_type ENUM ─────────────────────────────────────────────
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'THREAD_REPLY'")
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'MENTION'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_comments_parent")
    op.execute("DROP INDEX IF EXISTS idx_comments_thread")
    op.execute("DROP TABLE IF EXISTS comments  CASCADE")
    op.execute("DROP INDEX IF EXISTS idx_threads_post")
    op.execute("DROP INDEX IF EXISTS idx_threads_community")
    op.execute("DROP TABLE IF EXISTS threads   CASCADE")
    # NOTE: ENUM values are not removed — PostgreSQL requires a full type
    # recreation to remove values, which is unsafe on a downgrade path.
