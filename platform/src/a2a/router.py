"""AgentX Platform — A2A router.

Endpoints:

  GET  /.well-known/agent.json
       → Agent Card for the AgentX platform (discovery document).

  GET  /agents/{agent_did}/.well-known/agent.json
       → Agent Card for a specific registered agent.

  POST /a2a
       → JSON-RPC 2.0 endpoint for A2A method calls:
           message/send  — submit a task from an external A2A agent
           tasks/get     — retrieve a task by ID

Both Agent Card endpoints are publicly accessible (no auth required).
The JSON-RPC endpoint validates the envelope but currently accepts
unauthenticated calls (external A2A agents may not have a platform token).

References:
  https://google.github.io/A2A/specification/
  https://www.jsonrpc.org/specification
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from ..database import get_db
from .agent_card import AgentCard, generate_agent_card, generate_platform_card
from .handler import handle_message_send, handle_tasks_get
from .jsonrpc import JSONRPCError, JSONRPCRequest, JSONRPCResponse

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


# ── JSON-RPC 2.0 endpoint ─────────────────────────────────────────────────────

# Method registry — maps A2A method names to handler coroutines
_METHODS = {
    "message/send": handle_message_send,
    "tasks/get":    handle_tasks_get,
}


@a2a_router.post(
    "/a2a",
    summary="A2A JSON-RPC 2.0 endpoint",
    description=(
        "Accepts JSON-RPC 2.0 requests compliant with the A2A protocol. "
        "Supported methods: ``message/send``, ``tasks/get``. "
        "Returns JSON-RPC 2.0 response envelopes."
    ),
)
async def a2a_jsonrpc(request: Request) -> JSONResponse:
    """Handle an A2A JSON-RPC 2.0 request.

    Parses the JSON-RPC envelope, dispatches to the appropriate handler,
    and returns a JSON-RPC 2.0 response.  All errors are returned as
    JSON-RPC error objects (never as HTTP error status codes), per spec.
    """
    # ── Parse request body ────────────────────────────────────────────────────
    try:
        body = await request.json()
    except Exception:
        resp = JSONRPCResponse.err(
            None,
            JSONRPCError.PARSE_ERROR,
            "Parse error: request body is not valid JSON",
        )
        return JSONResponse(content=resp.model_dump(exclude_none=True))

    # ── Validate JSON-RPC envelope ────────────────────────────────────────────
    try:
        rpc = JSONRPCRequest(**body)
    except Exception as exc:
        resp = JSONRPCResponse.err(
            body.get("id"),
            JSONRPCError.INVALID_REQUEST,
            f"Invalid Request: {exc}",
        )
        return JSONResponse(content=resp.model_dump(exclude_none=True))

    logger.info("a2a: JSON-RPC %s (id=%s)", rpc.method, rpc.id)

    # ── Dispatch to handler ───────────────────────────────────────────────────
    handler = _METHODS.get(rpc.method)
    if handler is None:
        resp = JSONRPCResponse.err(
            rpc.id,
            JSONRPCError.METHOD_NOT_FOUND,
            f"Method not found: '{rpc.method}'",
            data={"available_methods": list(_METHODS.keys())},
        )
        return JSONResponse(content=resp.model_dump(exclude_none=True))

    try:
        result = await handler(rpc.params)
        resp = JSONRPCResponse.ok(rpc.id, result)
    except ValueError as exc:
        resp = JSONRPCResponse.err(
            rpc.id,
            JSONRPCError.INVALID_PARAMS,
            str(exc),
        )
    except Exception as exc:
        logger.exception("a2a: internal error in method %s", rpc.method)
        resp = JSONRPCResponse.err(
            rpc.id,
            JSONRPCError.INTERNAL_ERROR,
            "Internal error",
            data=str(exc),
        )

    return JSONResponse(content=resp.model_dump(exclude_none=True))
