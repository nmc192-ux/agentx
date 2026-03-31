import json
from uuid import UUID
import uuid
from typing import Union

from fastapi import APIRouter, HTTPException, Query, Request, status

from ..cache import cache_delete, cache_get, cache_set, enqueue_task
from ..database import get_db, transaction
from ..models.agent_task import TaskCreate, TaskResponse, TaskRouteCreate, TaskUpdate
from ..models.task import (
    TaskAssignmentResponse,
    TaskBid,
    TaskBidResponse,
    TaskCreate as MarketplaceTaskCreate,
    TaskResult,
    TaskResponse as MarketplaceTaskResponse,
    TaskResultResponse,
    TaskVerdict,
)
from ..services.events import emit_event
from ..services.reputation import record_event
from ..services.router import create_routed_task
from ..services import task_service
from ..services.workflows import update_workflow_for_task

router = APIRouter(prefix="/tasks", tags=["Tasks"])

TTL_TASKS = 60
VALID_TASK_STATUSES = {"PENDING", "IN_PROGRESS", "COMPLETED", "FAILED"}


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


async def _create_task_record(body: TaskCreate) -> TaskResponse:
    async with transaction() as conn:
        requester_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            body.requester_agent_did,
        )
        if requester_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Requester agent not found: {body.requester_agent_did}",
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
            body.requester_agent_did,
            body.executor_agent_did,
            body.task_type,
            json.dumps(body.payload or {}),
        )

    await cache_delete(_tasks_key(body.requester_agent_did))
    await cache_delete(_tasks_key(body.executor_agent_did))
    task = _row_to_response(dict(row))
    await enqueue_task(str(task.task_id))
    await emit_event(
        "TASK_CREATED",
        body.executor_agent_did,
        {
            "task_id": str(task.task_id),
            "requester_agent_did": body.requester_agent_did,
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
async def create_task(body: TaskCreate, request: Request):
    return await _create_task_record(body)


@router.post(
    "/route",
    status_code=status.HTTP_201_CREATED,
    response_model=TaskResponse,
)
async def route_task(body: TaskRouteCreate, request: Request):
    task = await create_routed_task(
        requester_agent_did=body.requester_agent_did,
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
async def marketplace_create_task(body: MarketplaceTaskCreate, request: Request):
    """Publish an open task that agents can discover and bid on."""
    try:
        return await task_service.create_task(
            creator_agent_did=body.creator_agent_did,
            task_type=body.task_type,
            payload=body.payload,
            reward=body.reward,
        )
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
async def marketplace_bid_task(task_id: UUID, body: TaskBid, request: Request):
    """An agent submits a bid (confidence + price) for an open task."""
    try:
        return await task_service.submit_bid(
            task_id=task_id,
            agent_did=body.agent_did,
            confidence=body.confidence,
            bid_price=body.bid_price,
        )
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
):
    """Creator accepts a bid; task is assigned and enqueued for worker execution."""
    try:
        return await task_service.assign_task(task_id=task_id, bid_id=bid_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.post(
    "/{task_id}/result",
    status_code=status.HTTP_201_CREATED,
    response_model=TaskResultResponse,
    summary="Submit task execution result",
)
async def marketplace_submit_result(task_id: UUID, body: TaskResult, request: Request):
    """Executor submits the result; trust score is updated on success."""
    try:
        return await task_service.submit_result(
            task_id=task_id,
            agent_did=body.agent_did,
            result_payload=body.result_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/{task_id}/verify",
    response_model=TaskResultResponse,
    summary="Verify a task result (creator only)",
)
async def marketplace_verify_result(task_id: UUID, body: TaskVerdict, request: Request):
    """Task creator approves or rejects the submitted result."""
    try:
        return await task_service.verify_result(
            task_id=task_id,
            creator_did=body.verdict and request.headers.get("X-Agent-DID", ""),
            verdict=body.verdict,
            feedback=body.feedback,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.get(
    "/{task_id}/results",
    response_model=list[TaskResultResponse],
    summary="Get all results for a task",
)
async def marketplace_get_results(task_id: UUID, request: Request):
    """Return all submitted results for a task, including verification status."""
    try:
        return await task_service.get_task_results(task_id=task_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/{task_id}/bids",
    summary="List bids ranked by composite score",
)
async def marketplace_list_bids(task_id: UUID, request: Request):
    """Return bids for a task ranked by composite score (capability + trust + REP)."""
    try:
        return await task_service.list_bids(task_id=task_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post(
    "/{task_id}/cancel",
    summary="Cancel a task (creator only)",
)
async def marketplace_cancel_task(task_id: UUID, request: Request):
    """Cancel an open or assigned task. Refunds escrowed tokens."""
    creator_did = request.headers.get("X-Agent-DID", "")
    try:
        return await task_service.cancel_task(task_id=task_id, creator_did=creator_did)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


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
async def update_task(task_id: UUID, body: TaskUpdate, request: Request):
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
        existing = await conn.fetchrow(
            """
            SELECT status, executor_agent_did
            FROM tasks
            WHERE task_id = $1
            """,
            task_id,
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task not found: {task_id}",
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
        await record_event(
            task.executor_agent_did,
            "TASK_FAILED",
            {"task_id": str(task.task_id), "task_type": task.task_type},
        )

    if status_value in {"COMPLETED", "FAILED"}:
        await update_workflow_for_task(task.task_id, status_value)

    return task
