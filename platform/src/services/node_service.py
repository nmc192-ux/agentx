"""
AgentX Platform — Node Service
═══════════════════════════════
Phase 17: Federated AgentX Nodes.

Functions
─────────
  register_node       — register (upsert) a peer node by URL
  list_nodes          — list known peer nodes, optionally filtered to active
  get_node            — fetch a single node by UUID, raises ValueError if absent
  send_node_message   — log a federated message (inbound or outbound)
  update_node_status  — set a node's status (active / inactive / banned)
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from ..database import get_db
from ..models.node import NodeMessageResponse, NodeResponse

logger = logging.getLogger(__name__)


# ── Row helpers ───────────────────────────────────────────────────────────────

def _row_to_node(row) -> NodeResponse:
    return NodeResponse(
        node_id=row["node_id"],
        node_url=row["node_url"],
        node_name=row.get("node_name"),
        public_key=row.get("public_key"),
        status=row["status"],
        trust_level=float(row["trust_level"]),
        registered_at=row["registered_at"],
        last_seen_at=row.get("last_seen_at"),
    )


def _row_to_message(row) -> NodeMessageResponse:
    raw_payload = row.get("payload")
    if isinstance(raw_payload, str):
        payload = json.loads(raw_payload)
    elif isinstance(raw_payload, dict):
        payload = raw_payload
    else:
        payload = {}
    return NodeMessageResponse(
        message_id=row["message_id"],
        node_id=row.get("node_id"),
        event_type=row["event_type"],
        payload=payload,
        direction=row["direction"],
        created_at=row["created_at"],
    )


# ── Service functions ─────────────────────────────────────────────────────────

async def register_node(
    node_url: str,
    node_name: str | None = None,
    public_key: str | None = None,
) -> NodeResponse:
    """Register (or upsert) a peer node by URL.

    If the URL already exists the record is updated with the new name and
    public_key (public_key is only overwritten when a non-None value is
    supplied) and last_seen_at is refreshed.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO agentx_nodes (node_url, node_name, public_key)
            VALUES ($1, $2, $3)
            ON CONFLICT (node_url) DO UPDATE
                SET node_name    = EXCLUDED.node_name,
                    public_key   = COALESCE(EXCLUDED.public_key, agentx_nodes.public_key),
                    last_seen_at = NOW()
            RETURNING *
            """,
            node_url,
            node_name,
            public_key,
        )
    return _row_to_node(row)


async def list_nodes(active_only: bool = False) -> list[NodeResponse]:
    """Return all known peer nodes ordered by registration time.

    Args:
        active_only: When True, only return nodes with status='active'.
    """
    async with get_db() as conn:
        if active_only:
            rows = await conn.fetch(
                "SELECT * FROM agentx_nodes WHERE status = 'active' ORDER BY registered_at ASC"
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM agentx_nodes ORDER BY registered_at ASC"
            )
    return [_row_to_node(r) for r in rows]


async def get_node(node_id: UUID) -> NodeResponse:
    """Fetch a single node by UUID.

    Raises:
        ValueError: If no node with that ID exists.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM agentx_nodes WHERE node_id = $1", node_id
        )
    if row is None:
        raise ValueError(f"Node not found: {node_id}")
    return _row_to_node(row)


async def send_node_message(
    node_id: UUID | None,
    event_type: str,
    payload: dict,
    direction: str = "inbound",
) -> NodeMessageResponse:
    """Log a federated message to or from a peer node.

    Args:
        node_id:    UUID of the peer node (may be None for anonymous peers).
        event_type: The event type string (e.g. "CONTRACT_COMPLETED").
        payload:    Arbitrary event payload.
        direction:  'inbound' (received from peer) or 'outbound' (sent to peer).
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO node_messages (node_id, event_type, payload, direction)
            VALUES ($1, $2, $3::jsonb, $4)
            RETURNING *
            """,
            node_id,
            event_type,
            json.dumps(payload),
            direction,
        )
    return _row_to_message(row)


async def update_node_status(node_id: UUID, status: str) -> NodeResponse:
    """Update a peer node's status.

    Args:
        node_id: UUID of the node to update.
        status:  One of 'active', 'inactive', 'banned'.

    Raises:
        ValueError: If status is invalid or node is not found.
    """
    allowed = {"active", "inactive", "banned"}
    if status not in allowed:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {allowed}")

    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            UPDATE agentx_nodes
               SET status = $1, last_seen_at = NOW()
             WHERE node_id = $2
            RETURNING *
            """,
            status,
            node_id,
        )
    if row is None:
        raise ValueError(f"Node not found: {node_id}")
    return _row_to_node(row)
