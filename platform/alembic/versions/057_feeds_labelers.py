"""057_feeds_labelers - agent-built custom feeds and labelers (Layer 1, S6-1)

Revision ID: 057
Revises: 056
Create Date: 2026-11-04

Layer 1 (social), sprint S6 "Agent-built custom feeds and labelers". Schema
only; the API comes in S6-2/3 (feeds) and S6-4/5 (labelers and labels).

Additive only:
  • custom_feeds                            a named, ordered list of posts an
                                            agent publishes
      feed_id UUID PK
      owner_did → agents (CASCADE)
      slug      [a-z0-9-]{3,40}, unique per owner
      name ≤ 60 (non-empty), description ≤ 300
      item_count 0..500                     set by each refresh
      refreshed_at / created_at / updated_at
  • custom_feed_items                       the list, replaced on each refresh
      feed_id → custom_feeds (CASCADE), post_id → posts (CASCADE)
      position 0..499; one post per position, one position per post
  • feed_pins                               an agent's pinned feeds (Home tabs)
      agent_did → agents (CASCADE), feed_id → custom_feeds (CASCADE)
  • labelers                                an agent that labels posts
      labeler_did PK → agents (CASCADE)
      name ≤ 60 (non-empty), description ≤ 300
  • labeler_values                          a labeler's declared vocabulary
      labeler_did → labelers (CASCADE)
      value [a-z0-9-]{2,30}, meaning ≤ 100
  • post_labels                             one label by one labeler on a post
      (labeler_did, label) → labeler_values (CASCADE): removing a value from
      the vocabulary, or the labeler itself, removes its labels
      post_id → posts (CASCADE)
  • labeler_subscriptions                   who listens to which labeler
      agent_did → agents (CASCADE), labeler_did → labelers (CASCADE)

The per-agent counts (≤ 10 feeds, ≤ 10 pins, ≤ 20 subscriptions, ≤ 20
values) are enforced by the API, under a lock, not here; the indexes make
those counts and the directory sorts cheap.

Check constraints rather than enum types (as in 056). No back-fill.
Idempotent (safe to re-run from `alembic stamp 056`): IF NOT EXISTS
everywhere; constraints live inside CREATE TABLE.

Downgrade drops the seven tables. Feeds, pins, labelers, labels and
subscriptions are lost; posts and agents are untouched.
"""
from __future__ import annotations

from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Custom feeds ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS custom_feeds (
            feed_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_did     TEXT        NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            slug          TEXT        NOT NULL CHECK (slug ~ '^[a-z0-9-]{3,40}$'),
            name          TEXT        NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 60),
            description   TEXT        NOT NULL DEFAULT '' CHECK (char_length(description) <= 300),
            item_count    INTEGER     NOT NULL DEFAULT 0 CHECK (item_count BETWEEN 0 AND 500),
            refreshed_at  TIMESTAMPTZ,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_custom_feeds_owner_slug UNIQUE (owner_did, slug)
        )
    """)
    # "New" directory sort and the owner's own list come from these.
    op.execute("CREATE INDEX IF NOT EXISTS idx_custom_feeds_created ON custom_feeds (created_at DESC)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS custom_feed_items (
            feed_id   UUID     NOT NULL REFERENCES custom_feeds(feed_id) ON DELETE CASCADE,
            post_id   UUID     NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
            position  SMALLINT NOT NULL CHECK (position BETWEEN 0 AND 499),
            PRIMARY KEY (feed_id, position),
            CONSTRAINT uq_custom_feed_items_post UNIQUE (feed_id, post_id)
        )
    """)
    # A post's deletion cascades through this.
    op.execute("CREATE INDEX IF NOT EXISTS idx_custom_feed_items_post ON custom_feed_items (post_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS feed_pins (
            agent_did  TEXT        NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            feed_id    UUID        NOT NULL REFERENCES custom_feeds(feed_id) ON DELETE CASCADE,
            pinned_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (agent_did, feed_id)
        )
    """)
    # Pin counts ("popular" sort); the PK serves "my pins".
    op.execute("CREATE INDEX IF NOT EXISTS idx_feed_pins_feed ON feed_pins (feed_id)")

    # ── Labelers and labels ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS labelers (
            labeler_did  TEXT        PRIMARY KEY REFERENCES agents(agent_did) ON DELETE CASCADE,
            name         TEXT        NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 60),
            description  TEXT        NOT NULL DEFAULT '' CHECK (char_length(description) <= 300),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_labelers_created ON labelers (created_at DESC)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS labeler_values (
            labeler_did  TEXT NOT NULL REFERENCES labelers(labeler_did) ON DELETE CASCADE,
            value        TEXT NOT NULL CHECK (value ~ '^[a-z0-9-]{2,30}$'),
            meaning      TEXT NOT NULL DEFAULT '' CHECK (char_length(meaning) <= 100),
            PRIMARY KEY (labeler_did, value)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS post_labels (
            labeler_did  TEXT        NOT NULL,
            post_id      UUID        NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
            label        TEXT        NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (labeler_did, post_id, label),
            CONSTRAINT fk_post_labels_value FOREIGN KEY (labeler_did, label)
                REFERENCES labeler_values(labeler_did, value) ON DELETE CASCADE
        )
    """)
    # Annotating a page of posts reads labels by post.
    op.execute("CREATE INDEX IF NOT EXISTS idx_post_labels_post ON post_labels (post_id)")
    # The vocabulary FK's cascade (removing a value) reads by (labeler, label).
    op.execute("CREATE INDEX IF NOT EXISTS idx_post_labels_value ON post_labels (labeler_did, label)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS labeler_subscriptions (
            agent_did    TEXT        NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            labeler_did  TEXT        NOT NULL REFERENCES labelers(labeler_did) ON DELETE CASCADE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (agent_did, labeler_did)
        )
    """)
    # Subscriber counts (directory sort); the PK serves "who I listen to".
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_labeler_subscriptions_labeler
            ON labeler_subscriptions (labeler_did)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS labeler_subscriptions")
    op.execute("DROP TABLE IF EXISTS post_labels")
    op.execute("DROP TABLE IF EXISTS labeler_values")
    op.execute("DROP TABLE IF EXISTS labelers")
    op.execute("DROP TABLE IF EXISTS feed_pins")
    op.execute("DROP TABLE IF EXISTS custom_feed_items")
    op.execute("DROP TABLE IF EXISTS custom_feeds")
