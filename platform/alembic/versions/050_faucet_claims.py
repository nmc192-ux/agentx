"""050_faucet_claims - one row per faucet claim (Phase C, Sprint 20, FC-1)

Revision ID: 050
Revises: 049
Create Date: 2026-10-15

The faucet (`services/faucet_service.py`, `POST /wallets/faucet`) lets an
agent mint a small, fixed amount into its own wallet at most once per UTC
day, while the platform-wide daily budget lasts. This table is the record
that makes both limits hold:

  • UNIQUE (agent_id, claim_day) — a second claim the same day is refused by
    the service and, should two ever race past it, by the database.
  • SUM(amount) over a claim_day — today's spend, checked against
    FAUCET_DAILY_BUDGET under a global advisory lock before any credit.

The credit itself goes to `wallets`, the ledger row to `transactions`
(type 'faucet', related_id = claim_id) and the supply to
`token_supply.total_minted`, all in the claim's own transaction.

Additive only: one new table, no existing row is read or changed. The
feature is off by default (FAUCET_ENABLED), so this migration changes no
behaviour on its own.

Idempotent (safe to re-run from `alembic stamp 001`).

Downgrade: drops the table (the claim history; wallet balances and the
ledger keep what was paid).
"""

from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS faucet_claims (
            claim_id   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id   UUID        NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
            claim_day  DATE        NOT NULL,
            amount     BIGINT      NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT faucet_claims_amount_positive CHECK (amount > 0),
            CONSTRAINT faucet_claims_one_per_day UNIQUE (agent_id, claim_day)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_faucet_claims_day
            ON faucet_claims (claim_day)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS faucet_claims")
