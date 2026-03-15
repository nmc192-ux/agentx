"""021_contract_engine - Agent Contract Engine

Revision ID: 021
Revises: 020
Create Date: 2026-03-15
"""

from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ contracts
    op.execute("""
        CREATE TABLE IF NOT EXISTS contracts (
            contract_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            creator_did      TEXT        NOT NULL,
            creator_id       UUID        REFERENCES agents(agent_id) ON DELETE SET NULL,
            contractor_did   TEXT,
            contractor_id    UUID        REFERENCES agents(agent_id) ON DELETE SET NULL,
            title            TEXT        NOT NULL,
            description      TEXT        NOT NULL,
            contract_type    TEXT        NOT NULL DEFAULT 'general',
            status           TEXT        NOT NULL DEFAULT 'open',
            budget           BIGINT      NOT NULL DEFAULT 0,
            escrowed_budget  BIGINT      NOT NULL DEFAULT 0,
            deadline         TIMESTAMPTZ,
            payload          JSONB,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'contracts' AND indexname = 'ix_contracts_status'
            ) THEN
                CREATE INDEX ix_contracts_status ON contracts(status);
            END IF;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'contracts' AND indexname = 'ix_contracts_creator_id'
            ) THEN
                CREATE INDEX ix_contracts_creator_id ON contracts(creator_id);
            END IF;
        END $$
    """)

    # ------------------------------------------------------------------ contract_bids
    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_bids (
            bid_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            contract_id  UUID        NOT NULL REFERENCES contracts(contract_id) ON DELETE CASCADE,
            bidder_did   TEXT        NOT NULL,
            bidder_id    UUID        NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            bid_amount   BIGINT      NOT NULL,
            proposal     TEXT,
            status       TEXT        NOT NULL DEFAULT 'pending',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (contract_id, bidder_id)
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'contract_bids' AND indexname = 'ix_contract_bids_contract_id'
            ) THEN
                CREATE INDEX ix_contract_bids_contract_id ON contract_bids(contract_id);
            END IF;
        END $$
    """)

    # ------------------------------------------------------------------ contract_assignments
    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_assignments (
            assignment_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            contract_id    UUID        NOT NULL REFERENCES contracts(contract_id) ON DELETE CASCADE UNIQUE,
            contractor_did TEXT        NOT NULL,
            contractor_id  UUID        NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            assigned_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at   TIMESTAMPTZ
        )
    """)

    # ------------------------------------------------------------------ contract_results
    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_results (
            result_id       UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            contract_id     UUID        NOT NULL REFERENCES contracts(contract_id) ON DELETE CASCADE,
            contractor_did  TEXT        NOT NULL,
            contractor_id   UUID        NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            result_payload  JSONB,
            submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'contract_results' AND indexname = 'ix_contract_results_contract_id'
            ) THEN
                CREATE INDEX ix_contract_results_contract_id ON contract_results(contract_id);
            END IF;
        END $$
    """)

    # ------------------------------------------------------------------ contract_disputes
    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_disputes (
            dispute_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            contract_id   UUID        NOT NULL REFERENCES contracts(contract_id) ON DELETE CASCADE,
            initiator_did TEXT        NOT NULL,
            initiator_id  UUID        REFERENCES agents(agent_id) ON DELETE SET NULL,
            reason        TEXT        NOT NULL,
            status        TEXT        NOT NULL DEFAULT 'open',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'contract_disputes' AND indexname = 'ix_contract_disputes_contract_id'
            ) THEN
                CREATE INDEX ix_contract_disputes_contract_id ON contract_disputes(contract_id);
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contract_disputes CASCADE")
    op.execute("DROP TABLE IF EXISTS contract_results CASCADE")
    op.execute("DROP TABLE IF EXISTS contract_assignments CASCADE")
    op.execute("DROP TABLE IF EXISTS contract_bids CASCADE")
    op.execute("DROP TABLE IF EXISTS contracts CASCADE")
