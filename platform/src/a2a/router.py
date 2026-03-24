"""AgentX Platform — A2A Agent Card router.

Serves Agent Card JSON documents at the standard A2A well-known URLs:

  GET /.well-known/agent.json
      → Agent Card describing the AgentX platform itself as an A2A server.

  GET /agents/{agent_did}/.well-known/agent.json
      → Agent Card for a specific registered agent, built from their DB record.

Both endpoints return ``application/json`` and are publicly accessible
(no authentication required — Agent Cards are discovery documents).

Reference: https://google.github.io/A2A/specification/
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from ..database import get_db
from .agent_card import AgentCard, generate_agent_card, generate_platform_card

logger = logging.getLogger(__name__)

a2a_router = APIRouter(tags=["A2A"])


# ── Platform card ─────────────────────────────────────────────────────────────


@a2a_router.get(
    "/.well-known/agent.json",
    response_model=AgentCard,
    summary="A2A Agent Card — platform",
    description=(
        "Returns the Agent Card for the AgentX platform itself. "
        "Compliant with the Google A2A protocol specification v0.3."
    ),
)
async def platform_agent_card() -> JSONResponse:
    """Serve the platform-level A2A Agent Card."""
    card = generate_platform_card()
    return JSONResponse(
        content=card.model_dump(exclude_none=True),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=300"},
    )


# ── Per-agent card ─────────────────────────────────────────────────────────────


@a2a_router.get(
    "/agents/{agent_did}/.well-known/agent.json",
    response_model=AgentCard,
    summary="A2A Agent Card — per agent",
    description=(
        "Returns the Agent Card for a specific registered agent identified "
        "by their DID. Compliant with the Google A2A protocol specification v0.3."
    ),
)
async def agent_agent_card(agent_did: str) -> JSONResponse:
    """Serve an individual agent's A2A Agent Card.

    Fetches the agent's record from the database and builds the Agent Card
    from their ``display_name``, ``specialization``, ``capabilities``,
    and ``bio`` fields.

    Returns HTTP 404 if no agent with the given DID is registered.
    """
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT agent_did, display_name, specialization, capabilities, bio
            FROM   agents
            WHERE  agent_did = $1
            """,
            agent_did,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent not found: {agent_did}",
        )

    # capabilities may be stored as a JSON string or a list
    raw_caps = row.get("capabilities")
    if isinstance(raw_caps, str):
        try:
            caps = json.loads(raw_caps) if raw_caps else []
        except (ValueError, TypeError):
            caps = []
    elif isinstance(raw_caps, list):
        caps = raw_caps
    else:
        caps = []

    card = generate_agent_card(
        agent_did=row["agent_did"],
        display_name=row["display_name"],
        specialization=row.get("specialization"),
        capabilities_list=caps,
        bio=row.get("bio"),
    )

    logger.debug("a2a: served card for %s", agent_did)

    return JSONResponse(
        content=card.model_dump(exclude_none=True),
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=60"},
    )
