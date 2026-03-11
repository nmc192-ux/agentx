import json

from fastapi import APIRouter, HTTPException, Query, Request, status

from ..cache import cache_delete, cache_get, cache_set
from ..database import get_db, transaction
from ..models.agent_service import ServiceCreate, ServiceResponse

router = APIRouter(prefix="/services", tags=["Services"])

TTL_SERVICES = 120


def _services_search_key(service_type: str | None, agent_did: str | None) -> str:
    type_part = service_type or "all"
    agent_part = agent_did or "all"
    return f"services:{type_part}:{agent_part}"


def _service_row_to_response(row: dict) -> ServiceResponse:
    capabilities = row.get("capabilities")
    if isinstance(capabilities, str):
        capabilities = json.loads(capabilities)
    return ServiceResponse(
        service_id=row["service_id"],
        agent_did=row["agent_did"],
        service_name=row["service_name"],
        service_type=row["service_type"],
        description=row.get("description"),
        pricing_model=row.get("pricing_model"),
        price=float(row["price"]) if row.get("price") is not None else None,
        capabilities=capabilities,
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=ServiceResponse,
)
async def register_service(body: ServiceCreate, request: Request):
    async with transaction() as conn:
        agent_row = await conn.fetchrow(
            "SELECT agent_id FROM agents WHERE agent_did = $1",
            body.agent_did,
        )
        if agent_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent not found: {body.agent_did}",
            )

        row = await conn.fetchrow(
            """
            INSERT INTO services (
                service_id,
                agent_id,
                agent_did,
                service_name,
                service_type,
                description,
                pricing_model,
                price,
                capabilities,
                is_active
            )
            VALUES (
                gen_random_uuid(),
                $1,
                $2,
                $3,
                $4,
                $5,
                $6,
                $7,
                $8::jsonb,
                TRUE
            )
            RETURNING
                service_id,
                agent_did,
                service_name,
                service_type,
                description,
                pricing_model,
                price,
                capabilities,
                is_active,
                created_at
            """,
            agent_row["agent_id"],
            body.agent_did,
            body.service_name,
            body.service_type,
            body.description,
            body.pricing_model,
            body.price,
            json.dumps(body.capabilities or {}),
        )

    await cache_delete(_services_search_key(body.service_type, None))
    await cache_delete(_services_search_key(body.service_type, body.agent_did))
    await cache_delete(_services_search_key(None, body.agent_did))
    await cache_delete(_services_search_key(None, None))
    return _service_row_to_response(dict(row))


@router.get(
    "/search",
    response_model=list[ServiceResponse],
)
async def search_services(
    request: Request,
    service_type: str | None = Query(default=None),
    agent_did: str | None = Query(default=None),
):
    cache_key = _services_search_key(service_type, agent_did)
    cached = await cache_get(cache_key)
    if cached:
        return [ServiceResponse(**item) for item in cached]

    conditions = ["is_active = TRUE"]
    params: list[object] = []

    if service_type:
        params.append(service_type)
        conditions.append(f"service_type = ${len(params)}")
    if agent_did:
        params.append(agent_did)
        conditions.append(f"agent_did = ${len(params)}")

    where = " AND ".join(conditions)

    async with get_db() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                service_id,
                agent_did,
                service_name,
                service_type,
                description,
                pricing_model,
                price,
                capabilities,
                is_active,
                created_at
            FROM services
            WHERE {where}
            ORDER BY created_at DESC
            """,
            *params,
        )

    payload = [_service_row_to_response(dict(row)).model_dump(mode="json") for row in rows]
    await cache_set(cache_key, payload, ttl=TTL_SERVICES)
    return [ServiceResponse(**item) for item in payload]


@router.get(
    "/agent/{agent_did:path}",
    response_model=list[ServiceResponse],
)
async def get_agent_services(agent_did: str, request: Request):
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
                service_id,
                agent_did,
                service_name,
                service_type,
                description,
                pricing_model,
                price,
                capabilities,
                is_active,
                created_at
            FROM services
            WHERE agent_did = $1
              AND is_active = TRUE
            ORDER BY created_at DESC
            """,
            agent_did,
        )

    return [_service_row_to_response(dict(row)) for row in rows]
