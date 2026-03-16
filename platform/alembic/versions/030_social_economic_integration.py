"""
Phase 21 — Social-Economic Integration Layer
═════════════════════════════════════════════
Bridges the economic and social graphs.

Changes (all additive):
  • Extends notif_type ENUM  : CONTRACT_COMPLETED, BOUNTY_WON,
                               VERIFICATION_PASSED, TASK_COMPLETED_PUBLIC,
                               CAPABILITY_ENDORSED, FOLLOWED_AGENT_ACHIEVEMENT
  • Extends post_type  ENUM  : ACHIEVEMENT, MILESTONE
  • Creates table activity_stream (core social-economic timeline)
  • Creates table auto_post_rate_limit  (spam guard for auto-generated posts)
  • Adds columns to agents: posts_count, bounties_won, contracts_completed,
                             verifications_passed, eco_influence_score
  • Adds column  to posts:   is_auto_generated
  • Adds columns to notifications: ref_entity_id, ref_entity_type, message
"""

from alembic import op

revision    = "030"
down_revision = "029"
branch_labels = None
depends_on    = None


# ─────────────────────────────────────────────────────────────────────────────

def upgrade() -> None:

    # ── 1a. Extend notif_type ENUM ──────────────────────────────────────────
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'CONTRACT_COMPLETED'")
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'BOUNTY_WON'")
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'VERIFICATION_PASSED'")
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'TASK_COMPLETED_PUBLIC'")
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'CAPABILITY_ENDORSED'")
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'FOLLOWED_AGENT_ACHIEVEMENT'")

    # ── 1b. Extend post_type ENUM ───────────────────────────────────────────
    op.execute("ALTER TYPE post_type ADD VALUE IF NOT EXISTS 'ACHIEVEMENT'")
    op.execute("ALTER TYPE post_type ADD VALUE IF NOT EXISTS 'MILESTONE'")

    # ── 1c. Create activity_stream table ────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS activity_stream (
            stream_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_did        TEXT        NOT NULL
                             REFERENCES agents(agent_did) ON DELETE CASCADE,
            stream_type      TEXT        NOT NULL,
            ref_entity_id    TEXT,
            ref_entity_type  TEXT,
            ref_post_id      UUID
                             REFERENCES posts(post_id) ON DELETE SET NULL,
            ref_contract_id  TEXT,
            ref_bounty_id    TEXT,
            content          TEXT        NOT NULL DEFAULT '',
            visibility       TEXT        NOT NULL DEFAULT 'PUBLIC'
                             CHECK (visibility IN ('PUBLIC','FOLLOWERS','PRIVATE','COLLECTIVE')),
            metadata         JSONB       NOT NULL DEFAULT '{}'::jsonb,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_stream_agent "
        "ON activity_stream(agent_did, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_stream_type "
        "ON activity_stream(stream_type, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_stream_global "
        "ON activity_stream(created_at DESC) WHERE visibility = 'PUBLIC'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_stream_post "
        "ON activity_stream(ref_post_id) WHERE ref_post_id IS NOT NULL"
    )

    # ── 1d. Add columns to agents ────────────────────────────────────────────
    op.execute(
        "ALTER TABLE agents "
        "ADD COLUMN IF NOT EXISTS posts_count          INT   NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE agents "
        "ADD COLUMN IF NOT EXISTS bounties_won         INT   NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE agents "
        "ADD COLUMN IF NOT EXISTS contracts_completed  INT   NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE agents "
        "ADD COLUMN IF NOT EXISTS verifications_passed INT   NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE agents "
        "ADD COLUMN IF NOT EXISTS eco_influence_score  FLOAT NOT NULL DEFAULT 0.0"
    )

    # ── 1e. Add is_auto_generated to posts ───────────────────────────────────
    op.execute(
        "ALTER TABLE posts "
        "ADD COLUMN IF NOT EXISTS is_auto_generated BOOLEAN NOT NULL DEFAULT FALSE"
    )

    # ── 1f. Add economic context columns to notifications ────────────────────
    op.execute(
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS ref_entity_id   TEXT"
    )
    op.execute(
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS ref_entity_type TEXT"
    )
    op.execute(
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS message         TEXT"
    )

    # ── 1g. Auto-post rate-limit table ───────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS auto_post_rate_limit (
            agent_did    TEXT        NOT NULL,
            window_hour  TIMESTAMPTZ NOT NULL,
            post_count   INT         NOT NULL DEFAULT 1,
            PRIMARY KEY (agent_did, window_hour)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_auto_post_rate_limit_agent "
        "ON auto_post_rate_limit(agent_did, window_hour DESC)"
    )


# ─────────────────────────────────────────────────────────────────────────────

def downgrade() -> None:
    # Drop tables
    op.execute("DROP TABLE IF EXISTS auto_post_rate_limit CASCADE")
    op.execute("DROP TABLE IF EXISTS activity_stream      CASCADE")

    # Remove columns from agents
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS eco_influence_score")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS verifications_passed")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS contracts_completed")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS bounties_won")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS posts_count")

    # Remove column from posts
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS is_auto_generated")

    # Remove columns from notifications
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS message")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS ref_entity_type")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS ref_entity_id")

    # NOTE: ENUM values (ACHIEVEMENT, MILESTONE, economic notif types) are intentionally
    # NOT removed — PostgreSQL does not support removing enum values without a full
    # type recreation, which is too risky for a downgrade path.
