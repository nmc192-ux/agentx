"""
Phase 24 — Hashtag Indexing
═══════════════════════════
Adds hashtag tables for indexing and trending:

New tables (all additive):
  • hashtags       — canonical hashtag registry with post counts
  • post_hashtags  — many-to-many link between posts and hashtags
"""

from alembic import op

revision      = "033"
down_revision = "032"
branch_labels = None
depends_on    = None


def upgrade() -> None:

    # ── 1. hashtags table ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS hashtags (
            hashtag_id   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tag          TEXT        UNIQUE NOT NULL,
            post_count   INT         NOT NULL DEFAULT 0,
            last_used_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_hashtags_tag "
        "ON hashtags(tag)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_hashtags_post_count "
        "ON hashtags(post_count DESC, last_used_at DESC)"
    )

    # ── 2. post_hashtags join table ───────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS post_hashtags (
            post_id    UUID NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
            hashtag_id UUID NOT NULL REFERENCES hashtags(hashtag_id) ON DELETE CASCADE,
            PRIMARY KEY (post_id, hashtag_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_post_hashtags_post "
        "ON post_hashtags(post_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_post_hashtags_hashtag "
        "ON post_hashtags(hashtag_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_post_hashtags_hashtag")
    op.execute("DROP INDEX IF EXISTS idx_post_hashtags_post")
    op.execute("DROP TABLE IF EXISTS post_hashtags CASCADE")
    op.execute("DROP INDEX IF EXISTS idx_hashtags_post_count")
    op.execute("DROP INDEX IF EXISTS idx_hashtags_tag")
    op.execute("DROP TABLE IF EXISTS hashtags CASCADE")
