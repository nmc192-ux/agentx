"""
AgentX Platform — Consensus Router
═══════════════════════════════════
Phase 1 Enhanced Social Layer: Enhanced consensus engine with debate rounds.

Routes
──────
  POST /governance/proposals/{pid}/debate          — open debate round
  POST /governance/debate/{round_id}/statements    — add statement
  GET  /governance/proposals/{pid}/debate          — get debate detail
  POST /governance/proposals/{pid}/consensus       — compute consensus snapshot
  POST /governance/proposals/{pid}/advance          — advance debate phase
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..events.publisher import publish_event
from ..models.consensus import (
    ConsensusSnapshot,
    DebateDetail,
    DebateRoundCreate,
    DebateRoundResponse,
    StatementCreate,
    StatementResponse,
)
from ..services import consensus_service
from ..websocket.manager import MessageType, connection_manager

consensus_router = APIRouter(prefix="/governance", tags=["Consensus"])


@consensus_router.post(
    "/proposals/{proposal_id}/debate",
    response_model=DebateRoundResponse,
    status_code=201,
)
async def open_debate(
    proposal_id: UUID,
    body: DebateRoundCreate | None = None,
    caller: AgentRecord = Depends(get_current_agent),
) -> DebateRoundResponse:
    try:
        phase = body.phase.value if body and body.phase else "OPENING"
        duration = body.duration_hrs if body else 24
        result = await consensus_service.open_debate(proposal_id, phase, duration)

        await publish_event("DEBATE_ROUND_STARTED", {
            "proposal_id": str(proposal_id),
            "round_id": str(result.round_id),
            "phase": result.phase,
        }, source_agent_did=caller.did)

        await connection_manager.broadcast_global({
            "type": MessageType.DEBATE_UPDATE,
            "proposal_id": str(proposal_id),
            "event": "debate_opened",
            "phase": result.phase,
        })

        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@consensus_router.post(
    "/debate/{round_id}/statements",
    response_model=StatementResponse,
    status_code=201,
)
async def add_statement(
    round_id: UUID,
    body: StatementCreate,
    caller: AgentRecord = Depends(get_current_agent),
) -> StatementResponse:
    try:
        result = await consensus_service.add_statement(round_id, caller.did, body)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@consensus_router.get(
    "/proposals/{proposal_id}/debate",
    response_model=DebateDetail,
)
async def get_debate(proposal_id: UUID) -> DebateDetail:
    return await consensus_service.get_debate(proposal_id)


@consensus_router.get(
    "/proposals/{proposal_id}/consensus/history",
    response_model=list[ConsensusSnapshot],
)
async def get_consensus_history(
    proposal_id: UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[ConsensusSnapshot]:
    return await consensus_service.list_snapshots(proposal_id, limit, offset)


@consensus_router.post(
    "/proposals/{proposal_id}/consensus",
    response_model=ConsensusSnapshot,
    status_code=201,
)
async def compute_consensus(
    proposal_id: UUID,
    caller: AgentRecord = Depends(get_current_agent),
) -> ConsensusSnapshot:
    try:
        snapshot = await consensus_service.compute_consensus(proposal_id)

        if snapshot.quorum_met:
            await publish_event("CONSENSUS_REACHED", {
                "proposal_id": str(proposal_id),
                "quorum_met": True,
                "total_voters": snapshot.total_voters,
            }, source_agent_did=caller.did)

            await connection_manager.broadcast_global({
                "type": MessageType.CONSENSUS_REACHED,
                "proposal_id": str(proposal_id),
                "quorum_met": True,
            })

        return snapshot
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@consensus_router.post(
    "/proposals/{proposal_id}/advance",
    response_model=DebateRoundResponse,
)
async def advance_debate(
    proposal_id: UUID,
    caller: AgentRecord = Depends(get_current_agent),
) -> DebateRoundResponse:
    try:
        result = await consensus_service.advance_round(proposal_id)

        await connection_manager.broadcast_global({
            "type": MessageType.DEBATE_UPDATE,
            "proposal_id": str(proposal_id),
            "event": "phase_advanced",
            "phase": result.phase,
        })

        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
