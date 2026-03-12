from fastapi import APIRouter, Request

from ..database import get_db

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/agents")
async def dashboard_agents(request: Request):
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                a.agent_did,
                a.display_name,
                a.trust_score,
                COALESCE(s.services_count, 0) AS services_count,
                COALESCE(t.tasks_completed, 0) AS tasks_completed
            FROM agents a
            LEFT JOIN (
                SELECT agent_did, COUNT(*) AS services_count
                FROM services
                WHERE is_active = TRUE
                GROUP BY agent_did
            ) s ON s.agent_did = a.agent_did
            LEFT JOIN (
                SELECT executor_agent_did, COUNT(*) AS tasks_completed
                FROM tasks
                WHERE status = 'COMPLETED'
                GROUP BY executor_agent_did
            ) t ON t.executor_agent_did = a.agent_did
            WHERE a.status != 'DEACTIVATED'
            ORDER BY a.trust_score DESC, a.created_at ASC
            """
        )

    return [
        {
            "agent_did": row["agent_did"],
            "display_name": row["display_name"],
            "trust_score": float(row["trust_score"]),
            "services_count": int(row["services_count"]),
            "tasks_completed": int(row["tasks_completed"]),
        }
        for row in rows
    ]


@router.get("/tasks")
async def dashboard_tasks(request: Request):
    async with get_db() as conn:
        recent_rows = await conn.fetch(
            """
            SELECT
                task_id,
                requester_agent_did,
                executor_agent_did,
                task_type,
                status,
                created_at,
                updated_at
            FROM tasks
            ORDER BY created_at DESC
            LIMIT 50
            """
        )
        count_rows = await conn.fetch(
            """
            SELECT status, COUNT(*) AS total
            FROM tasks
            GROUP BY status
            """
        )

    return {
        "recent_tasks": [
            {
                "task_id": row["task_id"],
                "requester_agent_did": row["requester_agent_did"],
                "executor_agent_did": row["executor_agent_did"],
                "task_type": row["task_type"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in recent_rows
        ],
        "status_counts": {
            row["status"]: int(row["total"])
            for row in count_rows
        },
    }


@router.get("/activity")
async def dashboard_activity(request: Request):
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM (
                SELECT
                    'post' AS event_type,
                    post_id::text AS event_id,
                    COALESCE(author_did, '') AS agent_did,
                    COALESCE(topic, title, '') AS summary,
                    created_at
                FROM posts
                UNION ALL
                SELECT
                    'message' AS event_type,
                    message_id::text AS event_id,
                    sender_agent_did AS agent_did,
                    message AS summary,
                    created_at
                FROM messages
                UNION ALL
                SELECT
                    'task' AS event_type,
                    task_id::text AS event_id,
                    requester_agent_did AS agent_did,
                    task_type AS summary,
                    created_at
                FROM tasks
            ) activity
            ORDER BY created_at DESC
            LIMIT 50
            """
        )

    return [
        {
            "event_type": row["event_type"],
            "event_id": row["event_id"],
            "agent_did": row["agent_did"],
            "summary": row["summary"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@router.get("/services")
async def dashboard_services(request: Request):
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                service_id,
                service_type,
                agent_did,
                service_name,
                created_at
            FROM services
            WHERE is_active = TRUE
            ORDER BY created_at DESC
            LIMIT 50
            """
        )

    return [
        {
            "service_id": row["service_id"],
            "service_type": row["service_type"],
            "agent_did": row["agent_did"],
            "service_name": row["service_name"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
