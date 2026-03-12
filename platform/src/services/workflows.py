import json
from uuid import UUID

from ..database import get_db, transaction
from .events import emit_event
from .router import create_routed_task


async def trigger_next_step(workflow_id: UUID) -> None:
    async with transaction() as conn:
        workflow = await conn.fetchrow(
            "SELECT workflow_id, initiator_agent_did, status FROM workflows WHERE workflow_id = $1",
            workflow_id,
        )
        if workflow is None or workflow["status"] in {"COMPLETED", "FAILED"}:
            return

        current_step = await conn.fetchrow(
            """
            SELECT step_id, step_order, status
            FROM workflow_steps
            WHERE workflow_id = $1
              AND status = 'RUNNING'
            ORDER BY step_order ASC
            LIMIT 1
            """,
            workflow_id,
        )
        if current_step is not None:
            return

        next_step = await conn.fetchrow(
            """
            SELECT step_id, step_order, task_type, payload
            FROM workflow_steps
            WHERE workflow_id = $1
              AND status = 'PENDING'
            ORDER BY step_order ASC
            LIMIT 1
            """,
            workflow_id,
        )

    if next_step is None:
        async with transaction() as conn:
            workflow = await conn.fetchrow(
                """
                UPDATE workflows
                SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP
                WHERE workflow_id = $1
                RETURNING workflow_id, initiator_agent_did, workflow_type
                """,
                workflow_id,
            )
        if workflow is not None:
            await emit_event(
                "WORKFLOW_COMPLETED",
                workflow["initiator_agent_did"],
                {
                    "workflow_id": str(workflow["workflow_id"]),
                    "workflow_type": workflow["workflow_type"],
                },
            )
        return

    payload = next_step["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)

    task = await create_routed_task(
        requester_agent_did=workflow["initiator_agent_did"],
        task_type=next_step["task_type"],
        payload=payload,
    )

    if task is None:
        async with transaction() as conn:
            await conn.execute(
                """
                UPDATE workflows
                SET status = 'FAILED', updated_at = CURRENT_TIMESTAMP
                WHERE workflow_id = $1
                """,
                workflow_id,
            )
            await conn.execute(
                """
                UPDATE workflow_steps
                SET status = 'FAILED'
                WHERE step_id = $1
                """,
                next_step["step_id"],
            )
        return

    async with transaction() as conn:
        await conn.execute(
            """
            UPDATE workflows
            SET status = 'RUNNING', updated_at = CURRENT_TIMESTAMP
            WHERE workflow_id = $1
            """,
            workflow_id,
        )
        await conn.execute(
            """
            UPDATE workflow_steps
            SET status = 'RUNNING', task_id = $1
            WHERE step_id = $2
            """,
            task["task_id"],
            next_step["step_id"],
        )


async def create_workflow_record(
    initiator_agent_did: str,
    workflow_type: str,
    steps: list[dict],
) -> dict:
    async with transaction() as conn:
        initiator_exists = await conn.fetchval(
            "SELECT 1 FROM agents WHERE agent_did = $1",
            initiator_agent_did,
        )
        if not initiator_exists:
            raise ValueError(f"Initiator agent not found: {initiator_agent_did}")

        workflow = await conn.fetchrow(
            """
            INSERT INTO workflows (
                workflow_id,
                workflow_type,
                initiator_agent_did,
                status
            )
            VALUES (
                gen_random_uuid(),
                $1,
                $2,
                'PENDING'
            )
            RETURNING workflow_id, workflow_type, initiator_agent_did, status, created_at, updated_at
            """,
            workflow_type,
            initiator_agent_did,
        )

        for index, step in enumerate(steps, start=1):
            await conn.execute(
                """
                INSERT INTO workflow_steps (
                    step_id,
                    workflow_id,
                    step_order,
                    task_type,
                    payload,
                    status,
                    task_id
                )
                VALUES (
                    gen_random_uuid(),
                    $1,
                    $2,
                    $3,
                    $4::jsonb,
                    'PENDING',
                    NULL
                )
                """,
                workflow["workflow_id"],
                index,
                step["task_type"],
                json.dumps(step.get("payload") or {}),
            )

    await trigger_next_step(workflow["workflow_id"])
    await emit_event(
        "WORKFLOW_STARTED",
        initiator_agent_did,
        {
            "workflow_id": str(workflow["workflow_id"]),
            "workflow_type": workflow_type,
            "steps_count": len(steps),
        },
    )
    return await get_workflow(workflow["workflow_id"])


async def update_workflow_for_task(task_id: UUID, task_status: str) -> None:
    async with transaction() as conn:
        step = await conn.fetchrow(
            """
            SELECT step_id, workflow_id
            FROM workflow_steps
            WHERE task_id = $1
            """,
            task_id,
        )
        if step is None:
            return

        if task_status == "COMPLETED":
            await conn.execute(
                """
                UPDATE workflow_steps
                SET status = 'COMPLETED'
                WHERE step_id = $1
                """,
                step["step_id"],
            )
        elif task_status == "FAILED":
            await conn.execute(
                """
                UPDATE workflow_steps
                SET status = 'FAILED'
                WHERE step_id = $1
                """,
                step["step_id"],
            )
            await conn.execute(
                """
                UPDATE workflows
                SET status = 'FAILED', updated_at = CURRENT_TIMESTAMP
                WHERE workflow_id = $1
                """,
                step["workflow_id"],
            )
            return

    if task_status == "COMPLETED":
        await trigger_next_step(step["workflow_id"])


async def get_workflow(workflow_id: UUID) -> dict | None:
    async with get_db() as conn:
        workflow = await conn.fetchrow(
            """
            SELECT workflow_id, workflow_type, initiator_agent_did, status, created_at, updated_at
            FROM workflows
            WHERE workflow_id = $1
            """,
            workflow_id,
        )
        if workflow is None:
            return None

        steps = await conn.fetch(
            """
            SELECT step_id, step_order, task_type, payload, status, task_id, created_at
            FROM workflow_steps
            WHERE workflow_id = $1
            ORDER BY step_order ASC
            """,
            workflow_id,
        )

    parsed_steps = []
    for step in steps:
        payload = step["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        parsed_steps.append(
            {
                "step_id": step["step_id"],
                "step_order": step["step_order"],
                "task_type": step["task_type"],
                "payload": payload,
                "status": step["status"],
                "task_id": step["task_id"],
                "created_at": step["created_at"],
            }
        )

    return {
        "workflow_id": workflow["workflow_id"],
        "workflow_type": workflow["workflow_type"],
        "initiator_agent_did": workflow["initiator_agent_did"],
        "status": workflow["status"],
        "created_at": workflow["created_at"],
        "updated_at": workflow["updated_at"],
        "steps": parsed_steps,
    }
