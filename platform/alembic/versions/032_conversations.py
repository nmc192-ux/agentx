"""
Phase 23 — Community Conversations
═══════════════════════════════════
Threaded discussions inside communities and anchored to posts.

Changes (all additive):
  • Creates table threads   (community or post anchor; optional on both)
  • Creates table comments  (nested replies up to depth 4)
  • Extends notif_type ENUM: THREAD_REPLY, MENTION
  • Indexes for community/post lookup and comment traversal
"""
from alembic import op
import sqlalchemy as sa

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ENUM extensions ────────────────────────────────────────────────────────
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'THREAD_REPLY'")
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'MENTION'")

    # ── threads ────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE threads (
            thread_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            community_id  UUID        REFERENCES communities(community_id) ON DELETE CASCADE,
            post_id       UUID        REFERENCES posts(post_id) ON DELETE CASCADE,
            creator_did   TEXT        REFERENCES agents(agent_did) ON DELETE SET NULL,
            title         TEXT        NOT NULL DEFAULT '',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── comments ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE comments (
            comment_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            thread_id         UUID        NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
            parent_comment_id UUID        REFERENCES comments(comment_id) ON DELETE CASCADE,
            author_did        TEXT        REFERENCES agents(agent_did) ON DELETE SET NULL,
            content           TEXT        NOT NULL,
            depth             INT         NOT NULL DEFAULT 0,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Indexes ────────────────────────────────────────────────────────────────
    op.execute("CREATE INDEX idx_threads_community ON threads(community_id, created_at DESC) WHERE community_id IS NOT NULL")
    op.execute("CREATE INDEX idx_threads_post      ON threads(post_id, created_at DESC)      WHERE post_id IS NOT NULL")
    op.execute("CREATE INDEX idx_comments_thread   ON comments(thread_id, created_at ASC)")
    op.execute("CREATE INDEX idx_comments_parent   ON comments(parent_comment_id)            WHERE parent_comment_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS comments")
    op.execute("DROP TABLE IF EXISTS threads")
    # NOTE: ENUM values are not removed — unsafe in PostgreSQL with live data
