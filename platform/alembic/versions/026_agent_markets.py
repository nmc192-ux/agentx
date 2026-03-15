"""026_agent_markets - Autonomous Agent Markets (Capability Bounties)

Revision ID: 026
Revises: 023
Create Date: 2026-03-15

Adds the Capability Bounty marketplace.  Organisations post problems
(capability_bounties); agents submit solutions (bounty_submissions);
the best submission wins the reward_pool (bounty_rewards).
"""

from alembic import op

revision = "026"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------- capability_bounties
    op.execute("""
        CREATE TABLE IF NOT EXISTS capability_bounties (
            bounty_id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            creator_did         TEXT        NOT NULL,
            creator_id          UUID        REFERENCES agents(agent_id) ON DELETE SET NULL,
            title               TEXT        NOT NULL,
            description         TEXT        NOT NULL DEFAULT '',
            capability_required TEXT        NOT NULL,
            reward_pool         BIGINT      NOT NULL DEFAULT 0,
            status              TEXT        NOT NULL DEFAULT 'open',
            deadline            TIMESTAMPTZ,
            winner_submission_id UUID,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at           TIMESTAMPTZ
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'capability_bounties'
                  AND indexname = 'ix_capability_bounties_status'
            ) THEN
                CREATE INDEX ix_capability_bounties_status
                    ON capability_bounties(status);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'capability_bounties'
                  AND indexname = 'ix_capability_bounties_creator_did'
            ) THEN
                CREATE INDEX ix_capability_bounties_creator_did
                    ON capability_bounties(creator_did);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'capability_bounties'
                  AND indexname = 'ix_capability_bounties_capability'
            ) THEN
                CREATE INDEX ix_capability_bounties_capability
                    ON capability_bounties(capability_required);
            END IF;
        END $$
    """)

    # ------------------------------------------------------- bounty_submissions
    op.execute("""
        CREATE TABLE IF NOT EXISTS bounty_submissions (
            submission_id   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            bounty_id       UUID        NOT NULL
                                        REFERENCES capability_bounties(bounty_id) ON DELETE CASCADE,
            submitter_did   TEXT        NOT NULL,
            submitter_id    UUID        REFERENCES agents(agent_id) ON DELETE SET NULL,
            solution_data   JSONB       NOT NULL DEFAULT '{}',
            summary         TEXT,
            score           FLOAT,
            status          TEXT        NOT NULL DEFAULT 'pending',
            submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            evaluated_at    TIMESTAMPTZ
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'bounty_submissions'
                  AND indexname = 'ix_bounty_submissions_bounty_id'
            ) THEN
                CREATE INDEX ix_bounty_submissions_bounty_id
                    ON bounty_submissions(bounty_id);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'bounty_submissions'
                  AND indexname = 'ix_bounty_submissions_submitter_did'
            ) THEN
                CREATE INDEX ix_bounty_submissions_submitter_did
                    ON bounty_submissions(submitter_did);
            END IF;
        END $$
    """)

    # ----------------------------------------------------------- bounty_rewards
    op.execute("""
        CREATE TABLE IF NOT EXISTS bounty_rewards (
            reward_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            bounty_id       UUID        NOT NULL
                                        REFERENCES capability_bounties(bounty_id) ON DELETE CASCADE,
            submission_id   UUID        NOT NULL
                                        REFERENCES bounty_submissions(submission_id) ON DELETE CASCADE,
            recipient_did   TEXT        NOT NULL,
            recipient_id    UUID        REFERENCES agents(agent_id) ON DELETE SET NULL,
            amount          BIGINT      NOT NULL,
            distributed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'bounty_rewards'
                  AND indexname = 'ix_bounty_rewards_bounty_id'
            ) THEN
                CREATE INDEX ix_bounty_rewards_bounty_id
                    ON bounty_rewards(bounty_id);
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bounty_rewards CASCADE")
    op.execute("DROP TABLE IF EXISTS bounty_submissions CASCADE")
    op.execute("DROP TABLE IF EXISTS capability_bounties CASCADE")
