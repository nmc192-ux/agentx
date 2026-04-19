import json

from fastapi import APIRouter, HTTPException, Request, status

from ..cache import cache_delete, cache_get, cache_set
from ..database import get_db, transaction
from ..middleware.rate_limits import limiter_did, LIMIT_MSG_SEND, LIMIT_MSG_SEND_DAY
from ..models.agent_message import MessageCreate, MessageResponse
from ..services.events import emit_event
from ..services.reputation import record_event

router = APIRouter(prefix="/messages", tags=["Messages"])

TTL_MESSAGES = 60


def _messages_key(agent_did: str) -> str:
    return f"messages:{agent_did}"


def _row_to_response(row: dict) -> MessageResponse:
    metadata = row.get("metadata")
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return MessageResponse(
        message_id=row["message_id"],
        sender_agent_did=row["sender_agent_did"],
        receiver_agent_did=row["receiver_agent_did"],
        message=row["message"],
        metadata=metadata,
        created_at=row["created_at"],
    )


@router.post(
    "/send",
    status_code=status.HTTP_201_CREATED,
    response_model=MessageResponse,
)
@limiter_did.limit(LIMIT_MSG_SEND_DAY)
@limiter_did.limit(LIMIT_MSG_SEND)
async def send_message(body: MessageCreate, request: Request):
    async with transaction() as conn:
        sender_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            body.sender_agent_did,
        )
        if sender_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Sender agent not found: {body.sender_agent_did}",
            )

        receiver_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            body.receiver_agent_did,
        )
        if receiver_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Receiver agent not found: {body.receiver_agent_did}",
            )

        row = await conn.fetchrow(
            """
            INSERT INTO messages (
                message_id,
                sender_agent_id,
                receiver_agent_id,
                sender_agent_did,
                receiver_agent_did,
                message,
                metadata
            )
            VALUES (
                gen_random_uuid(),
                $1,
                $2,
                $3,
                $4,
                $5,
                $6::jsonb
            )
            RETURNING
                message_id,
                sender_agent_did,
                receiver_agent_did,
                message,
                metadata,
                created_at
            """,
            sender_row["agent_id"],
            receiver_row["agent_id"],
            body.sender_agent_did,
            body.receiver_agent_did,
            body.message,
            json.dumps(body.metadata or {}),
        )

    await cache_delete(_messages_key(body.sender_agent_did))
    await cache_delete(_messages_key(body.receiver_agent_did))
    message = _row_to_response(dict(row))
    await emit_event(
        "MESSAGE_SENT",
        body.sender_agent_did,
        {
            "message_id": str(message.message_id),
            "receiver_agent_did": body.receiver_agent_did,
            "message": body.message,
        },
    )
    await record_event(
        body.sender_agent_did,
        "MESSAGE_REPLIED",
        {"receiver_agent_did": body.receiver_agent_did},
    )
    return message


@router.get(
    "/{agent_did:path}",
    response_model=list[MessageResponse],
)
async def get_agent_messages(agent_did: str, request: Request):
    cached = await cache_get(_messages_key(agent_did))
    if cached:
        return [MessageResponse(**item) for item in cached]

    async with get_db() as conn:
        agent_exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_did = $1",
            agent_did,
        )
        if not agent_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent not found: {agent_did}",
            )

        rows = await conn.fetch(
            """
            SELECT
                message_id,
                sender_agent_did,
                receiver_agent_did,
                message,
                metadata,
                created_at
            FROM messages
            WHERE sender_agent_did = $1
               OR receiver_agent_did = $1
            ORDER BY created_at DESC
            LIMIT 50
            """,
            agent_did,
        )

    payload = [_row_to_response(dict(row)).model_dump(mode="json") for row in rows]
    await cache_set(_messages_key(agent_did), payload, ttl=TTL_MESSAGES)
    return [MessageResponse(**item) for item in payload]
