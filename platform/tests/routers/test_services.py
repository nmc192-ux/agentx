"""
Tests: src/routers/services.py

POST /services/register lists a service under an agent's name. Sprint 9
(S9-6d): it requires a JWT and the agent is the JWT caller — before, this
always-on route took agent_did from the body with no login, so anyone could
list services in any agent's name.
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
            "agent_did": CALLER_DID, "display_name": "Atlas", "governance_role": "FOUNDER",
            "tier": "STANDARD", "status": "ACTIVE", "trust_score": 0.9,
        },
        claims=claims,
    )
    app.dependency_overrides[get_current_agent] = lambda: caller
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_agent, None)


def _body(agent_did):
    return {"agent_did": agent_did, "service_name": "Audits", "service_type": "security.audit"}


def _service_row(agent_did):
    return {
        "service_id": uuid4(), "agent_did": agent_did, "service_name": "Audits",
        "service_type": "security.audit", "description": None, "pricing_model": None,
        "price": None, "capabilities": "{}", "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }


async def _register(client, agent_did, headers=None):
    conn = AsyncMock()
    conn.fetchrow.side_effect = [{"agent_id": uuid4()}, _service_row(agent_did)]
    with (
        patch("src.routers.services.transaction") as mock_tx,
        patch("src.routers.services.cache_delete", new=AsyncMock()),
    ):
        mock_tx.return_value.__aenter__ = AsyncMock(return_value=conn)
        mock_tx.return_value.__aexit__ = AsyncMock(return_value=False)
        resp = await client.post("/services/register", json=_body(agent_did), headers=headers)
    return resp, mock_tx


class TestRegisterServiceIdentity:

    async def test_no_token_is_401_and_writes_nothing(self, client):
        resp, mock_tx = await _register(client, OTHER_DID)
        assert resp.status_code == 401
        mock_tx.assert_not_called()

    async def test_bad_token_is_401_and_writes_nothing(self, client):
        resp, mock_tx = await _register(
            client, OTHER_DID, headers={"Authorization": "Bearer nope"},
        )
        assert resp.status_code == 401
        mock_tx.assert_not_called()

    async def test_other_agents_did_is_403_even_for_a_founder(self, client, authed):
        resp, mock_tx = await _register(client, OTHER_DID)
        assert resp.status_code == 403
        mock_tx.assert_not_called()

    async def test_own_did_is_201(self, client, authed):
        resp, mock_tx = await _register(client, CALLER_DID)
        assert resp.status_code == 201
        assert resp.json()["agent_did"] == CALLER_DID
        mock_tx.assert_called_once()

    async def test_search_stays_public(self, client):
        with (
            patch("src.routers.services.cache_get", new=AsyncMock(return_value=[])),
            patch("src.routers.services.cache_set", new=AsyncMock()),
            patch("src.routers.services.get_db") as mock_db,
        ):
            conn = AsyncMock()
            conn.fetch.return_value = []
            mock_db.return_value.__aenter__ = AsyncMock(return_value=conn)
            mock_db.return_value.__aexit__ = AsyncMock(return_value=False)
            resp = await client.get("/services/search")
        assert resp.status_code == 200
