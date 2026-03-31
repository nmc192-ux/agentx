"""
AgentX Platform — Swarm Coordination Endpoints
═══════════════════════════════════════════════
Phase 4: Multi-agent swarm lifecycle

POST   /swarms              — create a swarm
GET    /swarms               — list swarms
GET    /swarms/{id}          — swarm detail with members & subtasks
POST   /swarms/{id}/join     — join a forming swarm
DELETE /swarms/{id}/leave    — leave a swarm
POST   /swarms/{id}/activate — start execution
POST   /swarms/{id}/subtasks/{sid}/result — submit subtask result
GET    /swarms/{id}/result   — get aggregated result
POST   /swarms/{id}/recruit  — auto-find qualified agents
POST   /swarms/{id}/cancel   — cancel swarm
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..models.swarm import (
    SubtaskResultSubmit,
    SwarmCreate,
    SwarmDetailResponse,
    SwarmResponse,
    SwarmResultResponse,
)
from ..services import swarm_service

router = APIRouter(prefix="/swarms", tags=["Swarms"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SwarmResponse,
    summary="Create a swarm",
)
async def create_swarm(
    body: SwarmCreate,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Create a new swarm with the authenticated agent as coordinator."""
    subtask_defs = [st.model_dump() for st in body.subtasks] if body.subtasks else []
    try:
        return await swarm_service.create_swarm(
            coordinator_did=agent.did,
            name=body.name,
            objective=body.objective,
            strategy=body.strategy.value,
            max_members=body.max_members,
            reward_pool=body.reward_pool,
            required_capabilities=body.required_capabilities,
            subtasks=subtask_defs,
            config=body.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get(
    "",
    response_model=list[SwarmResponse],
    summary="List swarms",
)
async def list_swarms(
    request: Request,
    swarm_status: str = Query(default=None, alias="status"),
    mine: bool = Query(default=False, description="Only swarms I'm in"),
    limit: int = Query(default=50, ge=1, le=200),
    agent: AgentRecord = Depends(get_current_agent),
):
    """List swarms, optionally filtered by status or membership."""
    agent_did = agent.did if mine else None
    return await swarm_service.list_swarms(status=swarm_status, agent_did=agent_did, limit=limit)


@router.get(
    "/{swarm_id}",
    response_model=SwarmDetailResponse,
    summary="Get swarm detail",
)
async def get_swarm(swarm_id: UUID, request: Request):
    """Get swarm with members and subtasks."""
    try:
        return await swarm_service.get_swarm(swarm_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/{swarm_id}/join",
    status_code=status.HTTP_200_OK,
    summary="Join a swarm",
)
async def join_swarm(
    swarm_id: UUID,
    request: Request,
    role: str = Query(default="worker", pattern="^(worker|verifier)$"),
    agent: AgentRecord = Depends(get_current_agent),
):
    """Join a forming swarm as a worker or verifier."""
    try:
        return await swarm_service.join_swarm(swarm_id, agent.did, role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.delete(
    "/{swarm_id}/leave",
    status_code=status.HTTP_200_OK,
    summary="Leave a swarm",
)
async def leave_swarm(
    swarm_id: UUID,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Leave a swarm. Coordinators cannot leave."""
    try:
        return await swarm_service.leave_swarm(swarm_id, agent.did)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.post(
    "/{swarm_id}/activate",
    response_model=SwarmDetailResponse,
    summary="Activate a swarm",
)
async def activate_swarm(
    swarm_id: UUID,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Transition swarm from FORMING to ACTIVE. Assigns subtasks to members."""
    try:
        return await swarm_service.activate_swarm(swarm_id, agent.did)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post(
    "/{swarm_id}/subtasks/{subtask_id}/result",
    summary="Submit subtask result",
)
async def submit_subtask_result(
    swarm_id: UUID,
    subtask_id: UUID,
    body: SubtaskResultSubmit,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Worker submits result for an assigned subtask. Auto-aggregates when all done."""
    try:
        return await swarm_service.submit_subtask_result(
            swarm_id, subtask_id, agent.did, body.result,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.get(
    "/{swarm_id}/result",
    response_model=SwarmResultResponse,
    summary="Get aggregated swarm result",
)
async def get_swarm_result(swarm_id: UUID, request: Request):
    """Get the final aggregated result of a completed swarm."""
    result = await swarm_service.get_swarm_result(swarm_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No result yet — swarm may still be in progress",
        )
    return result


@router.post(
    "/{swarm_id}/recruit",
    summary="Find qualified agents for swarm",
)
async def recruit_for_swarm(
    swarm_id: UUID,
    request: Request,
    limit: int = Query(default=5, ge=1, le=20),
    agent: AgentRecord = Depends(get_current_agent),
):
    """Auto-discover agents matching the swarm's required capabilities."""
    try:
        return await swarm_service.recruit_for_swarm(swarm_id, agent.did, limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post(
    "/{swarm_id}/cancel",
    summary="Cancel a swarm",
)
async def cancel_swarm(
    swarm_id: UUID,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Cancel a swarm. Refunds escrowed reward pool to coordinator."""
    try:
        return await swarm_service.cancel_swarm(swarm_id, agent.did)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
