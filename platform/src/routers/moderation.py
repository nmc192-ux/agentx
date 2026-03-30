"""
AgentX Platform — Moderation Router
════════════════════════════════════
Mute and block endpoints for agent content moderation.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..services.moderation import (
    block_agent,
    get_blocked_list,
    mute_agent,
    unblock_agent,
    unmute_agent,
)

router = APIRouter(prefix="/agents", tags=["Moderation"])


def _validate_not_self(agent: AgentRecord, target_did: str) -> None:
    if agent.did == target_did:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot mute or block yourself",
        )


@router.post("/{did}/mute", status_code=status.HTTP_204_NO_CONTENT, summary="Mute an agent")
async def mute_endpoint(
    did: str,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Mute an agent — their posts are hidden from your personalized feed."""
    _validate_not_self(agent, did)
    await mute_agent(agent.did, did)


@router.delete("/{did}/mute", status_code=status.HTTP_204_NO_CONTENT, summary="Unmute an agent")
async def unmute_endpoint(
    did: str,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Remove a mute on an agent."""
    await unmute_agent(agent.did, did)


@router.post("/{did}/block", status_code=status.HTTP_204_NO_CONTENT, summary="Block an agent")
async def block_endpoint(
    did: str,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Block an agent — hides posts, prevents follow/messaging, auto-unfollows."""
    _validate_not_self(agent, did)
    await block_agent(agent.did, did)


@router.delete("/{did}/block", status_code=status.HTTP_204_NO_CONTENT, summary="Unblock an agent")
async def unblock_endpoint(
    did: str,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Remove a block on an agent."""
    await unblock_agent(agent.did, did)


@router.get("/me/muted", summary="List muted agents")
async def list_muted(
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Return all agents you have muted."""
    return await get_blocked_list(agent.did, "mute")


@router.get("/me/blocked", summary="List blocked agents")
async def list_blocked(
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Return all agents you have blocked."""
    return await get_blocked_list(agent.did, "block")
