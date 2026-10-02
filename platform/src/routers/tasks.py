"""
AgentX Platform — Tasks Router
═══════════════════════════════
Direct-assignment tasks (/tasks/create, /tasks/route, /tasks/{id}/update) and
the marketplace (/tasks, /tasks/{id}/bid | accept | result).

Trust boundary (Sprint 9, S9-6a): every POST requires a JWT and the acting
agent is ALWAYS the JWT caller. Identity fields in the body
(`requester_agent_did`, `creator_agent_did`, `agent_did`) are optional and are
only accepted when they name the caller; anything else fails closed with 403.
  create / route   — the caller is the requester
  POST /tasks      — the caller is the creator (their wallet is escrowed; a
                     reward the wallet cannot cover is refused with 400)
  bid              — the caller is the bidder; a creator cannot bid on their own task
  accept           — the task's creator only
  result           — the assigned executor only, once (pays the escrow once)
  cancel           — the task's creator only, while 'open' (refunds reward + fee once)
  update           — the task's executor (or a FOUNDER, for the system worker),
                     direct tasks only, forward status changes only
GET endpoints stay public reads.

Rate limit (S9-8a2): create, route and POST /tasks share one per-agent budget
(5/min, 30/hr, 100/day) — a task can be cancelled for free, so creation is
the thing to cap.
"""
import json
from uuid import UUID
import uuid
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..auth.middleware import AgentRecord, get_current_agent
from ..cache import cache_delete, cache_get, cache_set, enqueue_task
from ..database import get_db, transaction
from ..middleware.rate_limits import (
    LIMIT_TASK_CREATE,
    LIMIT_TASK_CREATE_DAY,
    LIMIT_TASK_CREATE_HR,
    TASK_CREATE_SCOPE,
    limiter_did,
)
from ..models.agent_task import TaskCreate, TaskResponse, TaskRouteCreate, TaskUpdate
from ..models.task import (
    TaskAssignmentResponse,
    TaskBid,
    TaskBidResponse,
    TaskCreate as MarketplaceTaskCreate,
    TaskResult,
    TaskResponse as MarketplaceTaskResponse,
    TaskResultResponse,
)
from ..services.events import emit_event
from ..services.reputation import record_event
from ..services.router import create_routed_task
from ..services import task_service
from ..services.workflows import update_workflow_for_task

router = APIRouter(prefix="/tasks", tags=["Tasks"])

TTL_TASKS = 60
VALID_TASK_STATUSES = {"PENDING", "IN_PROGRESS", "COMPLETED", "FAILED"}

# Direct-task lifecycle for POST /tasks/{id}/update: current status → statuses
# it may move to. COMPLETED / FAILED are final (each records a trust event, so
# re-opening a task would let an executor farm them). Marketplace statuses
# ('open', 'assigned') are absent on purpose: those tasks finish through
# POST /tasks/{id}/result, which is what releases the escrow.
ALLOWED_STATUS_TRANSITIONS = {
    "PENDING": {"PENDING", "IN_PROGRESS", "COMPLETED", "FAILED"},
    "IN_PROGRESS": {"IN_PROGRESS", "COMPLETED", "FAILED"},
}


def _require_self(agent: AgentRecord, body_did: Optional[str], field: str) -> str:
    """Return the caller's DID; refuse a body identity that names anyone else."""
    if body_did is not None and body_did != agent.did:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{field} must be the authenticated agent's DID",
        )
    return agent.did


def _tasks_key(agent_did: str) -> str:
    return f"tasks:{agent_did}"


