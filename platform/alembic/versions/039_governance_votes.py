"""039_governance_votes - Create governance_votes (governance vote-cast 500 fix)

Revision ID: 039
Revises: 038
Create Date: 2026-07-04

Fixes the governance vote endpoint, which 500s because governance_service.py
reads/writes a `governance_votes` table that no migration ever created. The
name `governance_votes` (rather than `votes`) exists precisely to avoid the
baseline `votes` table (a different, post-voting schema in init-db.sql) — so
migration 020's `CREATE TABLE IF NOT EXISTS votes` silently no-ops and the
governance-shaped table lives nowhere. This creates it with the shape the
service expects (identical to 020's intended `votes` shape).

DEPLOY-SAFETY: production's DB schema is divergent (stamped 037 over a baseline
that lacks `proposals`). The `governance_votes.proposal_id` FK targets
`proposals`, so we re-issue 020's idempotent `proposals` (and
`governance_parameters`) DDL first — a no-op on any correctly-migrated DB, but
it prevents this migration from aborting the production release_command when
`proposals` is absent. See briefing_2026-07-04_chain.md ("Production schema
divergence").
"""

from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Deploy-safety: ensure the FK parent (proposals) exists. ───────────────
    # Verbatim-idempotent re-issue of migration 020's proposals DDL. No-op where
    # proposals already exists; on a divergent prod DB it creates the parent so
    # the governance_votes FK below does not abort the deploy.
    op.execute("""
        CREATE TABLE IF NOT EXISTS proposals (
            proposal_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            proposer_did    TEXT NOT NULL,
            proposer_id     UUID REFERENCES agents(agent_id) ON DELETE SET NULL,
            title           TEXT NOT NULL,
            description     TEXT NOT NULL,
            proposal_type   TEXT NOT NULL DEFAULT 'general',
            status          TEXT NOT NULL DEFAULT 'active',
            payload         JSONB,
            yes_power       NUMERIC(20, 6) NOT NULL DEFAULT 0,
            no_power        NUMERIC(20, 6) NOT NULL DEFAULT 0,
            voting_ends_at  TIMESTAMPTZ NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_indexes
                WHERE tablename = 'proposals' AND indexname = 'ix_proposals_status') THEN
                CREATE INDEX ix_proposals_status ON proposals(status);
            END IF;
        END $$
    """)

    # governance_parameters + seed (the service reads these; re-issue idempotently).
    op.execute("""
        CREATE TABLE IF NOT EXISTS governance_parameters (
            param_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            TEXT NOT NULL UNIQUE,
            value           TEXT NOT NULL,
            description     TEXT,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        INSERT INTO governance_parameters (name, value, description)
        VALUES
            ('min_vote_power',      '0',    'Minimum vote power required to cast a vote'),
            ('default_voting_days', '7',    'Default number of days for a proposal voting period'),
            ('quorum_threshold',    '100',  'Minimum total vote power required for a valid result'),
            ('pass_threshold',      '0.5',  'Fraction of yes_power/(yes_power+no_power) required to pass')
        ON CONFLICT (name) DO NOTHING
    """)

    # ── The actual fix: governance_votes. ─────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS governance_votes (
            vote_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            proposal_id  UUID NOT NULL REFERENCES proposals(proposal_id) ON DELETE CASCADE,
            voter_id     UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            voter_did    TEXT NOT NULL,
            vote         TEXT NOT NULL CHECK (vote IN ('yes', 'no', 'abstain')),
            vote_power   NUMERIC(20, 6) NOT NULL DEFAULT 0,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (proposal_id, voter_id)
        )
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_indexes
                WHERE tablename = 'governance_votes'
                  AND indexname = 'ix_governance_votes_proposal_id') THEN
                CREATE INDEX ix_governance_votes_proposal_id ON governance_votes(proposal_id);
            END IF;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_indexes
                WHERE tablename = 'governance_votes'
                  AND indexname = 'ix_governance_votes_voter_id') THEN
                CREATE INDEX ix_governance_votes_voter_id ON governance_votes(voter_id);
            END IF;
        END $$
    """)


def downgrade() -> None:
    # Only drop what this migration is responsible for. proposals /
    # governance_parameters are owned by migration 020 and are left intact.
    op.execute("DROP TABLE IF EXISTS governance_votes CASCADE")
