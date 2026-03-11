import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from ..cache import cache_delete, cache_get, cache_set
from ..database import get_db, transaction
from ..models.agent_task import TaskCreate, TaskResponse, TaskUpdate

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


@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    response_model=TaskResponse,
)
async def create_task(body: TaskCreate, request: Request):
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
    return _row_to_response(dict(row))


@router.get(
    "/{agent_did:path}",
    response_model=list[TaskResponse],
)
async def get_tasks_for_agent(agent_did: str, request: Request):
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

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {task_id}",
        )

    task = _row_to_response(dict(row))
    await cache_delete(_tasks_key(task.requester_agent_did))
    await cache_delete(_tasks_key(task.executor_agent_did))
    return task
