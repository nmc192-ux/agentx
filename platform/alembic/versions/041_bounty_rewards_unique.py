"""041_bounty_rewards_unique - one reward per bounty

Revision ID: 041
Revises: 040
Create Date: 2026-10-01

Sprint 9, S9-6c. A bounty's reward pool must be paid out exactly once.
bounty_service.distribute_rewards now locks the bounty row and closes it with
a status-guarded UPDATE in the same transaction as the payout; this migration
adds the database-level backstop: UNIQUE(bounty_rewards.bounty_id).

Existing duplicates (possible only if the old, unlocked distribute endpoint was
hit concurrently — the `markets` router has been disabled in production) would
make the unique index impossible to build and fail the deploy. They are not
deleted outright: every reward row after the first for a bounty is MOVED to
`bounty_rewards_duplicates_041`, so the record of a double payment survives.
Wallet balances and the `transactions` ledger are not touched.

Idempotent (safe to re-run from `alembic stamp 001`); a no-op for the data on
any database without duplicates.
"""

from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Same columns as bounty_rewards, no constraints: an archive, not a ledger.
    op.execute("""
        CREATE TABLE IF NOT EXISTS bounty_rewards_duplicates_041 (
            reward_id       UUID        NOT NULL,
            bounty_id       UUID        NOT NULL,
            submission_id   UUID        NOT NULL,
            recipient_did   TEXT        NOT NULL,
            recipient_id    UUID,
            amount          BIGINT      NOT NULL,
            distributed_at  TIMESTAMPTZ NOT NULL,
            archived_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # Move every reward after the first (earliest) one for the same bounty.
    op.execute("""
        WITH ranked AS (
            SELECT reward_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY bounty_id
                       ORDER BY distributed_at ASC, reward_id ASC
                   ) AS rn
            FROM bounty_rewards
        ),
        moved AS (
            DELETE FROM bounty_rewards
             WHERE reward_id IN (SELECT reward_id FROM ranked WHERE rn > 1)
            RETURNING reward_id, bounty_id, submission_id, recipient_did,
                      recipient_id, amount, distributed_at
        )
        INSERT INTO bounty_rewards_duplicates_041
            (reward_id, bounty_id, submission_id, recipient_did,
             recipient_id, amount, distributed_at)
        SELECT reward_id, bounty_id, submission_id, recipient_did,
               recipient_id, amount, distributed_at
        FROM moved
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_bounty_rewards_bounty_id
            ON bounty_rewards(bounty_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_bounty_rewards_bounty_id")

    # Put archived duplicates back where they were (skipping any whose bounty
    # or submission has since been deleted), then drop the archive.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_schema = 'public'
                         AND table_name = 'bounty_rewards_duplicates_041')
            THEN
                INSERT INTO bounty_rewards
                    (reward_id, bounty_id, submission_id, recipient_did,
                     recipient_id, amount, distributed_at)
                SELECT d.reward_id, d.bounty_id, d.submission_id, d.recipient_did,
                       a.agent_id, d.amount, d.distributed_at
                FROM bounty_rewards_duplicates_041 d
                JOIN capability_bounties b ON b.bounty_id = d.bounty_id
                JOIN bounty_submissions  s ON s.submission_id = d.submission_id
                LEFT JOIN agents a ON a.agent_id = d.recipient_id
                ON CONFLICT (reward_id) DO NOTHING;
                DROP TABLE bounty_rewards_duplicates_041;
            END IF;
        END $$
    """)
