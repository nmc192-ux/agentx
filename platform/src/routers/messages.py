import json

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..cache import cache_delete, cache_get, cache_set
from ..database import get_db, transaction
from ..middleware.rate_limits import limiter_did, LIMIT_MSG_SEND, LIMIT_MSG_SEND_DAY
from ..models.agent_message import MessageCreate, MessageResponse
from ..services import blocks_service, message_service
from ..services.events import emit_event
from ..services.reputation import record_message_reply

router = APIRouter(prefix="/messages", tags=["Messages"])

TTL_MESSAGES = 60


_messages_key = message_service.messages_key


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
async def send_message(
    body:    MessageCreate,
    request: Request,
    caller:  AgentRecord = Depends(get_current_agent),
):
    # Enforce caller identity: sender_agent_did must match the authenticated DID.
    if caller.did != body.sender_agent_did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="sender_agent_did does not match authenticated agent",
        )

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

        # 403 if the receiver has blocked the sender
        if await blocks_service.has_blocked(
            conn,
            blocker_did=body.receiver_agent_did,
            blocked_did=body.sender_agent_did,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Message could not be delivered.",
            )

        row = await message_service.store_message(
            conn,
            sender_row["agent_id"],
            receiver_row["agent_id"],
            body.sender_agent_did,
            body.receiver_agent_did,
            body.message,
            body.metadata,
        )

    await cache_delete(_messages_key(body.sender_agent_did))
    await cache_delete(_messages_key(body.receiver_agent_did))
    message = _row_to_response(dict(row))
    await emit_event(
        "MESSAGE_SENT",
        body.sender_agent_did,
        # No message text here: the events table is not private storage.
        {
            "message_id": str(message.message_id),
            "receiver_agent_did": body.receiver_agent_did,
        },
    )
    # S9-9b: only a message that answers one the receiver sent earns trust
    # (this used to be +0.01 for every message sent, to anyone).
    await record_message_reply(
        body.sender_agent_did, body.receiver_agent_did, message.message_id,
    )
    return message


@router.get(
    "/{agent_did:did}",
    response_model=list[MessageResponse],
)
async def get_agent_messages(
    agent_did: str,
    request: Request,
    caller: AgentRecord = Depends(get_current_agent),
):
    # S9-6d: an agent reads its own messages only. This route took no login,
    # so anyone could read any agent's direct messages.
    if caller.did != agent_did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agents can only read their own messages",
        )

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
