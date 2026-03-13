"""
Tests: POST/GET/PATCH /posts
Sprint 3 — routers/posts.py
"""
import json
import pytest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from src.main import app

_FUTURE = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _post_row(
    post_id=None,
    post_type="REQUEST",
    status="ACTIVE",
    author_did="did:agentx:atlas-001",
):
    return {
        "post_id":      post_id or uuid.uuid4(),
        "author_did":   author_did,
        "post_type":    post_type,
        "title":        "Test Post",
        "content":      "Test content",
        "tags":         [],
        "visibility":   "PUBLIC",
        "status":       status,
        "collective_id": None,
        "parent_post_id": None,
        "metadata":     json.dumps({"urgency": "HIGH", "offer_rep": 50}),
        "created_at":   datetime.now(timezone.utc),
        "updated_at":   datetime.now(timezone.utc),
        "expires_at":   None,
        "reply_count":  0,
    }


@pytest.fixture
async def client():
    from httpx import ASGITransport
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
def caller():
    return _make_caller()


# ── POST /posts ───────────────────────────────────────────────────────────────

class TestCreatePost:

    @pytest.mark.asyncio
    async def test_create_request_returns_201(self, client, caller):
        from src.auth.middleware import get_current_agent_optional
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="REQUEST")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent_optional] = lambda: caller
            response = await client.post("/posts", json={
                "post_type": "REQUEST",
                "title":     "Need help with Kubernetes",
                "content":   "Looking for K8s expertise",
                "metadata":  {"urgency": "HIGH", "offer_rep": 100},
            })

        app.dependency_overrides = {}
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_task_returns_201(self, client, caller):
        from src.auth.middleware import get_current_agent_optional
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="TASK")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent_optional] = lambda: caller
            response = await client.post("/posts", json={
                "post_type": "TASK",
                "title":     "Deploy service",
                "content":   "Deploy to prod",
                "metadata":  {"sla_hours": 24, "bounty_rep": 500, "deadline": _FUTURE},
            })

        app.dependency_overrides = {}
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_prediction_returns_201(self, client, caller):
        from src.auth.middleware import get_current_agent_optional
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="PREDICTION")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent_optional] = lambda: caller
            response = await client.post("/posts", json={
                "post_type": "PREDICTION",
                "title":     "Uptime forecast",
                "content":   "Predicting Q1 uptime",
                "metadata":  {
                    "target_metric": "uptime_pct",
                    "predicted_value": 99.9,
                    "confidence": 0.87,
                    "resolve_by": _FUTURE,
                },
            })

        app.dependency_overrides = {}
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_proposal_returns_201(self, client, caller):
        from src.auth.middleware import get_current_agent_optional
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="PROPOSAL")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent_optional] = lambda: caller
            response = await client.post("/posts", json={
                "post_type": "PROPOSAL",
                "title":     "Governance vote",
                "content":   "Vote on token policy",
                "metadata":  {
                    "proposal_type": "POLICY",
                    "voting_deadline": _FUTURE,
                    "quorum_required": 0.5,
                    "pass_threshold": 0.67,
                },
            })

        app.dependency_overrides = {}
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_offer_returns_201(self, client, caller):
        from src.auth.middleware import get_current_agent_optional
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="OFFER")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent_optional] = lambda: caller
            response = await client.post("/posts", json={
                "post_type": "OFFER",
                "title":     "K8s consulting",
                "content":   "Expert K8s help",
                "metadata":  {"price": 100.0, "currency": "WORK", "availability": "IMMEDIATE"},
            })

        app.dependency_overrides = {}
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_update_returns_201(self, client, caller):
        from src.auth.middleware import get_current_agent_optional
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="UPDATE")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent_optional] = lambda: caller
            response = await client.post("/posts", json={
                "post_type": "UPDATE",
                "title":     "Progress: 75%",
                "content":   "Three quarters done",
                "metadata":  {"progress_percent": 75, "related_task_id": None},
            })

        app.dependency_overrides = {}
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_invalid_urgency_returns_422(self, client, caller):
        from src.auth.middleware import get_current_agent_optional
        app.dependency_overrides[get_current_agent_optional] = lambda: caller

        response = await client.post("/posts", json={
            "post_type": "REQUEST",
            "title":     "Bad metadata",
            "content":   "x",
            "metadata":  {"urgency": "BOGUS", "offer_rep": 10},
        })

        app.dependency_overrides = {}
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        response = await client.post("/posts", json={
            "post_type": "REQUEST", "title": "x", "content": "y",
            "metadata": {"urgency": "LOW", "offer_rep": 0},
        })
        assert response.status_code == 401


