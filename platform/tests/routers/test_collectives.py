"""
Tests: POST/GET /collectives + membership actions
Sprint 3 — routers/collectives.py
"""
import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from src.main import app


def _make_caller(did="did:agentx:atlas-001", role="FOUNDER", trust=0.98):
    from src.auth.middleware import AgentRecord
    from src.auth.jwt import TokenClaims
    mock_claims = MagicMock(spec=TokenClaims)
    mock_claims.agent_did = did
    row = {
        "agent_did": did, "display_name": "ATLAS", "governance_role": role,
        "tier": "ELITE", "status": "ACTIVE", "trust_score": trust,
    }
    return AgentRecord(row=row, claims=mock_claims)


def _collective_row(col_id=None, owner="did:agentx:atlas-001"):
    col_id = col_id or uuid.uuid4()
    return {
        "collective_id":   col_id,
        "name":            "Founding Council",
        "description":     "The original eight",
        "charter":         None,
        "is_public":       True,
        "owner_did":       owner,
        "member_count":    1,
        "trust_score_avg": 0.90,
        "created_at":      datetime.now(timezone.utc),
    }


@pytest.fixture
async def client():
    from httpx import ASGITransport
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


class TestCreateCollective:

    @pytest.mark.asyncio
    async def test_create_returns_201(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller(trust=0.98)

        with patch("src.routers.collectives.transaction") as mock_tx:
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _collective_row()
            mock_conn.execute.return_value  = None
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post("/collectives", json={
                "name":        "Founding Council",
                "description": "The original eight agents",
                "is_public":   True,
            })

        app.dependency_overrides = {}
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_low_trust_score_returns_403(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller(trust=0.5)  # below 0.7 threshold

        app.dependency_overrides[get_current_agent] = lambda: caller
        response = await client.post("/collectives", json={
            "name": "Low Trust Club", "description": "Bad idea",
        })

        app.dependency_overrides = {}
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        response = await client.post("/collectives", json={
            "name": "Test", "description": "Test collective",
        })
        assert response.status_code == 401


class TestListCollectives:

    @pytest.mark.asyncio
    async def test_list_returns_200(self, client):
        with patch("src.routers.collectives.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 2
            mock_conn.fetch.return_value    = [_collective_row(), _collective_row()]
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)
            response = await client.get("/collectives")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_response_shape(self, client):
        with patch("src.routers.collectives.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 1
            mock_conn.fetch.return_value    = [_collective_row()]
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)
            response = await client.get("/collectives")
        data = response.json()
        assert "collectives" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_search_query(self, client):
        with patch("src.routers.collectives.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 1
            mock_conn.fetch.return_value    = [_collective_row()]
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)
            response = await client.get("/collectives?q=Founding")
        assert response.status_code == 200


class TestGetCollective:

    @pytest.mark.asyncio
    async def test_existing_collective_returns_200(self, client):
        col_id = uuid.uuid4()
        with patch("src.routers.collectives.get_db") as mock_db:
            mock_conn = AsyncMock()
            # first fetchrow = collective, second fetch = members
            mock_conn.fetchrow.return_value = _collective_row(col_id=col_id)
            mock_conn.fetch.return_value    = []  # no members
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)
            response = await client.get(f"/collectives/{col_id}")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_nonexistent_collective_returns_404(self, client):
        col_id = uuid.uuid4()
        with patch("src.routers.collectives.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = None
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)
            response = await client.get(f"/collectives/{col_id}")
        assert response.status_code == 404


class TestJoinCollective:

    @pytest.mark.asyncio
    async def test_join_returns_202(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller()
        col_id = uuid.uuid4()

        with (
            patch("src.routers.collectives.get_db") as mock_db,
            patch("src.routers.collectives.transaction") as mock_tx,
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 1  # collective exists
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            tx_conn = AsyncMock()
            tx_conn.execute.return_value = None
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=tx_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(f"/collectives/{col_id}/join", json={})

        app.dependency_overrides = {}
        assert response.status_code == 202

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        response = await client.post(f"/collectives/{uuid.uuid4()}/join", json={})
        assert response.status_code == 401


class TestApproveMember:

    @pytest.mark.asyncio
    async def test_admin_can_approve(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller(role="FOUNDER")
        col_id = uuid.uuid4()

        with (
            patch("src.routers.collectives.get_db") as mock_db,
            patch("src.routers.collectives.transaction") as mock_tx,
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = "OWNER"  # caller's role in collective
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            tx_conn = AsyncMock()
            tx_conn.execute.return_value = "UPDATE 1"
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=tx_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/collectives/{col_id}/members/did:agentx:bruno-001/approve"
            )

        app.dependency_overrides = {}
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_non_admin_cannot_approve(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller(role="MEMBER")
        col_id = uuid.uuid4()

        with patch("src.routers.collectives.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = "MEMBER"  # caller is just MEMBER
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/collectives/{col_id}/members/did:agentx:other-001/approve"
            )

        app.dependency_overrides = {}
        assert response.status_code == 403
