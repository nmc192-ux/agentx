"""
Tests: src/routers/conversations.py
Phase 23 — Community Conversations

Covers:
  POST /communities/{community_id}/threads   — create thread
  GET  /communities/{community_id}/threads   — list threads
  GET  /threads/{thread_id}                  — get thread
  POST /threads/{thread_id}/comments         — add comment
  GET  /threads/{thread_id}/comments         — list comments
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport

from src.main import app
from src.models.conversation import (
    CommentResponse,
    ThreadResponse,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

CREATOR_DID = "did:agentx:creator-001"
AUTHOR_DID  = "did:agentx:author-001"


def _make_caller(did: str = CREATOR_DID, role: str = "MEMBER"):
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = did
    return AgentRecord(
        row={
            "agent_did":       did,
            "display_name":    "Test Agent",
            "governance_role": role,
            "tier":            "STANDARD",
            "status":          "ACTIVE",
            "trust_score":     0.8,
            "bio":             None,
            "specialization":  None,
            "created_at":      datetime(2024, 1, 1, tzinfo=UTC),
            "last_seen_at":    None,
        },
        claims=claims,
    )


def _thread_response(thread_id=None, community_id=None) -> ThreadResponse:
    return ThreadResponse(
        thread_id=thread_id or uuid4(),
        community_id=community_id or uuid4(),
        post_id=None,
        creator_did=CREATOR_DID,
        title="Test Thread",
        comment_count=0,
        created_at=datetime.now(UTC),
    )


def _comment_response(comment_id=None, thread_id=None) -> CommentResponse:
    return CommentResponse(
        comment_id=comment_id or uuid4(),
        thread_id=thread_id or uuid4(),
        parent_comment_id=None,
        author_did=AUTHOR_DID,
        content="A comment",
        depth=0,
        created_at=datetime.now(UTC),
    )


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


# ── TestCreateThread ───────────────────────────────────────────────────────────

class TestCreateThread:

    @pytest.mark.asyncio
    async def test_returns_201_on_success(self, client):
        from src.auth.middleware import get_current_agent
        community_id = uuid4()
        thread       = _thread_response(community_id=community_id)

        with patch(
            "src.routers.conversations.conversation_service.create_thread",
            new=AsyncMock(return_value=thread),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(
                    f"/communities/{community_id}/threads",
                    json={"title": "Test Thread"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Test Thread"

    @pytest.mark.asyncio
    async def test_requires_authentication(self, client):
        resp = await client.post(
            f"/communities/{uuid4()}/threads",
            json={"title": "Test Thread"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_404_on_community_not_found(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.conversations.conversation_service.create_thread",
            new=AsyncMock(side_effect=ValueError("Community not found")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(
                    f"/communities/{uuid4()}/threads",
                    json={"title": "Test Thread"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_passes_community_id_to_service(self, client):
        from src.auth.middleware import get_current_agent
        community_id = uuid4()
        thread       = _thread_response(community_id=community_id)
        mock_create  = AsyncMock(return_value=thread)

        with patch(
            "src.routers.conversations.conversation_service.create_thread",
            new=mock_create,
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                await client.post(
                    f"/communities/{community_id}/threads",
                    json={"title": "Test Thread"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        mock_create.assert_awaited_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["community_id"] == community_id


# ── TestListThreads ────────────────────────────────────────────────────────────

class TestListThreads:

    @pytest.mark.asyncio
    async def test_returns_200_with_threads(self, client):
        community_id = uuid4()
        threads = [_thread_response(community_id=community_id), _thread_response(community_id=community_id)]

        with patch(
            "src.routers.conversations.conversation_service.list_threads_by_community",
            new=AsyncMock(return_value=threads),
        ):
            resp = await client.get(f"/communities/{community_id}/threads")

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_public_access(self, client):
        """GET /communities/{id}/threads does not require authentication."""
        with patch(
            "src.routers.conversations.conversation_service.list_threads_by_community",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/communities/{uuid4()}/threads")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, client):
        with patch(
            "src.routers.conversations.conversation_service.list_threads_by_community",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/communities/{uuid4()}/threads")

        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_passes_limit_and_offset(self, client):
        mock_list = AsyncMock(return_value=[])

        with patch(
            "src.routers.conversations.conversation_service.list_threads_by_community",
            new=mock_list,
        ):
            await client.get(f"/communities/{uuid4()}/threads?limit=10&offset=5")

        mock_list.assert_awaited_once()
        kwargs = mock_list.call_args[1]
        assert kwargs["limit"] == 10
        assert kwargs["offset"] == 5


# ── TestGetThread ──────────────────────────────────────────────────────────────

class TestGetThread:

    @pytest.mark.asyncio
    async def test_returns_200_with_thread(self, client):
        thread_id = uuid4()
        thread    = _thread_response(thread_id=thread_id)

        with patch(
            "src.routers.conversations.conversation_service.get_thread",
            new=AsyncMock(return_value=thread),
        ):
            resp = await client.get(f"/threads/{thread_id}")

        assert resp.status_code == 200
        assert resp.json()["thread_id"] == str(thread_id)

    @pytest.mark.asyncio
    async def test_public_access(self, client):
        thread = _thread_response()

        with patch(
            "src.routers.conversations.conversation_service.get_thread",
            new=AsyncMock(return_value=thread),
        ):
            resp = await client.get(f"/threads/{uuid4()}")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_404_if_not_found(self, client):
        with patch(
            "src.routers.conversations.conversation_service.get_thread",
            new=AsyncMock(side_effect=ValueError("Thread not found")),
        ):
            resp = await client.get(f"/threads/{uuid4()}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_includes_comment_count(self, client):
        thread_id = uuid4()
        thread    = ThreadResponse(
            thread_id=thread_id,
            community_id=uuid4(),
            post_id=None,
            creator_did=CREATOR_DID,
            title="Thread with comments",
            comment_count=7,
            created_at=datetime.now(UTC),
        )

        with patch(
            "src.routers.conversations.conversation_service.get_thread",
            new=AsyncMock(return_value=thread),
        ):
            resp = await client.get(f"/threads/{thread_id}")

        assert resp.json()["comment_count"] == 7


# ── TestAddComment ─────────────────────────────────────────────────────────────

class TestAddComment:

    @pytest.mark.asyncio
    async def test_returns_201_on_success(self, client):
        from src.auth.middleware import get_current_agent
        thread_id = uuid4()
        comment   = _comment_response(thread_id=thread_id)

        with patch(
            "src.routers.conversations.conversation_service.add_comment",
            new=AsyncMock(return_value=comment),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(
                    f"/threads/{thread_id}/comments",
                    json={"content": "A comment"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        assert resp.json()["content"] == "A comment"

    @pytest.mark.asyncio
    async def test_requires_authentication(self, client):
        resp = await client.post(
            f"/threads/{uuid4()}/comments",
            json={"content": "Unauthorized comment"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_404_if_thread_not_found(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.conversations.conversation_service.add_comment",
            new=AsyncMock(side_effect=ValueError("Thread not found: abc")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(
                    f"/threads/{uuid4()}/comments",
                    json={"content": "Comment on missing thread"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_400_on_depth_exceeded(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.conversations.conversation_service.add_comment",
            new=AsyncMock(side_effect=ValueError("Maximum comment depth reached")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(
                    f"/threads/{uuid4()}/comments",
                    json={"content": "Too deep", "parent_comment_id": str(uuid4())},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_returns_400_on_wrong_thread_parent(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.conversations.conversation_service.add_comment",
            new=AsyncMock(side_effect=ValueError("Parent comment belongs to a different thread")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(
                    f"/threads/{uuid4()}/comments",
                    json={"content": "Wrong thread", "parent_comment_id": str(uuid4())},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_passes_author_did_from_token(self, client):
        from src.auth.middleware import get_current_agent
        thread_id  = uuid4()
        comment    = _comment_response(thread_id=thread_id)
        mock_add   = AsyncMock(return_value=comment)

        with patch(
            "src.routers.conversations.conversation_service.add_comment",
            new=mock_add,
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller(did=AUTHOR_DID)
            try:
                await client.post(
                    f"/threads/{thread_id}/comments",
                    json={"content": "Auth comment"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        mock_add.assert_awaited_once()
        call_kwargs = mock_add.call_args[1]
        assert call_kwargs["author_did"] == AUTHOR_DID


# ── TestGetComments ────────────────────────────────────────────────────────────

class TestGetComments:

    @pytest.mark.asyncio
    async def test_returns_200_with_comments(self, client):
        thread_id = uuid4()
        comments  = [_comment_response(thread_id=thread_id), _comment_response(thread_id=thread_id)]

        with patch(
            "src.routers.conversations.conversation_service.get_thread_comments",
            new=AsyncMock(return_value=comments),
        ):
            resp = await client.get(f"/threads/{thread_id}/comments")

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_public_access(self, client):
        """GET /threads/{id}/comments does not require authentication."""
        with patch(
            "src.routers.conversations.conversation_service.get_thread_comments",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/threads/{uuid4()}/comments")

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, client):
        with patch(
            "src.routers.conversations.conversation_service.get_thread_comments",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/threads/{uuid4()}/comments")

        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_passes_limit_and_offset(self, client):
        mock_list = AsyncMock(return_value=[])

        with patch(
            "src.routers.conversations.conversation_service.get_thread_comments",
            new=mock_list,
        ):
            await client.get(f"/threads/{uuid4()}/comments?limit=25&offset=10")

        mock_list.assert_awaited_once()
        kwargs = mock_list.call_args[1]
        assert kwargs["limit"] == 25
        assert kwargs["offset"] == 10

    @pytest.mark.asyncio
    async def test_returns_comment_shape(self, client):
        thread_id  = uuid4()
        comment_id = uuid4()
        comment    = _comment_response(comment_id=comment_id, thread_id=thread_id)

        with patch(
            "src.routers.conversations.conversation_service.get_thread_comments",
            new=AsyncMock(return_value=[comment]),
        ):
            resp = await client.get(f"/threads/{thread_id}/comments")

        data = resp.json()
        assert data[0]["comment_id"] == str(comment_id)
        assert data[0]["author_did"] == AUTHOR_DID
        assert data[0]["depth"] == 0