# ── GET /posts ────────────────────────────────────────────────────────────────

class TestListPosts:

    @pytest.mark.asyncio
    async def test_list_returns_200(self, client):
        with patch("src.routers.posts.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 3
            mock_conn.fetch.return_value    = [_post_row()] * 3
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            response = await client.get("/posts")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_response_shape(self, client):
        with patch("src.routers.posts.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 5
            mock_conn.fetch.return_value    = [_post_row()] * 5
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            response = await client.get("/posts")
        data = response.json()
        assert "posts" in data
        assert "total" in data
        assert data["total"] == 5

    @pytest.mark.asyncio
    async def test_filter_by_type(self, client):
        with patch("src.routers.posts.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 1
            mock_conn.fetch.return_value    = [_post_row(post_type="TASK")]
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            response = await client.get("/posts?type=TASK")
        assert response.status_code == 200


# ── GET /posts/{post_id} ──────────────────────────────────────────────────────

class TestGetPost:

    @pytest.mark.asyncio
    async def test_existing_post_returns_200(self, client):
        pid = uuid.uuid4()
        with patch("src.routers.posts.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_id=pid)
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            response = await client.get(f"/posts/{pid}")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_nonexistent_post_returns_404(self, client):
        pid = uuid.uuid4()
        with patch("src.routers.posts.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = None
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            response = await client.get(f"/posts/{pid}")
        assert response.status_code == 404


# ── POST /posts/{id}/assign ───────────────────────────────────────────────────

class TestAssignTask:

    @pytest.mark.asyncio
    async def test_assign_task_returns_200(self, client, caller):
        from src.auth.middleware import get_current_agent
        pid = uuid.uuid4()

        with (
            patch("src.routers.posts.get_db") as mock_db_ctx,
            patch("src.routers.posts.transaction") as mock_tx,
        ):
            # get_db called twice: once for post, once for assignee verification
            task_row = {
                "post_id":    pid,
                "author_did": "did:agentx:atlas-001",
                "post_type":  "TASK",
                "status":     "ACTIVE",
            }
            assignee_check = "did:agentx:bruno-001"
            updated_row = _post_row(post_id=pid, post_type="TASK", author_did="did:agentx:atlas-001")

            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = task_row
            mock_conn.fetchval.return_value = assignee_check
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db_ctx.return_value.__aexit__  = AsyncMock(return_value=False)

            tx_conn = AsyncMock()
            tx_conn.fetchrow.return_value = updated_row
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=tx_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/posts/{pid}/assign",
                json={"assignee_did": "did:agentx:bruno-001"},
            )

        app.dependency_overrides = {}
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_assign_non_task_returns_422(self, client, caller):
        from src.auth.middleware import get_current_agent
        pid = uuid.uuid4()

        with patch("src.routers.posts.get_db") as mock_db_ctx:
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = {
                "post_id": pid, "author_did": "did:agentx:atlas-001",
                "post_type": "REQUEST", "status": "ACTIVE",
            }
            mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db_ctx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/posts/{pid}/assign",
                json={"assignee_did": "did:agentx:bruno-001"},
            )

        app.dependency_overrides = {}
        assert response.status_code == 422
