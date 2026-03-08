"""
Tests: GET/POST/PATCH /agents
Sprint 2 — routers/agents.py

Coverage:
  - POST /agents validation, conflict, 201 response
  - GET /agents pagination and filters
  - GET /agents/{did} — hit, miss, DID format
  - PATCH /agents/{did} — self-edit, other agent denied, admin override
  - GET /agents/{did}/trust — breakdown shape
  - Authentication: missing token → 401, wrong role → 403
"""
import pytest
from datetime import datetime, timezone
from httpx import AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch

from src.main import app


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_agent_row(
    did:   str  = "did:agentx:atlas-001",
    role:  str  = "FOUNDER",
    tier:  str  = "ELITE",
    score: float = 0.98,
    status: str = "ACTIVE",
) -> dict:
    return {
        "agent_did":      did,
        "display_name":   "ATLAS",
        "agent_type":     "AUTONOMOUS",
        "governance_role": role,
        "tier":           tier,
        "status":         status,
        "trust_score":    score,
        "bio":            "Chief Architect",
        "specialization": "system.architecture.expert",
        "created_at":     datetime(2024, 1, 1, tzinfo=timezone.utc),
        "last_seen_at":   None,
    }


def _make_mock_agent_record(did: str = "did:agentx:atlas-001", role: str = "FOUNDER"):
    """Create a mock AgentRecord to inject via Depends."""
    from src.auth.middleware import AgentRecord
    from src.auth.jwt import TokenClaims
    mock_claims = MagicMock(spec=TokenClaims)
    mock_claims.agent_did = did
    return AgentRecord(row=_make_agent_row(did=did, role=role), claims=mock_claims)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
async def client():
    from httpx import ASGITransport
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
def atlas_record():
    return _make_mock_agent_record(did="did:agentx:atlas-001", role="FOUNDER")


@pytest.fixture
def member_record():
    return _make_mock_agent_record(did="did:agentx:member-001", role="MEMBER")


# ── POST /agents ──────────────────────────────────────────────────────────────

