"""
Phase 1 Collaboration Rooms — Canvas state + Activity log
═════════════════════════════════════════════════════════

Changes (all additive):
  • Create table canvas_nodes  (node positions on room canvas)
  • Create table room_activity (event-sourced activity log)
  • Add indexes for canvas lookup and activity pagination

Revision ID: 036
Revises:      035
"""
from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── canvas_nodes: draggable artifact nodes on room canvas ──────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS canvas_nodes (
            node_id      UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            room_id      UUID NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
            artifact_id  UUID REFERENCES room_artifacts(artifact_id) ON DELETE SET NULL,
            node_type    TEXT NOT NULL DEFAULT 'artifact'
                         CHECK (node_type IN ('artifact','label','connector','group')),
            label        TEXT NOT NULL DEFAULT '',
            x            DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            y            DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            width        DOUBLE PRECISION NOT NULL DEFAULT 180.0,
            height       DOUBLE PRECISION NOT NULL DEFAULT 80.0,
            style        JSONB NOT NULL DEFAULT '{}',
            created_by   TEXT NOT NULL REFERENCES agents(agent_did),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_canvas_nodes_room
            ON canvas_nodes (room_id);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_canvas_nodes_artifact
            ON canvas_nodes (artifact_id)
            WHERE artifact_id IS NOT NULL;
    """)

    # ── room_activity: event-sourced log of everything in a room ───────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS room_activity (
            activity_id  UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            room_id      UUID NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
            agent_did    TEXT NOT NULL REFERENCES agents(agent_did),
            action       TEXT NOT NULL
                         CHECK (action IN (
                            'joined','left','artifact_added','artifact_removed',
                            'node_created','node_moved','node_deleted',
                            'room_closed','room_reopened','message'
                         )),
            detail       JSONB NOT NULL DEFAULT '{}',
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_room_activity_room
            ON room_activity (room_id, created_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS room_activity CASCADE;")
    op.execute("DROP TABLE IF EXISTS canvas_nodes CASCADE;")
