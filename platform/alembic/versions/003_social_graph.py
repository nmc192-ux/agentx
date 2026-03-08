"""003 — Social graph: follows, post_likes, notifications

Revision ID: 003
Revises: 002
Create Date: 2026-03-08

Adds the three tables that power AgentX as a Twitter/X-style social network:
  - follows         — agent-to-agent social graph (follower/following)
  - post_likes      — per-post heart/like reactions
  - notifications   — FOLLOW, LIKE, REPLY, MENTION, TASK_ASSIGNED events

Also adds denormalized count columns:
  - agents.followers_count / following_count
  - posts.like_count / reply_count

And opens agent self-registration (tracked in comment — gate removed in agents.py).

Note: Each op.execute() call contains a single SQL statement to satisfy
the asyncpg driver requirement (no multi-command prepared statements).
"""
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Follows table ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS follows (
            follower_did  TEXT NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            following_did TEXT NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (follower_did, following_did),
            CONSTRAINT no_self_follow CHECK (follower_did != following_did)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_follows_follower
            ON follows(follower_did)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_follows_following
            ON follows(following_did)
    """)

    # ── Post likes table ───────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS post_likes (
            post_id    UUID NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
            agent_did  TEXT NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (post_id, agent_did)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_post_likes_post
            ON post_likes(post_id)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_post_likes_agent
            ON post_likes(agent_did)
    """)

    # ── Notifications: create ENUM type (idempotent via DO block) ──────────────
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'notif_type') THEN
                CREATE TYPE notif_type AS ENUM (
                    'FOLLOW', 'LIKE', 'REPLY', 'MENTION', 'TASK_ASSIGNED'
                );
            END IF;
        END $$
    """)

    # ── Notifications table ────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            notif_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            to_did      TEXT        NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            from_did    TEXT        REFERENCES agents(agent_did) ON DELETE SET NULL,
            notif_type  notif_type  NOT NULL,
            ref_post_id UUID        REFERENCES posts(post_id) ON DELETE CASCADE,
            is_read     BOOLEAN     NOT NULL DEFAULT false,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_notifs_to_unread
            ON notifications(to_did, is_read, created_at DESC)
    """)

    # ── Denormalized counts on agents ──────────────────────────────────────────
    op.execute("""
        ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS followers_count INT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS following_count INT NOT NULL DEFAULT 0
    """)

    # ── Denormalized counts on posts ───────────────────────────────────────────
    op.execute("""
        ALTER TABLE posts
            ADD COLUMN IF NOT EXISTS like_count  INT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS reply_count INT NOT NULL DEFAULT 0
    """)

    # ── Backfill reply_count from existing posts ───────────────────────────────
    op.execute("""
        UPDATE posts p
        SET reply_count = (
            SELECT COUNT(*) FROM posts r WHERE r.parent_post_id = p.post_id
        )
        WHERE EXISTS (
            SELECT 1 FROM posts r WHERE r.parent_post_id = p.post_id
        )
    """)

    # ── Trigger function: agents follower/following counts ─────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION trg_follows_counts()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                UPDATE agents SET followers_count = followers_count + 1
                    WHERE agent_did = NEW.following_did;
                UPDATE agents SET following_count = following_count + 1
                    WHERE agent_did = NEW.follower_did;
            ELSIF TG_OP = 'DELETE' THEN
                UPDATE agents SET followers_count = GREATEST(0, followers_count - 1)
                    WHERE agent_did = OLD.following_did;
                UPDATE agents SET following_count = GREATEST(0, following_count - 1)
                    WHERE agent_did = OLD.follower_did;
            END IF;
            RETURN NULL;
        END;
        $$
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_follows_counts ON follows")

    op.execute("""
        CREATE TRIGGER trg_follows_counts
            AFTER INSERT OR DELETE ON follows
            FOR EACH ROW EXECUTE FUNCTION trg_follows_counts()
    """)

    # ── Trigger function: posts like count ────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION trg_post_likes_count()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                UPDATE posts SET like_count = like_count + 1 WHERE post_id = NEW.post_id;
            ELSIF TG_OP = 'DELETE' THEN
                UPDATE posts SET like_count = GREATEST(0, like_count - 1) WHERE post_id = OLD.post_id;
            END IF;
            RETURN NULL;
        END;
        $$
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_post_likes_count ON post_likes")

    op.execute("""
        CREATE TRIGGER trg_post_likes_count
            AFTER INSERT OR DELETE ON post_likes
            FOR EACH ROW EXECUTE FUNCTION trg_post_likes_count()
    """)

    # ── Trigger function: posts reply count ───────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION trg_reply_count()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' AND NEW.parent_post_id IS NOT NULL THEN
                UPDATE posts SET reply_count = reply_count + 1
                    WHERE post_id = NEW.parent_post_id;
            ELSIF TG_OP = 'DELETE' AND OLD.parent_post_id IS NOT NULL THEN
                UPDATE posts SET reply_count = GREATEST(0, reply_count - 1)
                    WHERE post_id = OLD.parent_post_id;
            END IF;
            RETURN NULL;
        END;
        $$
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_reply_count ON posts")

    op.execute("""
        CREATE TRIGGER trg_reply_count
            AFTER INSERT OR DELETE ON posts
            FOR EACH ROW EXECUTE FUNCTION trg_reply_count()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_reply_count ON posts")
    op.execute("DROP TRIGGER IF EXISTS trg_post_likes_count ON post_likes")
    op.execute("DROP TRIGGER IF EXISTS trg_follows_counts ON follows")
    op.execute("DROP FUNCTION IF EXISTS trg_reply_count()")
    op.execute("DROP FUNCTION IF EXISTS trg_post_likes_count()")
    op.execute("DROP FUNCTION IF EXISTS trg_follows_counts()")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS like_count")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS reply_count")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS followers_count")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS following_count")
    op.execute("DROP TABLE IF EXISTS notifications")
    op.execute("DROP TABLE IF EXISTS post_likes")
    op.execute("DROP TABLE IF EXISTS follows")
    op.execute("DROP TYPE IF EXISTS notif_type")
