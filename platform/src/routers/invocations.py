"""
AgentX Platform — Service Invocation Endpoints
═══════════════════════════════════════════════
Invoke another agent's registered service, complete invocations, list history.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..services import service_proxy

router = APIRouter(prefix="/invocations", tags=["Service Invocations"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Invoke a service",
)
async def invoke_service(
    request: Request,
    service_id: UUID = Query(..., description="ID of the service to invoke"),
    agent: AgentRecord = Depends(get_current_agent),
):
    """Caller requests a service invocation. The provider polls for pending work."""
    body = await request.json()
    payload = body.get("payload", {})

    try:
        return await service_proxy.invoke_service(
            caller_did=agent.agent_did,
            service_id=service_id,
            payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.post(
    "/{invocation_id}/complete",
    summary="Complete an invocation",
)
async def complete_invocation(
    invocation_id: UUID,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Provider completes a pending invocation with result payload."""
    body = await request.json()
    result = body.get("result", {})

    try:
        return await service_proxy.complete_invocation(
            invocation_id=invocation_id,
            provider_did=agent.agent_did,
            result=result,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.get(
    "",
    summary="List invocations",
)
async def list_invocations(
    request: Request,
    role: str = Query(default="both", pattern="^(caller|provider|both)$"),
    agent: AgentRecord = Depends(get_current_agent),
):
    """List service invocations for the authenticated agent."""
    return await service_proxy.list_invocations(
        agent_did=agent.agent_did,
        role=role,
    )
