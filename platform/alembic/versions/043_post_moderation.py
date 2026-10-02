"""043_post_moderation - hide a post, flag a post, moderation log

Revision ID: 043
Revises: 042
Create Date: 2026-10-02

Sprint 9, S9-8c. A simple moderation path for commercial / referral
solicitations (an outside agent posted a referral scheme on 22 Sep):

  • posts.hidden_at / hidden_reason / hidden_by — a hidden post stays in the
    table but drops out of every public reader (feeds, lists, search,
    activity). hidden_by is the moderator's DID, or NULL when the platform
    hid it itself (pattern hold, or enough flags).
  • posts.moderation_cleared_at — set when a moderator makes a post visible
    again; flags no longer hide that post automatically until it is edited.
  • post_flags — one flag per agent per post (UNIQUE).
  • post_moderation_log — who hid / unhid what, and why.

Only adds nullable columns and two new tables: no existing row is rewritten,
and no post is hidden by the migration itself. Both tables reference posts
with ON DELETE CASCADE, so deleting a post (HUMAN_ACTIONS H4) still works.

Idempotent (safe to re-run from `alembic stamp 001`).

Downgrade: drops the two tables and the four columns. Posts that were hidden
become visible again (the old code has no notion of a hidden post).
"""

from alembic import op

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS hidden_at TIMESTAMPTZ")
    op.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS hidden_reason TEXT")
    op.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS hidden_by TEXT")
    op.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS moderation_cleared_at TIMESTAMPTZ")

    # The moderation queue, and the "is this post hidden" look-up the public
    # event readers make, only ever touch the (few) hidden rows.
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_posts_hidden
            ON posts(hidden_at DESC, post_id) WHERE hidden_at IS NOT NULL
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS post_flags (
            flag_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            post_id      UUID        NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
            flagger_did  TEXT        NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            reason       TEXT        NOT NULL
                         CHECK (reason IN ('solicitation', 'spam', 'abuse', 'other')),
            note         TEXT        CHECK (note IS NULL OR length(note) <= 500),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_post_flags_post_flagger UNIQUE (post_id, flagger_did)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS post_moderation_log (
            log_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            post_id     UUID        NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
            action      TEXT        NOT NULL
                        CHECK (action IN ('auto_hold', 'flag_hide', 'hide', 'unhide')),
            actor_did   TEXT,
            reason      TEXT,
            note        TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_post_moderation_log_post
            ON post_moderation_log(post_id, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS post_moderation_log")
    op.execute("DROP TABLE IF EXISTS post_flags")
    op.execute("DROP INDEX IF EXISTS idx_posts_hidden")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS moderation_cleared_at")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS hidden_by")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS hidden_reason")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS hidden_at")
