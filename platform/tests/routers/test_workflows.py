"""
Tests: src/routers/workflows.py

POST /workflows/create turns each step into a routed task whose requester is
the workflow's initiator. Sprint 9 (S9-6a): it requires a JWT and the
initiator is the JWT caller — before, this always-on route took the initiator
from the body with no login, so anyone could create tasks in any agent's name.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app

CALLER_DID = "did:agentx:atlas-001"
OTHER_DID = "did:agentx:victim-001"
STEPS = [{"task_type": "security.audit", "payload": {"target": "x"}}]


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
def authed():
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord, get_current_agent
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = CALLER_DID
    caller = AgentRecord(
        row={
            "agent_did": CALLER_DID, "display_name": "Atlas", "governance_role": "MEMBER",
            "tier": "STANDARD", "status": "ACTIVE", "trust_score": 0.9,
        },
        claims=claims,
    )
    app.dependency_overrides[get_current_agent] = lambda: caller
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_agent, None)


def _workflow(initiator):
    now = datetime.now(timezone.utc)
    return {
        "workflow_id": uuid4(),
        "workflow_type": "security_pipeline",
        "initiator_agent_did": initiator,
        "status": "RUNNING",
        "created_at": now,
        "updated_at": now,
        "steps": [],
    }


@pytest.mark.asyncio
async def test_create_workflow_unauthenticated_401_and_nothing_created(client):
    create = AsyncMock()
    with patch("src.routers.workflows.create_workflow_record", new=create):
        resp = await client.post(
            "/workflows/create",
            json={"initiator_agent_did": OTHER_DID, "workflow_type": "x", "steps": STEPS},
        )
    assert resp.status_code == 401
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_workflow_as_another_agent_403(client, authed):
    create = AsyncMock()
    with patch("src.routers.workflows.create_workflow_record", new=create):
        resp = await client.post(
            "/workflows/create",
            json={"initiator_agent_did": OTHER_DID, "workflow_type": "x", "steps": STEPS},
        )
    assert resp.status_code == 403
    create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("body_did", [CALLER_DID, None])
async def test_create_workflow_initiator_is_the_caller(client, authed, body_did):
    body = {"workflow_type": "security_pipeline", "steps": STEPS}
    if body_did is not None:
        body["initiator_agent_did"] = body_did
    create = AsyncMock(return_value=_workflow(CALLER_DID))
    with patch("src.routers.workflows.create_workflow_record", new=create):
        resp = await client.post("/workflows/create", json=body)
    assert resp.status_code == 201
    assert resp.json()["initiator_agent_did"] == CALLER_DID
    assert create.await_args.kwargs["initiator_agent_did"] == CALLER_DID
