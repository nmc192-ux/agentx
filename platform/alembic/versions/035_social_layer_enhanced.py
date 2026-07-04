"""
Phase 1 Enhanced Social Layer — Channels, Rooms, Consensus, Search
══════════════════════════════════════════════════════════════════

Changes (all additive):
  • Enable pgvector extension
  • Add embedding vector(1536) + search_vector tsvector to posts
  • Create table channels (topic channels within communities)
  • Create table channel_posts (junction)
  • Create table rooms (collaboration rooms)
  • Create table room_participants
  • Create table room_artifacts
  • Create table debate_rounds (enhanced consensus engine)
  • Create table debate_statements
  • Create table consensus_snapshots
  • Extend notif_type ENUM: ROOM_INVITE, DEBATE_STARTED, CONSENSUS_REACHED
  • Indexes for all new tables
"""
from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── pgvector extension ────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── Search columns on posts ───────────────────────────────────────────────
    op.execute("ALTER TABLE posts ADD COLUMN IF NOT EXISTS embedding vector(1536)")
    # A STORED GENERATED column requires an IMMUTABLE expression. Two builtins
    # used here are only STABLE, so we make the expression immutable:
    #   • to_tsvector('english'::regconfig, …) — the regconfig cast selects the
    #     IMMUTABLE overload (the bare-text 'english' overload is STABLE).
    #   • array_to_string(text[], text) is STABLE, so wrap it in an IMMUTABLE
    #     SQL function (the join is deterministic for text[]; STABLE is just
    #     Postgres being conservative). Without this the ALTER fails with
    #     "generation expression is not immutable" — which blocked this whole
    #     migration (and every one after it) from ever applying. See
    #     briefing_2026-07-04_chain.md ("Migration chain was broken at 035").
    op.execute("""
        CREATE OR REPLACE FUNCTION agentx_immutable_array_to_string(text[], text)
        RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
        $$ SELECT array_to_string($1, $2) $$
    """)
    op.execute("""
        ALTER TABLE posts ADD COLUMN IF NOT EXISTS search_vector tsvector
            GENERATED ALWAYS AS (
                setweight(to_tsvector('english'::regconfig, coalesce(title, '')), 'A') ||
                setweight(to_tsvector('english'::regconfig, coalesce(content, '')), 'B') ||
                setweight(to_tsvector('english'::regconfig, coalesce(agentx_immutable_array_to_string(tags, ' '), '')), 'C')
            ) STORED
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_posts_search ON posts USING GIN(search_vector)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_posts_embedding ON posts USING ivfflat(embedding vector_cosine_ops) WITH (lists = 50)")

    # ── ENUM extensions ───────────────────────────────────────────────────────
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'ROOM_INVITE'")
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'DEBATE_STARTED'")
    op.execute("ALTER TYPE notif_type ADD VALUE IF NOT EXISTS 'CONSENSUS_REACHED'")

    # ── channels ──────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE channels (
            channel_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            community_id  UUID        NOT NULL REFERENCES communities(community_id) ON DELETE CASCADE,
            name          TEXT        NOT NULL,
            slug          TEXT        NOT NULL,
            description   TEXT        NOT NULL DEFAULT '',
            channel_type  TEXT        NOT NULL DEFAULT 'GENERAL'
                                       CHECK (channel_type IN ('GENERAL', 'ANNOUNCEMENT', 'DEBATE', 'WORKSPACE')),
            is_default    BOOLEAN     NOT NULL DEFAULT FALSE,
            post_count    INT         NOT NULL DEFAULT 0,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (community_id, slug)
        )
    """)

    # ── channel_posts ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE channel_posts (
            channel_post_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            channel_id       UUID        NOT NULL REFERENCES channels(channel_id) ON DELETE CASCADE,
            post_id          UUID        NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (channel_id, post_id)
        )
    """)

    # ── rooms ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE rooms (
            room_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            name             TEXT        NOT NULL,
            description      TEXT        NOT NULL DEFAULT '',
            community_id     UUID        REFERENCES communities(community_id) ON DELETE SET NULL,
            room_type        TEXT        NOT NULL DEFAULT 'WORKSHOP'
                                          CHECK (room_type IN ('WORKSHOP', 'WAR_ROOM', 'REVIEW', 'BRAINSTORM')),
            status           TEXT        NOT NULL DEFAULT 'OPEN'
                                          CHECK (status IN ('OPEN', 'IN_PROGRESS', 'CLOSED', 'ARCHIVED')),
            max_participants INT         NOT NULL DEFAULT 12,
            creator_did      TEXT        NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            closed_at        TIMESTAMPTZ
        )
    """)

    # ── room_participants ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE room_participants (
            room_id    UUID        NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
            agent_did  TEXT        NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            role       TEXT        NOT NULL DEFAULT 'PARTICIPANT'
                                    CHECK (role IN ('HOST', 'PARTICIPANT', 'OBSERVER')),
            joined_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (room_id, agent_did)
        )
    """)

    # ── room_artifacts ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE room_artifacts (
            artifact_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            room_id        UUID        NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
            author_did     TEXT        NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            artifact_type  TEXT        NOT NULL DEFAULT 'NOTE'
                                        CHECK (artifact_type IN ('NOTE', 'CODE', 'DIAGRAM', 'LOG', 'WORKFLOW', 'RAG_SNIPPET')),
            title          TEXT        NOT NULL DEFAULT '',
            content        JSONB       NOT NULL DEFAULT '{}',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── debate_rounds ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE debate_rounds (
            round_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            proposal_id    UUID        NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
            round_number   INT         NOT NULL DEFAULT 1,
            phase          TEXT        NOT NULL DEFAULT 'OPENING'
                                        CHECK (phase IN ('OPENING', 'REBUTTAL', 'CLOSING', 'VOTING')),
            starts_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            ends_at        TIMESTAMPTZ,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (proposal_id, round_number)
        )
    """)

    # ── debate_statements ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE debate_statements (
            statement_id   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            round_id       UUID        NOT NULL REFERENCES debate_rounds(round_id) ON DELETE CASCADE,
            author_did     TEXT        NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            position       TEXT        NOT NULL CHECK (position IN ('FOR', 'AGAINST', 'NEUTRAL')),
            content        TEXT        NOT NULL CHECK (length(content) <= 4000),
            evidence_refs  JSONB       NOT NULL DEFAULT '[]',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── consensus_snapshots ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE consensus_snapshots (
            snapshot_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            proposal_id    UUID        NOT NULL REFERENCES posts(post_id) ON DELETE CASCADE,
            vote_tally     JSONB       NOT NULL DEFAULT '{}',
            weighted_tally JSONB       NOT NULL DEFAULT '{}',
            total_voters   INT         NOT NULL DEFAULT 0,
            quorum_met     BOOLEAN     NOT NULL DEFAULT FALSE,
            quorum_threshold DECIMAL(4,2) NOT NULL DEFAULT 0.33,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Indexes ───────────────────────────────────────────────────────────────
    op.execute("CREATE INDEX idx_channels_community  ON channels(community_id)")
    op.execute("CREATE INDEX idx_channel_posts_ch    ON channel_posts(channel_id, created_at DESC)")
    op.execute("CREATE INDEX idx_rooms_community     ON rooms(community_id) WHERE community_id IS NOT NULL")
    op.execute("CREATE INDEX idx_rooms_status         ON rooms(status, created_at DESC)")
    op.execute("CREATE INDEX idx_room_participants    ON room_participants(agent_did)")
    op.execute("CREATE INDEX idx_room_artifacts_room  ON room_artifacts(room_id, created_at DESC)")
    op.execute("CREATE INDEX idx_debate_rounds_prop   ON debate_rounds(proposal_id, round_number)")
    op.execute("CREATE INDEX idx_debate_stmts_round   ON debate_statements(round_id, created_at ASC)")
    op.execute("CREATE INDEX idx_consensus_snap_prop  ON consensus_snapshots(proposal_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS consensus_snapshots")
    op.execute("DROP TABLE IF EXISTS debate_statements")
    op.execute("DROP TABLE IF EXISTS debate_rounds")
    op.execute("DROP TABLE IF EXISTS room_artifacts")
    op.execute("DROP TABLE IF EXISTS room_participants")
    op.execute("DROP TABLE IF EXISTS rooms")
    op.execute("DROP TABLE IF EXISTS channel_posts")
    op.execute("DROP TABLE IF EXISTS channels")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS search_vector")
    op.execute("ALTER TABLE posts DROP COLUMN IF EXISTS embedding")
