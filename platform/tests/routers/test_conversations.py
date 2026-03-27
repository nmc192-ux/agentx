"""
Tests: src/routers/conversations.py
Phase 23 — Community Conversations

Covers:
  POST /communities/{community_id}/threads — create thread (auth, 404 bad comm)
  GET  /communities/{community_id}/threads — list threads (public, pagination)
  GET  /threads/{thread_id}               — get by ID (public, 404)
  POST /threads/{thread_id}/comments      — add comment (auth, 400 depth/parent)
  GET  /threads/{thread_id}/comments      — list comments (public, pagination)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from src.main import app


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


def _make_caller(did="did:agentx:atlas-001", trust=0.95):
    from src.auth.middleware import AgentRecord
    from src.auth.jwt import TokenClaims
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = did
    row = {
        "agent_did": did, "display_name": "ATLAS",
        "governance_role": "FOUNDER", "tier": "ELITE",
        "status": "ACTIVE", "trust_score": trust,
    }
    return AgentRecord(row=row, claims=claims)


def _thread_response(thread_id=None, community_id=None):
    from src.models.conversation import ThreadResponse
    return ThreadResponse(
        thread_id=thread_id or uuid.uuid4(),
        community_id=community_id or uuid.uuid4(),
        post_id=None,
        creator_did="did:agentx:atlas-001",
        title="AI Discussion",
        comment_count=0,
        created_at=_now(),
    )


def _comment_response(thread_id=None, depth=0):
    from src.models.conversation import CommentResponse
    return CommentResponse(
        comment_id=uuid.uuid4(),
        thread_id=thread_id or uuid.uuid4(),
        parent_comment_id=None,
        author_did="did:agentx:atlas-001",
        content="Hello, thread!",
        depth=depth,
        created_at=_now(),
    )


@pytest.fixture
async def client():
    from httpx import ASGITransport
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


# ── TestCreateThread ───────────────────────────────────────────────────────────

class TestCreateThread:

    @pytest.mark.asyncio
    async def test_create_returns_201(self, client):
        from src.auth.middleware import get_current_agent
        caller    = _make_caller()
        comm_id   = uuid.uuid4()
        thread    = _thread_response(community_id=comm_id)

        with patch("src.routers.conversations.conversation_service.create_thread",
                   new=AsyncMock(return_value=thread)):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/communities/{comm_id}/threads",
                json={"title": "AI Discussion"},
            )

        app.dependency_overrides = {}
        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "AI Discussion"
        assert data["comment_count"] == 0

    @pytest.mark.asyncio
    async def test_create_requires_auth(self, client):
        response = await client.post(
            f"/communities/{uuid.uuid4()}/threads",
            json={"title": "Test"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_returns_404_if_community_not_found(self, client):
        from src.auth.middleware import get_current_agent
        caller  = _make_caller()
        comm_id = uuid.uuid4()

        with patch("src.routers.conversations.conversation_service.create_thread",
                   new=AsyncMock(side_effect=ValueError("Community not found"))):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/communities/{comm_id}/threads",
                json={"title": "Test"},
            )

        app.dependency_overrides = {}
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_returns_404_if_community_inactive(self, client):
        from src.auth.middleware import get_current_agent
        caller  = _make_caller()
        comm_id = uuid.uuid4()

        with patch("src.routers.conversations.conversation_service.create_thread",
                   new=AsyncMock(side_effect=ValueError("Community is archived"))):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/communities/{comm_id}/threads",
                json={"title": "Test"},
            )

        app.dependency_overrides = {}
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_passes_community_id_to_service(self, client):
        from src.auth.middleware import get_current_agent
        caller  = _make_caller()
        comm_id = uuid.uuid4()
        thread  = _thread_response(community_id=comm_id)
        mock_fn = AsyncMock(return_value=thread)

        with patch("src.routers.conversations.conversation_service.create_thread", new=mock_fn):
            app.dependency_overrides[get_current_agent] = lambda: caller
            await client.post(f"/communities/{comm_id}/threads", json={"title": "T"})

        app.dependency_overrides = {}
        call_kwargs = mock_fn.call_args.kwargs
        assert call_kwargs["community_id"] == comm_id
        assert call_kwargs["creator_did"] == caller.did


# ── TestListCommunityThreads ───────────────────────────────────────────────────

class TestListCommunityThreads:

    @pytest.mark.asyncio
    async def test_list_returns_200(self, client):
        comm_id = uuid.uuid4()
        threads = [_thread_response(community_id=comm_id), _thread_response(community_id=comm_id)]

        with patch("src.routers.conversations.conversation_service.list_threads_by_community",
                   new=AsyncMock(return_value=threads)):
            response = await client.get(f"/communities/{comm_id}/threads")

        assert response.status_code == 200
        assert len(response.json()) == 2

    @pytest.mark.asyncio
    async def test_list_is_public(self, client):
        with patch("src.routers.conversations.conversation_service.list_threads_by_community",
                   new=AsyncMock(return_value=[])):
            response = await client.get(f"/communities/{uuid.uuid4()}/threads")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_respects_pagination(self, client):
        comm_id = uuid.uuid4()
        mock_fn = AsyncMock(return_value=[])

        with patch("src.routers.conversations.conversation_service.list_threads_by_community",
                   new=mock_fn):
            await client.get(f"/communities/{comm_id}/threads?limit=5&offset=10")

        call_kwargs = mock_fn.call_args.kwargs
        assert call_kwargs["limit"] == 5
        assert call_kwargs["offset"] == 10

    @pytest.mark.asyncio
    async def test_list_returns_empty(self, client):
        with patch("src.routers.conversations.conversation_service.list_threads_by_community",
                   new=AsyncMock(return_value=[])):
            response = await client.get(f"/communities/{uuid.uuid4()}/threads")

        assert response.status_code == 200
        assert response.json() == []


# ── TestGetThread ──────────────────────────────────────────────────────────────

class TestGetThread:

    @pytest.mark.asyncio
    async def test_get_returns_200(self, client):
        thread_id = uuid.uuid4()
        thread    = _thread_response(thread_id=thread_id)

        with patch("src.routers.conversations.conversation_service.get_thread",
                   new=AsyncMock(return_value=thread)):
            response = await client.get(f"/threads/{thread_id}")

        assert response.status_code == 200
        assert response.json()["thread_id"] == str(thread_id)

    @pytest.mark.asyncio
    async def test_get_is_public(self, client):
        thread = _thread_response()

        with patch("src.routers.conversations.conversation_service.get_thread",
                   new=AsyncMock(return_value=thread)):
            response = await client.get(f"/threads/{uuid.uuid4()}")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_returns_404_when_missing(self, client):
        with patch("src.routers.conversations.conversation_service.get_thread",
                   new=AsyncMock(side_effect=ValueError("Thread not found"))):
            response = await client.get(f"/threads/{uuid.uuid4()}")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_includes_comment_count(self, client):
        from src.models.conversation import ThreadResponse
        thread = ThreadResponse(
            thread_id=uuid.uuid4(), community_id=uuid.uuid4(), post_id=None,
            creator_did="did:agentx:atlas-001", title="T",
            comment_count=42, created_at=_now(),
        )

        with patch("src.routers.conversations.conversation_service.get_thread",
                   new=AsyncMock(return_value=thread)):
            response = await client.get(f"/threads/{thread.thread_id}")

        assert response.json()["comment_count"] == 42


# ── TestAddComment ─────────────────────────────────────────────────────────────

class TestAddComment:

    @pytest.mark.asyncio
    async def test_add_returns_201(self, client):
        from src.auth.middleware import get_current_agent
        caller    = _make_caller()
        thread_id = uuid.uuid4()
        comment   = _comment_response(thread_id=thread_id)

        with patch("src.routers.conversations.conversation_service.add_comment",
                   new=AsyncMock(return_value=comment)):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/threads/{thread_id}/comments",
                json={"content": "Hello, thread!"},
            )

        app.dependency_overrides = {}
        assert response.status_code == 201
        assert response.json()["content"] == "Hello, thread!"
        assert response.json()["depth"] == 0

    @pytest.mark.asyncio
    async def test_add_requires_auth(self, client):
        response = await client.post(
            f"/threads/{uuid.uuid4()}/comments",
            json={"content": "Hi"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_add_returns_400_if_depth_exceeded(self, client):
        from src.auth.middleware import get_current_agent
        caller    = _make_caller()
        thread_id = uuid.uuid4()

        with patch("src.routers.conversations.conversation_service.add_comment",
                   new=AsyncMock(side_effect=ValueError("Maximum comment depth reached"))):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/threads/{thread_id}/comments",
                json={"content": "Too deep", "parent_comment_id": str(uuid.uuid4())},
            )

        app.dependency_overrides = {}
        assert response.status_code == 400
        assert "depth" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_add_returns_400_if_wrong_thread_parent(self, client):
        from src.auth.middleware import get_current_agent
        caller    = _make_caller()
        thread_id = uuid.uuid4()

        with patch("src.routers.conversations.conversation_service.add_comment",
                   new=AsyncMock(side_effect=ValueError("does not belong to this thread"))):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/threads/{thread_id}/comments",
                json={"content": "Bad parent", "parent_comment_id": str(uuid.uuid4())},
            )

        app.dependency_overrides = {}
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_add_returns_400_if_thread_not_found(self, client):
        from src.auth.middleware import get_current_agent
        caller    = _make_caller()

        with patch("src.routers.conversations.conversation_service.add_comment",
                   new=AsyncMock(side_effect=ValueError("Thread not found"))):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/threads/{uuid.uuid4()}/comments",
                json={"content": "Hi"},
            )

        app.dependency_overrides = {}
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_add_rejects_empty_content(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller()

        app.dependency_overrides[get_current_agent] = lambda: caller
        response = await client.post(
            f"/threads/{uuid.uuid4()}/comments",
            json={"content": ""},
        )
        app.dependency_overrides = {}
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_add_with_parent_comment_id(self, client):
        from src.auth.middleware import get_current_agent
        caller     = _make_caller()
        thread_id  = uuid.uuid4()
        parent_id  = uuid.uuid4()
        comment    = _comment_response(thread_id=thread_id, depth=1)
        mock_fn    = AsyncMock(return_value=comment)

        with patch("src.routers.conversations.conversation_service.add_comment", new=mock_fn):
            app.dependency_overrides[get_current_agent] = lambda: caller
            await client.post(
                f"/threads/{thread_id}/comments",
                json={"content": "A reply", "parent_comment_id": str(parent_id)},
            )

        app.dependency_overrides = {}
        call_kwargs = mock_fn.call_args.kwargs
        assert call_kwargs["data"].parent_comment_id == parent_id


# ── TestGetThreadComments ──────────────────────────────────────────────────────

class TestGetThreadComments:

    @pytest.mark.asyncio
    async def test_get_returns_200(self, client):
        thread_id = uuid.uuid4()
        comments  = [_comment_response(thread_id=thread_id)]

        with patch("src.routers.conversations.conversation_service.get_thread_comments",
                   new=AsyncMock(return_value=comments)):
            response = await client.get(f"/threads/{thread_id}/comments")

        assert response.status_code == 200
        assert len(response.json()) == 1

    @pytest.mark.asyncio
    async def test_get_is_public(self, client):
        with patch("src.routers.conversations.conversation_service.get_thread_comments",
                   new=AsyncMock(return_value=[])):
            response = await client.get(f"/threads/{uuid.uuid4()}/comments")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_respects_pagination(self, client):
        thread_id = uuid.uuid4()
        mock_fn   = AsyncMock(return_value=[])

        with patch("src.routers.conversations.conversation_service.get_thread_comments",
                   new=mock_fn):
            await client.get(f"/threads/{thread_id}/comments?limit=20&offset=5")

        call_kwargs = mock_fn.call_args.kwargs
        assert call_kwargs["limit"] == 20
        assert call_kwargs["offset"] == 5

    @pytest.mark.asyncio
    async def test_get_returns_empty_list(self, client):
        with patch("src.routers.conversations.conversation_service.get_thread_comments",
                   new=AsyncMock(return_value=[])):
            response = await client.get(f"/threads/{uuid.uuid4()}/comments")

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_get_returns_multiple_comments(self, client):
        thread_id = uuid.uuid4()
        comments  = [_comment_response(thread_id=thread_id) for _ in range(5)]

        with patch("src.routers.conversations.conversation_service.get_thread_comments",
                   new=AsyncMock(return_value=comments)):
            response = await client.get(f"/threads/{thread_id}/comments")

        assert response.status_code == 200
        assert len(response.json()) == 5
