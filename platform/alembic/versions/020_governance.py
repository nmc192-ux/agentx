"""020_governance - Governance layer: proposals, votes, governance_parameters

Revision ID: 020
Revises: 019
Create Date: 2026-03-15
"""

from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ proposals
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
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'proposals'
                  AND indexname = 'ix_proposals_status'
            ) THEN
                CREATE INDEX ix_proposals_status ON proposals(status);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'proposals'
                  AND indexname = 'ix_proposals_proposer_id'
            ) THEN
                CREATE INDEX ix_proposals_proposer_id ON proposals(proposer_id);
            END IF;
        END $$
    """)

    # ------------------------------------------------------------------ votes
    op.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            vote_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            proposal_id     UUID NOT NULL REFERENCES proposals(proposal_id) ON DELETE CASCADE,
            voter_id        UUID NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            voter_did       TEXT NOT NULL,
            vote            TEXT NOT NULL CHECK (vote IN ('yes', 'no', 'abstain')),
            vote_power      NUMERIC(20, 6) NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (proposal_id, voter_id)
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'votes'
                  AND indexname = 'ix_votes_proposal_id'
            ) THEN
                CREATE INDEX ix_votes_proposal_id ON votes(proposal_id);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'votes'
                  AND indexname = 'ix_votes_voter_id'
            ) THEN
                CREATE INDEX ix_votes_voter_id ON votes(voter_id);
            END IF;
        END $$
    """)

    # ------------------------------------------------------------------ governance_parameters
    op.execute("""
        CREATE TABLE IF NOT EXISTS governance_parameters (
            param_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            TEXT NOT NULL UNIQUE,
            value           TEXT NOT NULL,
            description     TEXT,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ------------------------------------------------------------------ seed default parameters
    op.execute("""
        INSERT INTO governance_parameters (name, value, description)
        VALUES
            ('min_vote_power',      '0',    'Minimum vote power required to cast a vote'),
            ('default_voting_days', '7',    'Default number of days for a proposal voting period'),
            ('quorum_threshold',    '100',  'Minimum total vote power required for a valid result'),
            ('pass_threshold',      '0.5',  'Fraction of yes_power/(yes_power+no_power) required to pass')
        ON CONFLICT (name) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS votes CASCADE")
    op.execute("DROP TABLE IF EXISTS proposals CASCADE")
    op.execute("DROP TABLE IF EXISTS governance_parameters CASCADE")
