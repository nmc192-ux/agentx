"""045_capability_endorsements - one endorsement per endorser; trust trigger on INSERT only

Revision ID: 045
Revises: 044
Create Date: 2026-10-02

Sprint 9, S9-9d.

(a) POST /agents/{did}/capabilities/{id}/verify only added one to
    agent_capabilities.verified_by_count, so one other account calling it
    twice made a capability "verified". Nothing recorded who had endorsed.

  • capability_endorsements — one row per (agent, capability, endorser).
    The primary key refuses a second endorsement by the same account, the
    CHECK refuses the capability's owner, and the rows go when the
    capability (or either agent) does.

    No existing row is changed: counts and "verified" flags already in
    agent_capabilities stay as they are (the founders' are seeded by
    init-db.sql and cannot be attributed to anyone). From here on the route
    counts an endorsement only when its row is new, and sets "verified" only
    on two recorded endorsers.

(b) trg_trust_score_update copied the factor composite (a flat 0.44, nothing
    feeds the factors after sign-up) into agents.trust_score on every INSERT
    *or UPDATE* of agent_trust_breakdown. agents.trust_score is owned by the
    scheduled replay of trust_events (S9-9a/c); any future writer of the
    breakdown would have reset replayed scores. The trigger now fires on
    INSERT only, which keeps the starting value sign-up sets. It is only
    narrowed where it exists; a database without it is left without it.

Idempotent: running it again on a database that already has it changes nothing.

Downgrade: drops capability_endorsements (the counts in agent_capabilities
stay) and puts the trigger back on INSERT OR UPDATE.
"""

from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def _retarget_trust_trigger(events: str) -> str:
    return f"""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_trigger
                WHERE tgname = 'trg_trust_score_update'
                  AND tgrelid = to_regclass('public.agent_trust_breakdown')
                  AND NOT tgisinternal
            ) THEN
                DROP TRIGGER trg_trust_score_update ON agent_trust_breakdown;
                CREATE TRIGGER trg_trust_score_update
                    AFTER {events} ON agent_trust_breakdown
                    FOR EACH ROW EXECUTE FUNCTION recalculate_trust_score();
            END IF;
        END $$
    """


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS capability_endorsements (
            agent_did      TEXT        NOT NULL,
            capability_id  TEXT        NOT NULL,
            endorser_did   TEXT        NOT NULL REFERENCES agents(agent_did) ON DELETE CASCADE,
            notes          TEXT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (agent_did, capability_id, endorser_did),
            FOREIGN KEY (agent_did, capability_id)
                REFERENCES agent_capabilities(agent_did, capability_id) ON DELETE CASCADE,
            CONSTRAINT capability_endorsements_not_owner CHECK (endorser_did <> agent_did)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_capability_endorsements_endorser
            ON capability_endorsements(endorser_did)
    """)
    op.execute(_retarget_trust_trigger("INSERT"))


def downgrade() -> None:
    op.execute(_retarget_trust_trigger("INSERT OR UPDATE"))
    op.execute("DROP TABLE IF EXISTS capability_endorsements")
