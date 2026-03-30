"""
Phase 25 — Full-Text Post Search
══════════════════════════════════
Adds a tsvector column and GIN index to posts for fast full-text search,
plus a trigger that auto-updates search_vector on insert/update from
title + content.
"""

from alembic import op

revision      = "034"
down_revision = "033"
branch_labels = None
depends_on    = None


def upgrade() -> None:

    # ── 1. Add search_vector column ───────────────────────────────────────────
    op.execute("""
        ALTER TABLE posts
            ADD COLUMN IF NOT EXISTS search_vector tsvector
    """)

    # ── 2. Backfill existing rows ─────────────────────────────────────────────
    op.execute("""
        UPDATE posts
        SET search_vector =
            setweight(to_tsvector('english', COALESCE(title, '')),   'A') ||
            setweight(to_tsvector('english', COALESCE(content, '')), 'B')
        WHERE search_vector IS NULL
    """)

    # ── 3. GIN index for fast searches ────────────────────────────────────────
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_posts_search
            ON posts USING GIN(search_vector)
    """)

    # ── 4. Trigger function: keep search_vector up-to-date ────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION posts_search_vector_update()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('english', COALESCE(NEW.title,   '')), 'A') ||
                setweight(to_tsvector('english', COALESCE(NEW.content, '')), 'B');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    # ── 5. Bind trigger to posts ───────────────────────────────────────────────
    op.execute("""
        DROP TRIGGER IF EXISTS trg_posts_search_vector ON posts
    """)
    op.execute("""
        CREATE TRIGGER trg_posts_search_vector
        BEFORE INSERT OR UPDATE OF title, content
        ON posts
        FOR EACH ROW
        EXECUTE FUNCTION posts_search_vector_update()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_posts_search_vector ON posts")
    op.execute("DROP FUNCTION IF EXISTS posts_search_vector_update()")
    op.execute("DROP INDEX IF EXISTS idx_posts_search")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS search_vector")
