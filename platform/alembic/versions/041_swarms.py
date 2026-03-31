"""041 — Swarm coordination tables

Revision ID: 041
Revises: 040
Create Date: 2026-03-31

Creates tables for multi-agent swarm coordination:
  swarms         — swarm lifecycle (FORMING → ACTIVE → COMPLETED)
  swarm_members  — agent membership with roles and subtask assignments
  swarm_results  — aggregated swarm outputs
"""
from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS swarms (
            swarm_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name                  TEXT NOT NULL,
            coordinator_did       TEXT NOT NULL,
            parent_task_id        UUID,
            objective             TEXT NOT NULL,
            strategy              TEXT NOT NULL DEFAULT 'parallel'
                                  CHECK (strategy IN ('parallel', 'pipeline', 'consensus', 'competitive')),
            max_members           INT NOT NULL DEFAULT 10,
            reward_pool           BIGINT NOT NULL DEFAULT 0,
            status                TEXT NOT NULL DEFAULT 'forming'
                                  CHECK (status IN ('forming', 'active', 'aggregating', 'completed', 'failed', 'cancelled')),
            required_capabilities TEXT[] DEFAULT '{}',
            config                JSONB DEFAULT '{}'::jsonb,
            created_at            TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            started_at            TIMESTAMPTZ,
            completed_at          TIMESTAMPTZ
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS swarm_members (
            swarm_id    UUID NOT NULL REFERENCES swarms(swarm_id) ON DELETE CASCADE,
            agent_did   TEXT NOT NULL,
            role        TEXT NOT NULL DEFAULT 'worker'
                        CHECK (role IN ('coordinator', 'worker', 'verifier')),
            status      TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('invited', 'active', 'completed', 'failed', 'left')),
            subtask_id  UUID,
            joined_at   TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMPTZ,
            PRIMARY KEY (swarm_id, agent_did)
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS swarm_subtasks (
            subtask_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            swarm_id     UUID NOT NULL REFERENCES swarms(swarm_id) ON DELETE CASCADE,
            task_type    TEXT NOT NULL,
            description  TEXT,
            payload      JSONB DEFAULT '{}'::jsonb,
            sequence     INT NOT NULL DEFAULT 0,
            assigned_did TEXT,
            task_id      UUID,
            status       TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'assigned', 'in_progress', 'completed', 'failed')),
            result       JSONB,
            created_at   TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMPTZ
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS swarm_results (
            result_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            swarm_id      UUID NOT NULL REFERENCES swarms(swarm_id) ON DELETE CASCADE,
            aggregation   JSONB NOT NULL DEFAULT '{}'::jsonb,
            summary       TEXT,
            created_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_swarms_coordinator ON swarms(coordinator_did)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_swarms_status ON swarms(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_swarm_members_agent ON swarm_members(agent_did)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_swarm_subtasks_swarm ON swarm_subtasks(swarm_id, sequence)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_swarm_subtasks_assigned ON swarm_subtasks(assigned_did)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS swarm_results CASCADE")
    op.execute("DROP TABLE IF EXISTS swarm_subtasks CASCADE")
    op.execute("DROP TABLE IF EXISTS swarm_members CASCADE")
    op.execute("DROP TABLE IF EXISTS swarms CASCADE")
