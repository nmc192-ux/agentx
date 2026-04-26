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
    author_name="ATLAS",
    author_trust=0.98,
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
        "like_count":   0,
        "reply_count":  0,
        "author_name":  author_name,
        "author_trust": author_trust,
    }


@pytest.fixture(autouse=True)
def _reset_post_rate_limiter():
    """
    POST /posts is limited to 10/min, 100/hour, 500/day per-DID and per-IP via
    slowapi's memory:// backend.  The in-process counter persists across tests
    in the same pytest session, so adding more POST tests would trip the limiter
    regardless of intent.  Clear the storage before each test.
    """
    from src.middleware.rate_limits import limiter, limiter_did
    for lim in (limiter, limiter_did):
        try:
            lim.reset()
        except Exception:
            pass
    yield


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
        from src.auth.middleware import get_current_agent
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="REQUEST")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
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
        from src.auth.middleware import get_current_agent
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="TASK")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
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
        from src.auth.middleware import get_current_agent
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="PREDICTION")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
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
        from src.auth.middleware import get_current_agent
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="PROPOSAL")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
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
        from src.auth.middleware import get_current_agent
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="OFFER")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
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
        from src.auth.middleware import get_current_agent
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="UPDATE")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post("/posts", json={
                "post_type": "UPDATE",
                "title":     "Progress: 75%",
                "content":   "Three quarters done",
                "metadata":  {"progress_percent": 75, "related_task_id": None},
            })

        app.dependency_overrides = {}
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_update_with_empty_metadata_returns_201(self, client, caller):
        """UPDATE is the casual-status post type; empty metadata must work
        (regression: pre-fix this returned 422 because progress_percent had no default)."""
        from src.auth.middleware import get_current_agent
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="UPDATE")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post("/posts", json={
                "post_type": "UPDATE",
                "title":     "What's happening",
                "content":   "Just shipped 0.2.2",
                "metadata":  {},
            })

        app.dependency_overrides = {}
        assert response.status_code == 201, response.text

    @pytest.mark.asyncio
    async def test_create_update_without_metadata_field_returns_201(self, client, caller):
        """An UPDATE post body that omits ``metadata`` entirely must still succeed."""
        from src.auth.middleware import get_current_agent
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="UPDATE")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)

            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post("/posts", json={
                "post_type": "UPDATE",
                "title":     "ping",
                "content":   "hello",
            })

        app.dependency_overrides = {}
        assert response.status_code == 201, response.text

    @pytest.mark.asyncio
    async def test_create_request_with_empty_metadata_still_422(self, client, caller):
        """Structured types (REQUEST, OFFER, TASK, PREDICTION, PROPOSAL) must still
        require their type-specific fields — only UPDATE was loosened."""
        from src.auth.middleware import get_current_agent
        app.dependency_overrides[get_current_agent] = lambda: caller
        response = await client.post("/posts", json={
            "post_type": "REQUEST",
            "title":     "x",
            "content":   "y",
            "metadata":  {},
        })
        app.dependency_overrides = {}
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_urgency_returns_422(self, client, caller):
        from src.auth.middleware import get_current_agent
        app.dependency_overrides[get_current_agent] = lambda: caller

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

    @pytest.mark.asyncio
    async def test_list_includes_author_enrichment(self, client):
        """list_posts LEFT JOINs agents — author_name and author_trust must be present."""
        with patch("src.routers.posts.get_db") as mock_db:
            mock_conn = AsyncMock()
            mock_conn.fetchval.return_value = 1
            mock_conn.fetch.return_value = [
                _post_row(author_name="MERIDIAN", author_trust=0.85)
            ]
            mock_db.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_db.return_value.__aexit__  = AsyncMock(return_value=False)

            response = await client.get("/posts")
        assert response.status_code == 200
        post = response.json()["posts"][0]
        assert post["author_name"] == "MERIDIAN"
        assert post["author_trust"] == pytest.approx(0.85)
        assert "like_count" in post


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


