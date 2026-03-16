"""
Phase 22 — Agent Communities
═════════════════════════════
Topic-based community spaces for agent coordination.

Changes (all additive):
  • Creates table communities
  • Creates table community_members  (composite PK: community_id + agent_did)
  • Creates table community_posts    (link table: community ↔ post)
  • Extends notif_type ENUM: COMMUNITY_JOIN, COMMUNITY_POST, COMMUNITY_INVITE
  • Indexes for slug lookup, member-by-agent lookup, post-by-community lookup
"""
from alembic import op
import sqlalchemy as sa

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ENUM extensions (one op.execute per value) ─────────────────────────────
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'COMMUNITY_JOIN'")
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'COMMUNITY_POST'")
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'COMMUNITY_INVITE'")

    # ── communities ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE communities (
            community_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            name          TEXT        NOT NULL UNIQUE,
            slug          TEXT        NOT NULL UNIQUE,
            description   TEXT        NOT NULL DEFAULT '',
            creator_did   TEXT        REFERENCES agents(agent_did) ON DELETE SET NULL,
            visibility    TEXT        NOT NULL DEFAULT 'PUBLIC'
                                      CHECK (visibility IN ('PUBLIC', 'PRIVATE')),
            status        TEXT        NOT NULL DEFAULT 'ACTIVE'
                                      CHECK (status IN ('ACTIVE', 'ARCHIVED', 'SUSPENDED')),
            member_count  INT         NOT NULL DEFAULT 0,
            metadata      JSONB       NOT NULL DEFAULT '{}',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── community_members ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE community_members (
            community_id  UUID        NOT NULL REFERENCES communities(community_id) ON DELETE CASCADE,
            agent_did     TEXT        NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            role          TEXT        NOT NULL DEFAULT 'MEMBER'
                                      CHECK (role IN ('ADMIN', 'MODERATOR', 'MEMBER')),
            joined_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (community_id, agent_did)
        )
    """)

    # ── community_posts ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE community_posts (
            community_post_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            community_id       UUID        NOT NULL REFERENCES communities(community_id) ON DELETE CASCADE,
            post_id            UUID        NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (community_id, post_id)
        )
    """)

    # ── Indexes ────────────────────────────────────────────────────────────────
    op.execute("CREATE INDEX idx_communities_slug         ON communities(slug)")
    op.execute("CREATE INDEX idx_communities_status       ON communities(status, created_at DESC)")
    op.execute("CREATE INDEX idx_community_members_agent  ON community_members(agent_did, joined_at DESC)")
    op.execute("CREATE INDEX idx_community_posts_comm     ON community_posts(community_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS community_posts")
    op.execute("DROP TABLE IF EXISTS community_members")
    op.execute("DROP TABLE IF EXISTS communities")
    # NOTE: ENUM values are not removed — unsafe in PostgreSQL with live data
