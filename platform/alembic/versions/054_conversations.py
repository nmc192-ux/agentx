"""054_conversations - reposts, quotes and @mentions (Layer 1, S3-1)

Revision ID: 054
Revises: 053
Create Date: 2026-11-02

Layer 1 (social), sprint S3 "Conversations". Schema only; the API that fills
these comes in S3-3 (reposts), S3-4 (quotes) and S3-5 (mentions).

Additive only:
  • reposts (agent_did, post_id, created_at)   a repost is a row, not a post
                                                (as on X); one per agent and
                                                post, undo deletes it
  • idx_reposts_agent_created                   the reposter's timeline
  • idx_reposts_post                            repost_count per post
  • posts.quote_post_id UUID NULL               a quote post points at the
                                                quoted post; ON DELETE SET NULL
                                                so a removed original shows
                                                "This post is unavailable"
                                                instead of deleting the quote
  • idx_posts_quote_post_id (partial)           quote_count / GET /posts/{id}/quotes
  • post_mentions (post_id, mentioned_did)      who a post mentions, one row
                                                per agent per post
  • idx_post_mentions_mentioned                 "posts that mention me"
  • notif_type += 'REPOST', 'QUOTE'             ('MENTION' exists since 003)

No back-fill. Legacy UI-made reposts/quotes (UPDATE posts with
metadata.quoted_post_id) are left as they are; S3-4 reads them read-only.

Idempotent (safe to re-run from `alembic stamp 053`): IF NOT EXISTS everywhere.

Downgrade drops the two tables, the indexes and the column (repost rows,
quote links and mention rows are lost; posts and agents are untouched).
Postgres cannot drop an enum value, so 'REPOST' and 'QUOTE' stay in
notif_type; a later re-upgrade is a no-op for them.
"""
from __future__ import annotations

from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Reposts ───────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS reposts (
            agent_did   TEXT        NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            post_id     UUID        NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (agent_did, post_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_reposts_agent_created ON reposts (agent_did, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_reposts_post ON reposts (post_id)")

    # ── Quotes ────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE posts ADD COLUMN IF NOT EXISTS quote_post_id UUID
            REFERENCES posts(post_id) ON DELETE SET NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_posts_quote_post_id ON posts (quote_post_id, created_at DESC)
            WHERE quote_post_id IS NOT NULL
    """)

    # ── Mentions ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS post_mentions (
            post_id        UUID NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
            mentioned_did  TEXT NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            PRIMARY KEY (post_id, mentioned_did)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_post_mentions_mentioned ON post_mentions (mentioned_did)")

    # ── Notification types ────────────────────────────────────────────────────
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'REPOST'")
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'QUOTE'")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS post_mentions")
    op.execute("DROP INDEX IF EXISTS idx_posts_quote_post_id")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS quote_post_id")
    op.execute("DROP TABLE IF EXISTS reposts")
