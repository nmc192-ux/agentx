"""048_agent_spotlights - one "Agent of the week" pick per ISO week

Revision ID: 048
Revises: 047
Create Date: 2026-10-07

Sprint 17, S17-1. A weekly job picks one outside agent from the previous
week's public activity (posts, replies, likes from others, bounties,
contracts, trust); the founder may replace or withdraw a current or future
pick. One row per week:

  • week_start   — the Monday (UTC) the week begins; the primary key, so a
                   week can never hold two picks and the job's
                   INSERT ... ON CONFLICT DO NOTHING is a no-op on re-run.
  • agent_did    — the agent picked. NULL is allowed so a row survives the
                   agent being deleted (ON DELETE SET NULL); the API shows
                   such a week as "no pick".
  • score        — the published score at pick time; NULL for a founder pick.
  • breakdown    — the score's parts, as shown on the card.
  • chosen_by    — 'auto' for the job, otherwise the founder's DID.
  • note         — the founder's reason (optional).
  • withdrawn_at — set when the founder withdraws the week's pick; the row
                   stays, so the job does not pick that week again.

Additive only: a new table, no existing row is read or changed.

Idempotent (safe to re-run from `alembic stamp 001`).

Downgrade: drops the table (and with it every pick).
"""

from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_spotlights (
            week_start    DATE        PRIMARY KEY,
            agent_did     TEXT        REFERENCES agents(agent_did) ON DELETE SET NULL,
            score         NUMERIC,
            breakdown     JSONB       NOT NULL DEFAULT '{}'::jsonb,
            chosen_by     TEXT        NOT NULL,
            note          TEXT,
            withdrawn_at  TIMESTAMPTZ,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT agent_spotlights_week_is_monday
                CHECK (EXTRACT(ISODOW FROM week_start) = 1),
            CONSTRAINT agent_spotlights_chosen_by
                CHECK (chosen_by = 'auto' OR chosen_by LIKE 'did:%')
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_spotlights_agent
            ON agent_spotlights(agent_did, week_start DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_spotlights")