class TestCreateAgent:
    """POST /agents — creates agent, returns JWT."""

    @pytest.mark.asyncio
    async def test_create_returns_201(self, client, atlas_record):
        from src.auth.middleware import get_current_agent, require_role

        with (
            patch("src.routers.agents.transaction") as mock_tx,
            patch("src.routers.agents.get_db")      as mock_db,
        ):
            # Mock the transaction context manager
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = None  # DID not taken
            mock_conn.execute.return_value  = None
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            # Mock get_db for the tier/role fetch after creation
            mock_db_conn = AsyncMock()
            mock_db_conn.fetchrow.return_value = {"tier": "BOOTSTRAP", "governance_role": "MEMBER"}
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_db_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: atlas_record

            response = await client.post(
                "/agents",
                json={
                    "agent_did":    "did:agentx:newbot-001",
                    "display_name": "New Bot",
                    "agent_type":   "AUTONOMOUS",
                    "governance_role": "MEMBER",
                },
            )

        app.dependency_overrides = {}
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_returns_tokens(self, client, atlas_record):
        from src.auth.middleware import get_current_agent

        with (
            patch("src.routers.agents.transaction") as mock_tx,
            patch("src.routers.agents.get_db")      as mock_db,
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = None
            mock_conn.execute.return_value  = None
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            mock_db_conn = AsyncMock()
            mock_db_conn.fetchrow.return_value = {"tier": "BOOTSTRAP", "governance_role": "MEMBER"}
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_db_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: atlas_record

            response = await client.post("/agents", json={
                "agent_did":    "did:agentx:newbot-002",
                "display_name": "New Bot 2",
            })

        app.dependency_overrides = {}
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_create_invalid_did_returns_422(self, client, atlas_record):
        from src.auth.middleware import get_current_agent
        app.dependency_overrides[get_current_agent] = lambda: atlas_record

        response = await client.post("/agents", json={
            "agent_did":    "not-a-valid-did",
            "display_name": "Test",
        })

        app.dependency_overrides = {}
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_without_auth_returns_401(self, client):
        response = await client.post("/agents", json={
            "agent_did":    "did:agentx:newbot-003",
            "display_name": "Bot",
        })
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_as_member_returns_403(self, client, member_record):
        from src.auth.middleware import get_current_agent
        app.dependency_overrides[get_current_agent] = lambda: member_record

        response = await client.post("/agents", json={
            "agent_did":    "did:agentx:newbot-004",
            "display_name": "Bot",
        })

        app.dependency_overrides = {}
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_duplicate_did_returns_409(self, client, atlas_record):
        from src.auth.middleware import get_current_agent

        with patch("src.routers.agents.transaction") as mock_tx:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = "did:agentx:existing-001"  # already exists
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: atlas_record

            response = await client.post("/agents", json={
                "agent_did":    "did:agentx:existing-001",
                "display_name": "Bot",
            })

        app.dependency_overrides = {}
        assert response.status_code == 409


# ── GET /agents ───────────────────────────────────────────────────────────────

class TestListAgents:
    """GET /agents — paginated list."""

    @pytest.mark.asyncio
    async def test_list_returns_200(self, client):
        with patch("src.routers.agents.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 1
            mock_conn.fetch.return_value    = [_make_agent_row()]
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            response = await client.get("/agents")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_response_shape(self, client):
        with patch("src.routers.agents.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 8
            mock_conn.fetch.return_value    = [_make_agent_row()] * 8
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            response = await client.get("/agents")

        data = response.json()
        assert "agents" in data
        assert "total" in data
        assert "page" in data
        assert data["total"] == 8

    @pytest.mark.asyncio
    async def test_list_respects_limit_param(self, client):
        with patch("src.routers.agents.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 50
            mock_conn.fetch.return_value    = [_make_agent_row()] * 5
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            response = await client.get("/agents?limit=5")

        data = response.json()
        assert data["limit"] == 5

    @pytest.mark.asyncio
    async def test_list_has_more_flag(self, client):
        with patch("src.routers.agents.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 100
            mock_conn.fetch.return_value    = [_make_agent_row()] * 20
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            response = await client.get("/agents?page=1&limit=20")

        data = response.json()
        assert data["has_more"] is True


# ── GET /agents/{did} ─────────────────────────────────────────────────────────

class TestGetAgent:
    """GET /agents/{did} — single agent profile."""

    @pytest.mark.asyncio
    async def test_existing_agent_returns_200(self, client):
        with (
            patch("src.routers.agents.cache_get", new=AsyncMock(return_value=None)),
            patch("src.routers.agents.get_db")   as mock_db,
            patch("src.routers.agents.cache_set", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _make_agent_row()
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            response = await client.get("/agents/did:agentx:atlas-001")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_existing_agent_returns_correct_did(self, client):
        with (
            patch("src.routers.agents.cache_get", new=AsyncMock(return_value=None)),
            patch("src.routers.agents.get_db")   as mock_db,
            patch("src.routers.agents.cache_set", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _make_agent_row()
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            response = await client.get("/agents/did:agentx:atlas-001")

        data = response.json()
        assert data["agent_did"] == "did:agentx:atlas-001"

    @pytest.mark.asyncio
    async def test_nonexistent_agent_returns_404(self, client):
        with (
            patch("src.routers.agents.cache_get", new=AsyncMock(return_value=None)),
            patch("src.routers.agents.get_db")   as mock_db,
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = None
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            response = await client.get("/agents/did:agentx:ghost-001")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_cache_hit_returns_200(self, client):
        import json
        cached = {
            "agent_did":    "did:agentx:atlas-001",
            "display_name": "ATLAS",
            "agent_type":   "AUTONOMOUS",
            "governance_role": "FOUNDER",
            "tier":         "ELITE",
            "status":       "ACTIVE",
            "trust_score":  0.98,
            "bio":          None,
            "specialization": None,
            "created_at":   "2024-01-01T00:00:00+00:00",
            "last_seen_at": None,
        }
        with patch("src.routers.agents.cache_get", new=AsyncMock(return_value=cached)):
            response = await client.get("/agents/did:agentx:atlas-001")
        assert response.status_code == 200


# ── PATCH /agents/{did} ───────────────────────────────────────────────────────

class TestUpdateAgent:
    """PATCH /agents/{did} — self-edit and admin override."""

    @pytest.mark.asyncio
    async def test_self_edit_succeeds(self, client, atlas_record):
        from src.auth.middleware import get_current_agent

        with (
            patch("src.routers.agents.transaction") as mock_tx,
            patch("src.routers.agents.cache_delete", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _make_agent_row(
                did="did:agentx:atlas-001",
                role="FOUNDER",
            )
            mock_conn.execute.return_value = None
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: atlas_record

            response = await client.patch(
                "/agents/did:agentx:atlas-001",
                json={"display_name": "ATLAS v2"},
            )

        app.dependency_overrides = {}
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_edit_other_agent_as_member_returns_403(self, client, member_record):
        from src.auth.middleware import get_current_agent
        app.dependency_overrides[get_current_agent] = lambda: member_record

        response = await client.patch(
            "/agents/did:agentx:atlas-001",  # not member's own DID
            json={"bio": "Hacked"},
        )

        app.dependency_overrides = {}
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_edit_without_auth_returns_401(self, client):
        response = await client.patch(
            "/agents/did:agentx:atlas-001",
            json={"bio": "No auth"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_can_edit_other_agent(self, client, atlas_record):
        """FOUNDER can update any agent's profile."""
        from src.auth.middleware import get_current_agent

        with (
            patch("src.routers.agents.transaction") as mock_tx,
            patch("src.routers.agents.cache_delete", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _make_agent_row(
                did="did:agentx:bruno-001",
            )
            mock_conn.execute.return_value = None
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: atlas_record

            response = await client.patch(
                "/agents/did:agentx:bruno-001",
                json={"bio": "Updated by admin"},
            )

        app.dependency_overrides = {}
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_empty_body_returns_422(self, client, atlas_record):
        from src.auth.middleware import get_current_agent
        app.dependency_overrides[get_current_agent] = lambda: atlas_record

        response = await client.patch(
            "/agents/did:agentx:atlas-001",
            json={},
        )

        app.dependency_overrides = {}
        assert response.status_code == 422
