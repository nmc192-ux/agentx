import json

from fastapi import APIRouter, HTTPException, Request

from ..database import get_db

router = APIRouter(prefix="/reputation", tags=["Reputation"])


@router.get("/{agent_did:path}")
async def get_reputation(agent_did: str, request: Request):
    async with get_db() as conn:
        agent_row = await conn.fetchrow(
            "SELECT trust_score FROM agents WHERE agent_did = $1",
            agent_did,
        )
        if agent_row is None:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_did}")

        rows = await conn.fetch(
            """
            SELECT event_id, event_type, event_value, metadata, created_at
            FROM trust_events
            WHERE agent_did = $1
            ORDER BY created_at DESC
            LIMIT 50
            """,
            agent_did,
        )

    recent_events = []
    for row in rows:
        metadata = row["metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        recent_events.append(
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "event_value": float(row["event_value"]),
                "metadata": metadata,
                "created_at": row["created_at"],
            }
        )

    return {
        "agent_did": agent_did,
        "trust_score": float(agent_row["trust_score"]),
        "recent_events": recent_events,
    }
