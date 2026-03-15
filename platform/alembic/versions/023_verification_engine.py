"""023_verification_engine - Result Verification Engine

Revision ID: 023
Revises: 022
Create Date: 2026-03-15

Adds the decentralised result-verification layer.  When a contractor
submits a contract result the creator can open a verification request;
a panel of agents votes (approve/reject) weighted by stake × trust.
"""

from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------- verifications
    op.execute("""
        CREATE TABLE IF NOT EXISTS verifications (
            verification_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            contract_id          UUID        NOT NULL
                                             REFERENCES contracts(contract_id) ON DELETE CASCADE,
            result_id            UUID        NOT NULL
                                             REFERENCES contract_results(result_id) ON DELETE CASCADE,
            requester_did        TEXT        NOT NULL,
            requester_id         UUID        REFERENCES agents(agent_id) ON DELETE SET NULL,
            status               TEXT        NOT NULL DEFAULT 'pending',
            required_votes       INT         NOT NULL DEFAULT 3,
            consensus_threshold  FLOAT       NOT NULL DEFAULT 0.6,
            yes_power            FLOAT       NOT NULL DEFAULT 0.0,
            no_power             FLOAT       NOT NULL DEFAULT 0.0,
            vote_count           INT         NOT NULL DEFAULT 0,
            reward_pool          BIGINT      NOT NULL DEFAULT 0,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finalized_at         TIMESTAMPTZ
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'verifications'
                  AND indexname = 'ix_verifications_contract_id'
            ) THEN
                CREATE INDEX ix_verifications_contract_id
                    ON verifications(contract_id);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'verifications'
                  AND indexname = 'ix_verifications_status'
            ) THEN
                CREATE INDEX ix_verifications_status ON verifications(status);
            END IF;
        END $$
    """)

    # --------------------------------------------------- verification_votes
    op.execute("""
        CREATE TABLE IF NOT EXISTS verification_votes (
            vote_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            verification_id  UUID        NOT NULL
                                         REFERENCES verifications(verification_id) ON DELETE CASCADE,
            verifier_did     TEXT        NOT NULL,
            verifier_id      UUID        NOT NULL
                                         REFERENCES agents(agent_id) ON DELETE CASCADE,
            vote             TEXT        NOT NULL,
            vote_power       FLOAT       NOT NULL DEFAULT 1.0,
            comment          TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (verification_id, verifier_id)
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'verification_votes'
                  AND indexname = 'ix_verification_votes_verification_id'
            ) THEN
                CREATE INDEX ix_verification_votes_verification_id
                    ON verification_votes(verification_id);
            END IF;
        END $$
    """)

    # ------------------------------------------------- verification_rewards
    op.execute("""
        CREATE TABLE IF NOT EXISTS verification_rewards (
            reward_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            verification_id  UUID        NOT NULL
                                         REFERENCES verifications(verification_id) ON DELETE CASCADE,
            verifier_id      UUID        NOT NULL
                                         REFERENCES agents(agent_id) ON DELETE CASCADE,
            verifier_did     TEXT        NOT NULL,
            amount           BIGINT      NOT NULL,
            rewarded_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'verification_rewards'
                  AND indexname = 'ix_verification_rewards_verification_id'
            ) THEN
                CREATE INDEX ix_verification_rewards_verification_id
                    ON verification_rewards(verification_id);
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS verification_rewards CASCADE")
    op.execute("DROP TABLE IF EXISTS verification_votes CASCADE")
    op.execute("DROP TABLE IF EXISTS verifications CASCADE")
