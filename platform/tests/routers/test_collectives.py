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


# ── Phase 6: New endpoint tests ───────────────────────────────────────────────

class TestListMembers:
    """GET /collectives/{id}/members — delegates to collective_service.get_members"""

    @pytest.mark.asyncio
    async def test_returns_200_with_members(self, client):
        col_id = uuid.uuid4()
        member = {
            "agent_did":    "did:agentx:atlas-001",
            "display_name": "ATLAS",
            "role":         "OWNER",
            "status":       "ACTIVE",
            "trust_score":  0.98,
            "joined_at":    datetime.now(timezone.utc),
        }
        from src.models.collective import CollectiveMemberResponse
        member_model = CollectiveMemberResponse(**member)

        with patch(
            "src.routers.collectives.collective_service.get_members",
            new=AsyncMock(return_value=[member_model]),
        ):
            response = await client.get(f"/collectives/{col_id}/members")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert data[0]["agent_did"] == "did:agentx:atlas-001"
        assert data[0]["role"] == "OWNER"

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_new_collective(self, client):
        col_id = uuid.uuid4()

        with patch(
            "src.routers.collectives.collective_service.get_members",
            new=AsyncMock(return_value=[]),
        ):
            response = await client.get(f"/collectives/{col_id}/members")

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_returns_404_for_missing_collective(self, client):
        col_id = uuid.uuid4()

        with patch(
            "src.routers.collectives.collective_service.get_members",
            new=AsyncMock(side_effect=ValueError("Collective not found")),
        ):
            response = await client.get(f"/collectives/{col_id}/members")

        assert response.status_code == 404


class TestAssignTaskToCollective:
    """POST /collectives/{id}/tasks — delegates to collective_service.assign_task_to_collective"""

    @pytest.mark.asyncio
    async def test_owner_can_assign_task(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller(trust=0.98)
        col_id = uuid.uuid4()
        task_id = uuid.uuid4()
        col_task_id = uuid.uuid4()

        from src.models.collective import CollectiveTaskResponse
        ct_response = CollectiveTaskResponse(
            collective_task_id=col_task_id,
            collective_id=col_id,
            task_id=task_id,
            assigned_by_did=caller.did,
            status="assigned",
            assigned_at=datetime.now(timezone.utc),
        )

        with patch(
            "src.routers.collectives.collective_service.assign_task_to_collective",
            new=AsyncMock(return_value=ct_response),
        ):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/collectives/{col_id}/tasks",
                json={"task_id": str(task_id)},
            )

        app.dependency_overrides = {}
        assert response.status_code == 201
        data = response.json()
        assert data["task_id"] == str(task_id)
        assert data["status"] == "assigned"

    @pytest.mark.asyncio
    async def test_returns_422_when_not_owner_or_admin(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller(trust=0.98)
        col_id = uuid.uuid4()

        with patch(
            "src.routers.collectives.collective_service.assign_task_to_collective",
            new=AsyncMock(side_effect=ValueError("must be OWNER or ADMIN")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/collectives/{col_id}/tasks",
                json={"task_id": str(uuid.uuid4())},
            )

        app.dependency_overrides = {}
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_returns_422_when_task_not_found(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller(trust=0.98)
        col_id = uuid.uuid4()

        with patch(
            "src.routers.collectives.collective_service.assign_task_to_collective",
            new=AsyncMock(side_effect=ValueError("Task not found")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/collectives/{col_id}/tasks",
                json={"task_id": str(uuid.uuid4())},
            )

        app.dependency_overrides = {}
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        col_id = uuid.uuid4()
        response = await client.post(
            f"/collectives/{col_id}/tasks",
            json={"task_id": str(uuid.uuid4())},
        )
        assert response.status_code == 401
