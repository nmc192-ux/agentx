"""
AgentX Platform — Developer Ecosystem Endpoints
════════════════════════════════════════════════
Phase 5: API keys, webhooks, delivery processing

API Keys:
  POST   /developer/keys          — create API key
  GET    /developer/keys          — list keys
  DELETE /developer/keys/{id}     — revoke key

Webhooks:
  POST   /developer/webhooks          — register webhook
  GET    /developer/webhooks          — list webhooks
  PATCH  /developer/webhooks/{id}     — update webhook
  DELETE /developer/webhooks/{id}     — delete webhook
  GET    /developer/webhooks/{id}/deliveries — delivery history
  POST   /developer/webhooks/process  — trigger pending deliveries
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..models.developer import (
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    WebhookCreate,
    WebhookDeliveryResponse,
    WebhookResponse,
    WebhookUpdate,
)
from ..services import api_keys, webhooks
from ..database import get_db

router = APIRouter(prefix="/developer", tags=["Developer"])


# ── API Keys ─────────────────────────────────────────────────────────────────

@router.post(
    "/keys",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiKeyCreatedResponse,
    summary="Create API key",
)
async def create_api_key(
    body: ApiKeyCreate,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Create a new API key. The full key is returned only once — store it securely."""
    try:
        return await api_keys.create_api_key(
            agent_did=agent.did,
            name=body.name,
            scopes=body.scopes,
            expires_in_days=body.expires_in_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get(
    "/keys",
    response_model=list[ApiKeyResponse],
    summary="List API keys",
)
async def list_api_keys(
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """List all API keys for the authenticated agent."""
    return await api_keys.list_api_keys(agent.did)


@router.delete(
    "/keys/{key_id}",
    summary="Revoke API key",
)
async def revoke_api_key(
    key_id: UUID,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Deactivate an API key. It can no longer be used for authentication."""
    try:
        return await api_keys.revoke_api_key(key_id, agent.did)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ── Webhooks ─────────────────────────────────────────────────────────────────

@router.post(
    "/webhooks",
    status_code=status.HTTP_201_CREATED,
    response_model=WebhookResponse,
    summary="Register webhook",
)
async def create_webhook(
    body: WebhookCreate,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Register a webhook URL to receive events. Secret is returned only once."""
    try:
        return await webhooks.create_webhook(
            agent_did=agent.did,
            callback_url=body.callback_url,
            name=body.name,
            event_types=body.event_types,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get(
    "/webhooks",
    response_model=list[WebhookResponse],
    summary="List webhooks",
)
async def list_webhooks(
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """List all registered webhooks for the authenticated agent."""
    return await webhooks.list_webhooks(agent.did)


@router.patch(
    "/webhooks/{webhook_id}",
    response_model=WebhookResponse,
    summary="Update webhook",
)
async def update_webhook(
    webhook_id: UUID,
    body: WebhookUpdate,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Update a webhook's URL, event filter, or active status."""
    try:
        return await webhooks.update_webhook(
            webhook_id=webhook_id,
            agent_did=agent.did,
            callback_url=body.callback_url,
            event_types=body.event_types,
            is_active=body.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.delete(
    "/webhooks/{webhook_id}",
    summary="Delete webhook",
)
async def delete_webhook(
    webhook_id: UUID,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Delete a webhook registration."""
    try:
        return await webhooks.delete_webhook(webhook_id, agent.did)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/webhooks/{webhook_id}/deliveries",
    response_model=list[WebhookDeliveryResponse],
    summary="Webhook delivery history",
)
async def get_deliveries(
    webhook_id: UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    agent: AgentRecord = Depends(get_current_agent),
):
    """Get delivery history for a webhook."""
    async with get_db() as conn:
        # Verify ownership
        owner = await conn.fetchval(
            "SELECT agent_did FROM webhooks WHERE webhook_id = $1",
            webhook_id,
        )
        if owner != agent.did:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")

        rows = await conn.fetch(
            """
            SELECT delivery_id, webhook_id, event_id, event_type,
                   status, response_code, attempt_count, last_attempt, created_at
            FROM webhook_deliveries
            WHERE webhook_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            webhook_id, limit,
        )

    return [dict(r) for r in rows]


@router.post(
    "/webhooks/process",
    summary="Process pending webhook deliveries",
    tags=["Internal"],
)
async def process_deliveries(
    request: Request,
    batch_size: int = Query(default=50, ge=1, le=200),
):
    """Trigger processing of pending webhook deliveries. Called by background worker."""
    return await webhooks.process_pending_deliveries(batch_size=batch_size)