def _row_to_response(row: dict) -> TaskResponse:
    payload = row.get("payload")
    result = row.get("result")
    if isinstance(payload, str):
        payload = json.loads(payload)
    if isinstance(result, str):
        result = json.loads(result)
    return TaskResponse(
        task_id=row["task_id"],
        requester_agent_did=row["requester_agent_did"],
        executor_agent_did=row["executor_agent_did"],
        task_type=row["task_type"],
        payload=payload,
        status=row["status"],
        result=result,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _create_task_record(body: TaskCreate, requester_agent_did: str) -> TaskResponse:
    async with transaction() as conn:
        requester_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            requester_agent_did,
        )
        if requester_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Requester agent not found: {requester_agent_did}",
            )

        executor_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            body.executor_agent_did,
        )
        if executor_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Executor agent not found: {body.executor_agent_did}",
            )

        row = await conn.fetchrow(
            """
            INSERT INTO tasks (
                task_id,
                requester_agent_id,
                executor_agent_id,
                requester_agent_did,
                executor_agent_did,
                task_type,
                payload,
                status,
                result
            )
            VALUES (
                gen_random_uuid(),
                $1,
                $2,
                $3,
                $4,
                $5,
                $6::jsonb,
                'PENDING',
                NULL
            )
            RETURNING
                task_id,
                requester_agent_did,
                executor_agent_did,
                task_type,
                payload,
                status,
                result,
                created_at,
                updated_at
            """,
            requester_row["agent_id"],
            executor_row["agent_id"],
            requester_agent_did,
            body.executor_agent_did,
            body.task_type,
            json.dumps(body.payload or {}),
        )

    await cache_delete(_tasks_key(requester_agent_did))
    await cache_delete(_tasks_key(body.executor_agent_did))
    task = _row_to_response(dict(row))
    await enqueue_task(str(task.task_id))
    await emit_event(
        "TASK_CREATED",
        body.executor_agent_did,
        {
            "task_id": str(task.task_id),
            "requester_agent_did": requester_agent_did,
            "executor_agent_did": body.executor_agent_did,
            "task_type": body.task_type,
        },
    )
    return task


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    response_model=TaskResponse,
)
@limiter_did.shared_limit(LIMIT_TASK_CREATE_DAY, scope=TASK_CREATE_SCOPE)
@limiter_did.shared_limit(LIMIT_TASK_CREATE_HR, scope=TASK_CREATE_SCOPE)
@limiter_did.shared_limit(LIMIT_TASK_CREATE, scope=TASK_CREATE_SCOPE)
async def create_task(
    body: TaskCreate,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    requester_did = _require_self(agent, body.requester_agent_did, "requester_agent_did")
    return await _create_task_record(body, requester_did)


@router.post(
    "/route",
    status_code=status.HTTP_201_CREATED,
    response_model=TaskResponse,
)
@limiter_did.shared_limit(LIMIT_TASK_CREATE_DAY, scope=TASK_CREATE_SCOPE)
@limiter_did.shared_limit(LIMIT_TASK_CREATE_HR, scope=TASK_CREATE_SCOPE)
@limiter_did.shared_limit(LIMIT_TASK_CREATE, scope=TASK_CREATE_SCOPE)
async def route_task(
    body: TaskRouteCreate,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    requester_did = _require_self(agent, body.requester_agent_did, "requester_agent_did")
    task = await create_routed_task(
        requester_agent_did=requester_did,
        task_type=body.task_type,
        payload=body.payload,
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "NO_EXECUTOR_AVAILABLE"},
        )
    return _row_to_response(task)


# ── Phase 4: Marketplace endpoints ────────────────────────────────────────────
# These MUST appear before the catch-all GET /{agent_did:path}.

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=MarketplaceTaskResponse,
    summary="Publish a marketplace task",
)
@limiter_did.shared_limit(LIMIT_TASK_CREATE_DAY, scope=TASK_CREATE_SCOPE)
@limiter_did.shared_limit(LIMIT_TASK_CREATE_HR, scope=TASK_CREATE_SCOPE)
@limiter_did.shared_limit(LIMIT_TASK_CREATE, scope=TASK_CREATE_SCOPE)
async def marketplace_create_task(
    body: MarketplaceTaskCreate,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Publish an open task that agents can discover and bid on.

    The caller is the creator; `reward` is escrowed from the caller's wallet
    in the same transaction that creates the task. A non-zero reward the
    wallet cannot cover (or no wallet at all) answers 400 and creates nothing.
    """
    creator_did = _require_self(agent, body.creator_agent_did, "creator_agent_did")
    try:
        return await task_service.create_task(
            creator_agent_did=creator_did,
            task_type=body.task_type,
            payload=body.payload,
            reward=body.reward,
        )
    except task_service.InsufficientFundsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "",
    response_model=list[MarketplaceTaskResponse],
    summary="Discover marketplace tasks",
)
async def marketplace_list_tasks(
    request: Request,
    task_status: str = Query(default="open", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Return open (or filtered) marketplace tasks available for bidding."""
    return await task_service.list_tasks(status=task_status, limit=limit)


@router.post(
    "/{task_id}/bid",
    status_code=status.HTTP_201_CREATED,
    response_model=TaskBidResponse,
    summary="Submit a bid on a marketplace task",
)
async def marketplace_bid_task(
    task_id: UUID,
    body: TaskBid,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """The caller submits a bid (confidence + price) for an open task."""
    bidder_did = _require_self(agent, body.agent_did, "agent_did")
    try:
        return await task_service.submit_bid(
            task_id=task_id,
            agent_did=bidder_did,
            confidence=body.confidence,
            bid_price=body.bid_price,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.post(
    "/{task_id}/accept",
    status_code=status.HTTP_200_OK,
    response_model=TaskAssignmentResponse,
    summary="Accept a bid and assign the task",
)
async def marketplace_accept_task(
    task_id: UUID,
    request: Request,
    bid_id: UUID = Query(..., description="The bid_id to accept"),
    agent: AgentRecord = Depends(get_current_agent),
):
    """Creator accepts a bid; task is assigned and enqueued for worker execution.

    Only the task's creator may accept.
    """
    try:
        return await task_service.assign_task(
            task_id=task_id, bid_id=bid_id, caller_did=agent.did,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.get(
    "/{task_id}/bids",
    response_model=list[TaskBidResponse],
    summary="List bids for a marketplace task",
)
async def marketplace_list_bids(task_id: UUID, request: Request):
    """Return all bids for a task, ranked by confidence descending."""
    try:
        return await task_service.list_bids(task_id=task_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/{task_id}/result",
    status_code=status.HTTP_201_CREATED,
    response_model=TaskResultResponse,
    summary="Submit task execution result",
)
async def marketplace_submit_result(
    task_id: UUID,
    body: TaskResult,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Executor submits the result; trust score is updated on success.

    Only the assigned executor may submit, and only once: the escrowed reward
    is released in the same transaction that completes the task (409 after).
    """
    executor_did = _require_self(agent, body.agent_did, "agent_did")
    try:
        return await task_service.submit_result(
            task_id=task_id,
            agent_did=executor_did,
            result_payload=body.result_payload,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except task_service.TaskConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/{task_id}/cancel",
    status_code=status.HTTP_200_OK,
    response_model=MarketplaceTaskResponse,
    summary="Cancel an open marketplace task and refund it",
)
async def marketplace_cancel_task(
    task_id: UUID,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Creator withdraws a task nobody has taken; it becomes 'cancelled'.

    The escrowed reward and the platform fee go back to the creator's wallet
    in the same transaction. Only the task's creator may cancel (403
    otherwise), only while the task is 'open' (409 otherwise).
    """
    try:
        return await task_service.cancel_task(task_id=task_id, caller_did=agent.did)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except task_service.TaskConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ── Existing endpoints (catch-all GET must remain last among GETs) ─────────────

@router.get(
    "/{agent_did:path}",
    response_model=Union[TaskResponse, list[TaskResponse]],
)
async def get_tasks_for_agent(agent_did: str, request: Request):
    try:
        task_uuid = uuid.UUID(agent_did)
    except ValueError:
        task_uuid = None

    if task_uuid is not None:
        async with get_db() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    task_id,
                    requester_agent_did,
                    executor_agent_did,
                    task_type,
                    payload,
                    status,
                    result,
                    created_at,
                    updated_at
                FROM tasks
                WHERE task_id = $1
                """,
                task_uuid,
            )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task not found: {task_uuid}",
            )
        return _row_to_response(dict(row))

    cached = await cache_get(_tasks_key(agent_did))
    if cached:
        return [TaskResponse(**item) for item in cached]

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
                task_id,
                requester_agent_did,
                executor_agent_did,
                task_type,
                payload,
                status,
                result,
                created_at,
                updated_at
            FROM tasks
            WHERE executor_agent_did = $1
               OR requester_agent_did = $1
            ORDER BY created_at DESC
            LIMIT 50
            """,
            agent_did,
        )

    payload = [_row_to_response(dict(row)).model_dump(mode="json") for row in rows]
    await cache_set(_tasks_key(agent_did), payload, ttl=TTL_TASKS)
    return [TaskResponse(**item) for item in payload]


@router.post(
    "/{task_id}/update",
    response_model=TaskResponse,
)
async def update_task(
    task_id: UUID,
    body: TaskUpdate,
    request: Request,
    agent: AgentRecord = Depends(get_current_agent),
):
    """Update a direct task's status / result.

    Only the task's executor may call this (or a FOUNDER, which is how the
    system worker acts for executors). Status only moves forward — see
    ALLOWED_STATUS_TRANSITIONS — and marketplace tasks are refused (409): they
    are completed through POST /tasks/{id}/result.
    """
    updates: list[str] = []
    values: list[object] = []
    status_value: str | None = None

    if body.status is not None:
        status_value = body.status.upper()
        if status_value not in VALID_TASK_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid task status: {body.status}",
            )
        values.append(status_value)
        updates.append(f"status = ${len(values)}")

    if body.result is not None:
        values.append(json.dumps(body.result))
        updates.append(f"result = ${len(values)}::jsonb")

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided for update",
        )

    updates.append("updated_at = CURRENT_TIMESTAMP")
    values.append(task_id)

    async with transaction() as conn:
        # Row lock: concurrent updates are checked one after the other, so a
        # task is completed (and its trust events recorded) at most once.
        existing = await conn.fetchrow(
            """
            SELECT status, executor_agent_did
            FROM tasks
            WHERE task_id = $1
            FOR UPDATE
            """,
            task_id,
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task not found: {task_id}",
            )

        if existing["executor_agent_did"] != agent.did and not agent.is_founder():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the task's executor can update it",
            )

        allowed = ALLOWED_STATUS_TRANSITIONS.get(existing["status"])
        if allowed is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Task cannot be updated here (status={existing['status']}); "
                    "finished tasks are final and marketplace tasks are completed "
                    "via POST /tasks/{task_id}/result"
                ),
            )
        if status_value is not None and status_value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Task cannot move from {existing['status']} to {status_value}",
            )

        row = await conn.fetchrow(
            f"""
            UPDATE tasks
            SET {", ".join(updates)}
            WHERE task_id = ${len(values)}
            RETURNING
                task_id,
                requester_agent_did,
                executor_agent_did,
                task_type,
                payload,
                status,
                result,
                created_at,
                updated_at
            """,
            *values,
        )

    task = _row_to_response(dict(row))
    await cache_delete(_tasks_key(task.requester_agent_did))
    await cache_delete(_tasks_key(task.executor_agent_did))

    # A task an agent gave to itself earns no reputation: otherwise one agent
    # could raise its own trust score by creating and completing its own tasks.
    earns_reputation = task.requester_agent_did != task.executor_agent_did

    if status_value == "COMPLETED" and existing["status"] != "COMPLETED":
        await emit_event(
            "TASK_COMPLETED",
            task.executor_agent_did,
            {"task_id": str(task.task_id), "task_type": task.task_type},
        )
        await emit_event(
            "TASK_EXECUTED",
            task.executor_agent_did,
            {
                "task_id": str(task.task_id),
                "task_type": task.task_type,
                "result": task.result or {},
            },
        )
        if earns_reputation:
            await record_event(
                task.executor_agent_did,
                "TASK_COMPLETED",
                {"task_id": str(task.task_id), "task_type": task.task_type},
            )
            await record_event(
                task.executor_agent_did,
                "SERVICE_USED",
                {"task_id": str(task.task_id), "task_type": task.task_type},
            )
    elif status_value == "FAILED" and existing["status"] != "FAILED":
        if earns_reputation:
            await record_event(
                task.executor_agent_did,
                "TASK_FAILED",
                {"task_id": str(task.task_id), "task_type": task.task_type},
            )

    if status_value in {"COMPLETED", "FAILED"}:
        await update_workflow_for_task(task.task_id, status_value)

    return task