# ── Input size-limit tests ────────────────────────────────────────────────────

class TestPostInputLimits:
    """Validate Pydantic field-level size limits: 422 on oversized payloads."""

    @pytest.fixture
    async def client(self):
        from httpx import ASGITransport
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as c:
            yield c

    @pytest.fixture
    def caller(self):
        return _make_caller()

    # ── title limit (max 500 chars) ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_title_too_long_returns_422(self, client, caller):
        from src.auth.middleware import get_current_agent
        app.dependency_overrides[get_current_agent] = lambda: caller
        try:
            response = await client.post("/posts", json={
                "post_type": "UPDATE",
                "title":     "x" * 501,
                "content":   "Valid content",
            })
        finally:
            app.dependency_overrides = {}
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_title_at_limit_is_accepted(self, client, caller):
        """Exactly 500 chars should pass field validation (DB mock for the rest)."""
        from src.auth.middleware import get_current_agent
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="UPDATE")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post("/posts", json={
                "post_type": "UPDATE",
                "title":     "x" * 500,
                "content":   "Valid content",
                "metadata":  {"progress_percent": 0},
            })
        app.dependency_overrides = {}
        assert response.status_code == 201

    # ── content limit (max 10 000 chars) ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_content_too_long_returns_422(self, client, caller):
        from src.auth.middleware import get_current_agent
        app.dependency_overrides[get_current_agent] = lambda: caller
        try:
            response = await client.post("/posts", json={
                "post_type": "UPDATE",
                "title":     "Fine title",
                "content":   "x" * 10_001,
            })
        finally:
            app.dependency_overrides = {}
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_content_at_limit_is_accepted(self, client, caller):
        from src.auth.middleware import get_current_agent
        with (
            patch("src.routers.posts.transaction") as mock_tx,
            patch("src.routers.posts.emit_event", new=AsyncMock()),
        ):
            mock_conn = AsyncMock()
            mock_conn.fetchrow.return_value = _post_row(post_type="UPDATE")
            mock_conn.fetchval.return_value = uuid.uuid4()
            mock_tx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_tx.return_value.__aexit__  = AsyncMock(return_value=False)
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post("/posts", json={
                "post_type": "UPDATE",
                "title":     "Fine title",
                "content":   "x" * 10_000,
                "metadata":  {"progress_percent": 100},
            })
        app.dependency_overrides = {}
        assert response.status_code == 201

    # ── tags limit (max 10 tags, each ≤ 50 chars) ─────────────────────────

    @pytest.mark.asyncio
    async def test_too_many_tags_returns_422(self, client, caller):
        from src.auth.middleware import get_current_agent
        app.dependency_overrides[get_current_agent] = lambda: caller
        try:
            response = await client.post("/posts", json={
                "post_type": "UPDATE",
                "title":     "Fine title",
                "content":   "Fine content",
                "tags":      [f"tag{i}" for i in range(11)],
            })
        finally:
            app.dependency_overrides = {}
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_tag_too_long_returns_422(self, client, caller):
        from src.auth.middleware import get_current_agent
        app.dependency_overrides[get_current_agent] = lambda: caller
        try:
            response = await client.post("/posts", json={
                "post_type": "UPDATE",
                "title":     "Fine title",
                "content":   "Fine content",
                "tags":      ["x" * 51],
            })
        finally:
            app.dependency_overrides = {}
        assert response.status_code == 422

    # ── HTTP body-size limit (> 64 KB returns 413) ────────────────────────

    @pytest.mark.asyncio
    async def test_oversized_body_returns_413(self, client):
        """A request body larger than 64 KiB should be rejected at middleware level."""
        response = await client.post(
            "/posts",
            content=b"x" * 65_537,
            headers={"Content-Type": "application/json",
                     "Content-Length": str(65_537)},
        )
        assert response.status_code == 413
