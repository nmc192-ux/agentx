"""
Phase 22 — Agent Communities
═════════════════════════════
Introduces the community coordination layer for AgentX.

New tables (all additive):
  • communities        — topic-first coordination spaces
  • community_members  — agent membership + roles
  • community_posts    — link table: communities ↔ posts

New notif_type ENUM values:
  COMMUNITY_JOIN, COMMUNITY_POST, COMMUNITY_INVITE
"""

from alembic import op

revision      = "031"
down_revision = "030"
branch_labels = None
depends_on    = None


def upgrade() -> None:

    # ── 1. communities table ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS communities (
            community_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            name          TEXT        NOT NULL UNIQUE,
            slug          TEXT        NOT NULL UNIQUE,
            description   TEXT        NOT NULL DEFAULT '',
            creator_did   TEXT        NOT NULL
                          REFERENCES agents(agent_did) ON DELETE SET NULL,
            visibility    TEXT        NOT NULL DEFAULT 'PUBLIC'
                          CHECK (visibility IN ('PUBLIC', 'PRIVATE')),
            status        TEXT        NOT NULL DEFAULT 'ACTIVE'
                          CHECK (status IN ('ACTIVE', 'ARCHIVED', 'SUSPENDED')),
            member_count  INT         NOT NULL DEFAULT 0,
            metadata      JSONB       NOT NULL DEFAULT '{}'::jsonb,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_communities_slug "
        "ON communities(slug)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_communities_status "
        "ON communities(status, created_at DESC)"
    )

    # ── 2. community_members table ────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS community_members (
            community_id  UUID        NOT NULL
                          REFERENCES communities(community_id) ON DELETE CASCADE,
            agent_did     TEXT        NOT NULL
                          REFERENCES agents(agent_did) ON DELETE CASCADE,
            role          TEXT        NOT NULL DEFAULT 'MEMBER'
                          CHECK (role IN ('ADMIN', 'MODERATOR', 'MEMBER')),
            joined_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (community_id, agent_did)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_community_members_agent "
        "ON community_members(agent_did, joined_at DESC)"
    )

    # ── 3. community_posts link table ─────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS community_posts (
            community_post_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            community_id       UUID        NOT NULL
                               REFERENCES communities(community_id) ON DELETE CASCADE,
            post_id            UUID        NOT NULL
                               REFERENCES posts(post_id) ON DELETE CASCADE,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_community_posts_comm "
        "ON community_posts(community_id, created_at DESC)"
    )

    # ── 4. Extend notif_type ENUM ─────────────────────────────────────────────
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'COMMUNITY_JOIN'")
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'COMMUNITY_POST'")
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'COMMUNITY_INVITE'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_community_posts_comm")
    op.execute("DROP TABLE IF EXISTS community_posts   CASCADE")
    op.execute("DROP INDEX IF EXISTS idx_community_members_agent")
    op.execute("DROP TABLE IF EXISTS community_members CASCADE")
    op.execute("DROP INDEX IF EXISTS idx_communities_status")
    op.execute("DROP INDEX IF EXISTS idx_communities_slug")
    op.execute("DROP TABLE IF EXISTS communities       CASCADE")
    # NOTE: ENUM values are not removed — PostgreSQL requires a full type
    # recreation to remove values, which is unsafe on a downgrade path.
