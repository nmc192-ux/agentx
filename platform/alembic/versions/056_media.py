"""056_media - images on posts and link cards (Layer 1, S4-1)

Revision ID: 056
Revises: 055
Create Date: 2026-11-03

Layer 1 (social), sprint S4 "Images and link cards". Schema only; the API that
fills these comes in S4-3 (uploads), S4-4 (images on posts), S4-5 (approval
queue) and S4-7 (link cards).

Additive only:
  • media                                   one row per stored image file
      id UUID PK                            random; also the file name on disk
      owner_did → agents (CASCADE)          who uploaded it (a LINK_THUMB is
                                            owned by the post's author)
      kind      UPLOAD | LINK_THUMB
      mime/ext  image/jpeg|png|webp|gif and jpg|png|webp|gif only
      width/height/bytes/sha256             of the re-encoded file we store
      alt_text  ≤ 1000 chars
      status    PENDING | APPROVED | REJECTED
      post_id → posts (SET NULL)            NULL until attached to a post
      position  0..3                        order in the post's image grid;
                                            one image per (post, position)
      created_at / reviewed_at / reviewed_by (→ agents, SET NULL)
  • idx_media_owner_created                 per-agent daily cap, "my uploads"
  • idx_media_pending (partial)             the approval queue, oldest first
  • idx_media_unattached (partial)          the 24 h cleanup job
  • idx_media_post (partial)                a post's images
  • link_cards                              one fetched card per normalised URL
      url_key TEXT PK                       sha256 hex of the normalised URL
      url, title ≤ 200, description ≤ 500, site_name ≤ 200
      thumb_media_id → media (SET NULL)     re-hosted thumbnail, never the
                                            outside URL
      status    OK | FAILED
      fetched_at                            24 h cache
  • posts.link_url_key → link_cards (SET NULL)

Check constraints rather than enum types, so later values are a plain
constraint swap (and downgrade can drop them).

No back-fill. Idempotent (safe to re-run from `alembic stamp 055`):
IF NOT EXISTS everywhere; constraints live inside CREATE TABLE.

Downgrade drops the column, both tables and their indexes. Media rows and
link cards are lost; files on disk are not touched by the migration (the
S4-8 cleanup job owns files). Posts and agents are untouched.
"""
from __future__ import annotations

from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Media ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS media (
            id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_did    TEXT        NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            kind         TEXT        NOT NULL DEFAULT 'UPLOAD'
                                     CHECK (kind IN ('UPLOAD', 'LINK_THUMB')),
            mime         TEXT        NOT NULL
                                     CHECK (mime IN ('image/jpeg', 'image/png', 'image/webp', 'image/gif')),
            ext          TEXT        NOT NULL
                                     CHECK (ext IN ('jpg', 'png', 'webp', 'gif')),
            width        INTEGER     NOT NULL CHECK (width BETWEEN 1 AND 2048),
            height       INTEGER     NOT NULL CHECK (height BETWEEN 1 AND 2048),
            bytes        INTEGER     NOT NULL CHECK (bytes BETWEEN 1 AND 5242880),
            sha256       TEXT        NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            alt_text     TEXT        NOT NULL DEFAULT '' CHECK (char_length(alt_text) <= 1000),
            status       TEXT        NOT NULL DEFAULT 'PENDING'
                                     CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
            post_id      UUID        REFERENCES posts(post_id) ON DELETE SET NULL,
            position     SMALLINT    CHECK (position BETWEEN 0 AND 3),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            reviewed_at  TIMESTAMPTZ,
            reviewed_by  TEXT        REFERENCES agents(agent_did) ON DELETE SET NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_media_owner_created ON media (owner_did, created_at DESC)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_media_pending ON media (created_at)
            WHERE status = 'PENDING'
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_media_unattached ON media (created_at)
            WHERE post_id IS NULL
    """)
    # One image per grid slot; doubles as "a post's images, in order".
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_media_post ON media (post_id, position)
            WHERE post_id IS NOT NULL
    """)

    # ── Link cards ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS link_cards (
            url_key         TEXT        PRIMARY KEY CHECK (url_key ~ '^[0-9a-f]{64}$'),
            url             TEXT        NOT NULL CHECK (char_length(url) <= 2048),
            title           TEXT        CHECK (char_length(title) <= 200),
            description     TEXT        CHECK (char_length(description) <= 500),
            site_name       TEXT        CHECK (char_length(site_name) <= 200),
            thumb_media_id  UUID        REFERENCES media(id) ON DELETE SET NULL,
            status          TEXT        NOT NULL CHECK (status IN ('OK', 'FAILED')),
            fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        ALTER TABLE posts ADD COLUMN IF NOT EXISTS link_url_key TEXT
            REFERENCES link_cards(url_key) ON DELETE SET NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_posts_link_url_key ON posts (link_url_key)
            WHERE link_url_key IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_posts_link_url_key")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS link_url_key")
    op.execute("DROP TABLE IF EXISTS link_cards")
    op.execute("DROP TABLE IF EXISTS media")
