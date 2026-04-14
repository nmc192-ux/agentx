"""
AgentX Platform — Graph Service
════════════════════════════════
Phase 1 Enhanced Social Layer: Constellation graph with relationship traversal.

Public API
──────────
  get_constellation(center_did, hops, min_trust, capability, community_id, limit)
    → { nodes: [...], edges: [...] }
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from ..database import get_db

logger = logging.getLogger(__name__)


async def get_constellation(
    center_did: str,
    hops: int = 2,
    min_trust: float = 0.0,
    capability: Optional[str] = None,
    community_id: Optional[UUID] = None,
    limit: int = 50,
) -> dict[str, Any]:
    """
    Build a constellation graph centered on an agent.

    Traverses follows, shared communities, shared tasks, and endorsements
    up to `hops` levels deep. Filters by min trust, capability, and community.

    Returns { nodes: [{did, name, trust, tier, ...}], edges: [{source, target, type}] }
    """
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    async with get_db() as conn:
        # Seed: the center agent
        center = await conn.fetchrow(
            "SELECT agent_did, display_name, trust_score, tier, bio, specialization FROM agents WHERE agent_did = $1",
            center_did,
        )
        if center is None:
            raise ValueError(f"Agent not found: {center_did}")

        nodes[center_did] = {
            "did": center["agent_did"],
            "name": center["display_name"],
            "trust": float(center["trust_score"]),
            "tier": center["tier"],
            "bio": center.get("bio") or "",
            "specialization": center.get("specialization") or "",
            "depth": 0,
        }

        frontier = {center_did}

        for depth in range(1, hops + 1):
            if not frontier:
                break

            next_frontier: set[str] = set()

            for did in frontier:
                # 1. Follows (both directions)
                follow_rows = await conn.fetch(
                    """
                    SELECT
                        CASE WHEN follower_did = $1 THEN followed_did ELSE follower_did END AS peer_did,
                        CASE WHEN follower_did = $1 THEN 'follows' ELSE 'followed_by' END AS rel_type
                    FROM follows
                    WHERE follower_did = $1 OR followed_did = $1
                    """,
                    did,
                )
                for fr in follow_rows:
                    peer = fr["peer_did"]
                    if peer not in nodes:
                        next_frontier.add(peer)
                    edges.append({"source": did, "target": peer, "type": fr["rel_type"]})

                # 2. Shared community memberships
                community_rows = await conn.fetch(
                    """
                    SELECT DISTINCT cm2.agent_did AS peer_did
                    FROM community_members cm1
                    JOIN community_members cm2 ON cm1.community_id = cm2.community_id
                    WHERE cm1.agent_did = $1 AND cm2.agent_did != $1
                    LIMIT 20
                    """,
                    did,
                )
                for cr in community_rows:
                    peer = cr["peer_did"]
                    if peer not in nodes:
                        next_frontier.add(peer)
                    edges.append({"source": did, "target": peer, "type": "shared_community"})

                # 3. Shared tasks (collaborators)
                task_rows = await conn.fetch(
                    """
                    SELECT DISTINCT
                        CASE WHEN requester_agent_did = $1 THEN executor_agent_did ELSE requester_agent_did END AS peer_did
                    FROM tasks
                    WHERE (requester_agent_did = $1 OR executor_agent_did = $1)
                      AND requester_agent_did IS NOT NULL
                      AND executor_agent_did IS NOT NULL
                    LIMIT 10
                    """,
                    did,
                )
                for tr in task_rows:
                    peer = tr["peer_did"]
                    if peer and peer not in nodes:
                        next_frontier.add(peer)
                    if peer:
                        edges.append({"source": did, "target": peer, "type": "collaborator"})

            # Fetch agent details for the new frontier
            if next_frontier:
                agent_rows = await conn.fetch(
                    """
                    SELECT agent_did, display_name, trust_score, tier, bio, specialization
                    FROM agents
                    WHERE agent_did = ANY($1)
                      AND status = 'ACTIVE'
                      AND trust_score >= $2
                    """,
                    list(next_frontier), min_trust,
                )
                for ar in agent_rows:
                    if ar["agent_did"] not in nodes:
                        nodes[ar["agent_did"]] = {
                            "did": ar["agent_did"],
                            "name": ar["display_name"],
                            "trust": float(ar["trust_score"]),
                            "tier": ar["tier"],
                            "bio": ar.get("bio") or "",
                            "specialization": ar.get("specialization") or "",
                            "depth": depth,
                        }

            # Next hop starts from newly discovered nodes
            frontier = next_frontier & set(nodes.keys())

        # Apply filters
        node_list = list(nodes.values())

        if capability:
            # Filter nodes that have matching capability
            cap_dids = set()
            cap_rows = await conn.fetch(
                "SELECT agent_did FROM agent_capabilities WHERE capability_id LIKE $1",
                f"{capability}%",
            )
            cap_dids = {r["agent_did"] for r in cap_rows}
            # Keep center + matching
            node_list = [n for n in node_list if n["did"] == center_did or n["did"] in cap_dids]

        if community_id:
            member_rows = await conn.fetch(
                "SELECT agent_did FROM community_members WHERE community_id = $1",
                community_id,
            )
            member_dids = {r["agent_did"] for r in member_rows}
            node_list = [n for n in node_list if n["did"] == center_did or n["did"] in member_dids]

        # Limit
        node_list = node_list[:limit]
        valid_dids = {n["did"] for n in node_list}
        edge_list = [e for e in edges if e["source"] in valid_dids and e["target"] in valid_dids]

        # Deduplicate edges
        seen_edges: set[str] = set()
        deduped_edges = []
        for e in edge_list:
            key = f"{e['source']}|{e['target']}|{e['type']}"
            if key not in seen_edges:
                seen_edges.add(key)
                deduped_edges.append(e)

    return {"nodes": node_list, "edges": deduped_edges}
