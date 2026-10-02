import json

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..cache import cache_delete, cache_get, cache_set
from ..database import get_db, transaction
from ..middleware.rate_limits import limiter_did, LIMIT_MSG_SEND, LIMIT_MSG_SEND_DAY
from ..models.agent_message import MessageCreate, MessageResponse
from ..services import blocks_service
from ..services.events import emit_event
from ..services.reputation import record_event

router = APIRouter(prefix="/messages", tags=["Messages"])

TTL_MESSAGES = 60


def _messages_key(agent_did: str) -> str:
    return f"messages:{agent_did}"


_RETURNING = "message_id, sender_agent_did, receiver_agent_did, message, metadata, created_at"

# S9-6e: `messages` exists in two shapes. The init-db.sql baseline (and, per
# the reconciliation briefing, production) is DID-only; a database built by
# migration 006 alone also has NOT NULL sender_agent_id / receiver_agent_id
# (007 adds the DID columns). The INSERT used to name the id columns always,
# so sending answered 500 on the baseline. Looked up once per process.
_legacy_id_columns: bool | None = None


async def _has_legacy_id_columns(conn) -> bool:
    global _legacy_id_columns
    if _legacy_id_columns is None:
        _legacy_id_columns = bool(await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = 'messages'
                  AND column_name = 'sender_agent_id'
            )
            """
        ))
    return _legacy_id_columns


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

        if await _has_legacy_id_columns(conn):
            row = await conn.fetchrow(
                f"""
                INSERT INTO messages (
                    sender_agent_id, receiver_agent_id,
                    sender_agent_did, receiver_agent_did, message, metadata
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                RETURNING {_RETURNING}
                """,
                sender_row["agent_id"],
                receiver_row["agent_id"],
                body.sender_agent_did,
                body.receiver_agent_did,
                body.message,
                json.dumps(body.metadata or {}),
            )
        else:
            row = await conn.fetchrow(
                f"""
                INSERT INTO messages (
                    sender_agent_did, receiver_agent_did, message, metadata
                )
                VALUES ($1, $2, $3, $4::jsonb)
                RETURNING {_RETURNING}
                """,
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
        # No message text here: the events table is not private storage.
        {
            "message_id": str(message.message_id),
            "receiver_agent_did": body.receiver_agent_did,
        },
    )
    await record_event(
        body.sender_agent_did,
        "MESSAGE_REPLIED",
        {"receiver_agent_did": body.receiver_agent_did},
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
