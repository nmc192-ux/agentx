from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..database import get_db
from ..services.reputation import get_agent_trust_by_did, get_reputation_history

router = APIRouter(prefix="/reputation", tags=["Reputation"])


@router.get("/{agent_did:did}")
async def get_reputation(agent_did: str, request: Request):
    try:
        trust = await get_agent_trust_by_did(agent_did)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async with get_db() as conn:
        agent_id = await conn.fetchval(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            agent_did,
        )

    history = await get_reputation_history(agent_id)
    recent_events = [
        {
            "event_id": item.event_id,
            "event_type": item.event_type,
            "event_weight": item.event_weight,
            "metadata": item.metadata,
            "created_at": item.created_at,
        }
        for item in history
    ]

    return {
        "agent_did": agent_did,
        "trust_score": trust.current_score,
        "recent_events": recent_events,
    }
