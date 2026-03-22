"""
AgentX Platform — Agent Memory Router
═══════════════════════════════════════
REST API for the server-side key-value agent memory store.

Endpoints:
  PUT    /agents/{agent_did}/memory/{key}  — Save (upsert) a value
  GET    /agents/{agent_did}/memory/{key}  — Load a value
  GET    /agents/{agent_did}/memory        — List all keys
  DELETE /agents/{agent_did}/memory/{key}  — Delete a key
  DELETE /agents/{agent_did}/memory        — Clear all keys

Authorization:
  All endpoints require a valid agent JWT (get_current_agent).
  Agents may only read/write their OWN memory (caller.did == agent_did).
  FOUNDER and OPERATOR agents may read/write on behalf of any agent.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..models.memory import MemoryClearResponse, MemoryEntry, MemoryWrite
from ..services import memory_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["Memory"])

_ADMIN_ROLES = {"FOUNDER", "OPERATOR"}


def _check_access(caller: AgentRecord, agent_did: str) -> None:
    """Raise 403 if the caller is not the owner and not an admin."""
    if caller.did != agent_did and caller.role not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agents can only access their own memory",
        )


# ── PUT /agents/{agent_did}/memory/{key} ──────────────────────────────────────

@router.put(
    "/{agent_did}/memory/{key}",
    response_model=MemoryEntry,
    summary="Save (upsert) a memory value",
    status_code=status.HTTP_200_OK,
)
async def save_memory(
    agent_did: str,
    key:       str,
    body:      MemoryWrite,
    request:   Request,
    caller:    AgentRecord = Depends(get_current_agent),
):
    """
    Store a JSON value under **key** for the given agent.

    - Creates the entry if the key does not exist.
    - Overwrites the value if the key already exists.
    - Returns the full `MemoryEntry` (including timestamps).
    """
    _check_access(caller, agent_did)

    entry = await memory_service.save(agent_did, key, body.value)
    logger.info("Memory saved: agent=%s key=%s by=%s", agent_did, key, caller.did)
    return entry


# ── GET /agents/{agent_did}/memory ────────────────────────────────────────────
# MUST be registered BEFORE /{key} to avoid the key route swallowing ""

@router.get(
    "/{agent_did}/memory",
    response_model=list[str],
    summary="List all memory keys for an agent",
)
async def list_memory_keys(
    agent_did: str,
    request:   Request,
    caller:    AgentRecord = Depends(get_current_agent),
):
    """
    Return an alphabetically sorted list of all stored keys for the agent.
    Returns an empty list if the agent has no stored memory.
    """
    _check_access(caller, agent_did)

    return await memory_service.list_keys(agent_did)


# ── GET /agents/{agent_did}/memory/{key} ──────────────────────────────────────

@router.get(
    "/{agent_did}/memory/{key}",
    response_model=MemoryEntry,
    summary="Load a memory value by key",
)
async def load_memory(
    agent_did: str,
    key:       str,
    request:   Request,
    caller:    AgentRecord = Depends(get_current_agent),
):
    """
    Retrieve the memory entry stored under **key** for the given agent.

    Returns **404** if the key does not exist.
    """
    _check_access(caller, agent_did)

    entry = await memory_service.load(agent_did, key)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory key '{key}' not found for agent {agent_did}",
        )
    return entry


# ── DELETE /agents/{agent_did}/memory ─────────────────────────────────────────
# MUST be registered BEFORE /{key} for the same reason as GET.

@router.delete(
    "/{agent_did}/memory",
    response_model=MemoryClearResponse,
    summary="Clear all memory for an agent",
)
async def clear_memory(
    agent_did: str,
    request:   Request,
    caller:    AgentRecord = Depends(get_current_agent),
):
    """
    Delete **all** stored memory entries for the given agent.

    Returns the count of deleted entries.
    """
    _check_access(caller, agent_did)

    count = await memory_service.clear(agent_did)
    logger.info("Memory cleared: agent=%s count=%d by=%s", agent_did, count, caller.did)
    return MemoryClearResponse(deleted=count)


# ── DELETE /agents/{agent_did}/memory/{key} ───────────────────────────────────

@router.delete(
    "/{agent_did}/memory/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a single memory key",
)
async def delete_memory(
    agent_did: str,
    key:       str,
    request:   Request,
    caller:    AgentRecord = Depends(get_current_agent),
):
    """
    Delete the memory entry stored under **key** for the given agent.

    Returns **404** if the key does not exist.
    """
    _check_access(caller, agent_did)

    deleted = await memory_service.delete(agent_did, key)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory key '{key}' not found for agent {agent_did}",
        )
    logger.info("Memory key deleted: agent=%s key=%s by=%s", agent_did, key, caller.did)
