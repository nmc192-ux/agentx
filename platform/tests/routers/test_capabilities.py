"""
Tests: GET/POST /capabilities and /agents/{did}/capabilities
Sprint 3 — routers/capabilities.py
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from src.main import app


def _make_caller(did="did:agentx:atlas-001", role="FOUNDER"):
    from src.auth.middleware import AgentRecord
    from src.auth.jwt import TokenClaims
    mock_claims = MagicMock(spec=TokenClaims)
    mock_claims.agent_did = did
    row = {
        "agent_did": did, "display_name": "ATLAS", "governance_role": role,
        "tier": "ELITE", "status": "ACTIVE", "trust_score": 0.98,
    }
    return AgentRecord(row=row, claims=mock_claims)


def _cap_row(cap_id="infrastructure.kubernetes.advanced"):
    domain, skill, level = cap_id.split(".")
    return {
        "capability_id":        cap_id,
        "name":                 f"{skill.title()} ({level})",
        "description":          f"Capability: {cap_id}",
        "domain":               domain.upper(),
        "level":                level.upper(),
        "requires_verification": True,
        "rep_reward":           50,
        "prerequisites":        [],
        "verified_by":          [],
        "created_at":           datetime.now(timezone.utc),
    }


@pytest.fixture
async def client():
    from httpx import ASGITransport
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


class TestListCapabilities:

    @pytest.mark.asyncio
    async def test_list_returns_200(self, client):
        with patch("src.routers.capabilities.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 2
            mock_conn.fetch.return_value    = [
                _cap_row("infrastructure.kubernetes.advanced"),
                _cap_row("security.tls.intermediate"),
            ]
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)
            response = await client.get("/capabilities")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_response_shape(self, client):
        with patch("src.routers.capabilities.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 1
            mock_conn.fetch.return_value    = [_cap_row()]
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)
            response = await client.get("/capabilities")
        data = response.json()
        assert "capabilities" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_filter_by_domain(self, client):
        with patch("src.routers.capabilities.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 1
            mock_conn.fetch.return_value    = [_cap_row("infrastructure.kubernetes.expert")]
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)
            response = await client.get("/capabilities?domain=INFRASTRUCTURE")
        assert response.status_code == 200


class TestGetCapability:

    @pytest.mark.asyncio
    async def test_existing_capability_returns_200(self, client):
        cap_id = "infrastructure.kubernetes.advanced"
        with patch("src.routers.capabilities.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _cap_row(cap_id)
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)
            response = await client.get(f"/capabilities/{cap_id}")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_nonexistent_capability_returns_404(self, client):
        with patch("src.routers.capabilities.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = None
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)
            response = await client.get("/capabilities/nonexistent.cap.basic")
        assert response.status_code == 404


class TestAddAgentCapability:

    @pytest.mark.asyncio
    async def test_add_own_capability_returns_201(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller("did:agentx:atlas-001", "FOUNDER")
        cap_id = "infrastructure.kubernetes.advanced"

        with patch("src.routers.capabilities.get_db") as mock_db, \
             patch("src.routers.capabilities.transaction") as mock_tx:

            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _cap_row(cap_id)
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            tx_conn = AsyncMock()
            tx_conn.fetchrow.return_value = {
                "capability_id": cap_id,
                "verified": False,
                "verified_by_count": 0,
                "acquired_at": datetime.now(timezone.utc),
            }
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=tx_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/agents/did:agentx:atlas-001/capabilities",
                json={"capability_id": cap_id},
            )

        app.dependency_overrides = {}
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_add_other_agents_capability_returns_403(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller("did:agentx:atlas-001", "MEMBER")

        app.dependency_overrides[get_current_agent] = lambda: caller
        response = await client.post(
            "/agents/did:agentx:bruno-001/capabilities",
            json={"capability_id": "infrastructure.docker.basic"},
        )

        app.dependency_overrides = {}
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_capability_id_returns_422(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller()

        app.dependency_overrides[get_current_agent] = lambda: caller
        response = await client.post(
            "/agents/did:agentx:atlas-001/capabilities",
            json={"capability_id": "NOTVALID"},
        )

        app.dependency_overrides = {}
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        response = await client.post(
            "/agents/did:agentx:atlas-001/capabilities",
            json={"capability_id": "infrastructure.kubernetes.basic"},
        )
        assert response.status_code == 401


class TestVerifyCapability:

    @pytest.mark.asyncio
    async def test_peer_verify_returns_200(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller("did:agentx:marcus-002", "OPERATOR")

        with patch("src.routers.capabilities.transaction") as mock_tx:
            tx_conn = AsyncMock()
            tx_conn.fetchrow.return_value = {"verified_by_count": 1, "verified": False}
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=tx_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                "/agents/did:agentx:atlas-001/capabilities/infrastructure.kubernetes.advanced/verify",
                json={"endorser_did": "did:agentx:marcus-002"},
            )

        app.dependency_overrides = {}
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_self_verify_returns_422(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller("did:agentx:atlas-001", "FOUNDER")

        app.dependency_overrides[get_current_agent] = lambda: caller
        response = await client.post(
            "/agents/did:agentx:atlas-001/capabilities/infrastructure.kubernetes.advanced/verify",
            json={"endorser_did": "did:agentx:atlas-001"},
        )

        app.dependency_overrides = {}
        assert response.status_code == 422
