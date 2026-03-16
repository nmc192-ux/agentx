"""
Tests: src/routers/communities.py
Phase 22 — Agent Communities

Covers:
  POST /communities
  GET  /communities
  GET  /communities/{community_id}
  GET  /communities/slug/{slug}
  POST /communities/{community_id}/join
  POST /communities/{community_id}/leave
  GET  /communities/{community_id}/members
  POST /communities/{community_id}/posts
  GET  /communities/{community_id}/feed
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport

from src.main import app
from src.models.community import (
    CommunityMember,
    CommunityPost,
    CommunityResponse,
)
from src.models.post import PostResponse


# ── Helpers ────────────────────────────────────────────────────────────────────

CREATOR_DID = "did:agentx:creator-001"
MEMBER_DID  = "did:agentx:member-001"


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


def _community(community_id=None, name="Test Community", slug="test-community") -> CommunityResponse:
    return CommunityResponse(
        community_id=community_id or uuid4(),
        name=name,
        slug=slug,
        description="A test community",
        creator_did=CREATOR_DID,
        visibility="PUBLIC",
        status="ACTIVE",
        member_count=1,
        metadata={},
        created_at=datetime.now(UTC),
    )


def _member(community_id=None, agent_did=MEMBER_DID) -> CommunityMember:
    return CommunityMember(
        community_id=community_id or uuid4(),
        agent_did=agent_did,
        role="MEMBER",
        joined_at=datetime.now(UTC),
    )


def _community_post(community_id=None, post_id=None) -> CommunityPost:
    return CommunityPost(
        community_post_id=uuid4(),
        community_id=community_id or uuid4(),
        post_id=post_id or uuid4(),
        created_at=datetime.now(UTC),
    )


def _post_response() -> PostResponse:
    return PostResponse(
        post_id=uuid4(),
        author_did=CREATOR_DID,
        post_type="UPDATE",
        title="Test Post",
        content="Content",
        tags=[],
        visibility="PUBLIC",
        status="ACTIVE",
        collective_id=None,
        parent_post_id=None,
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        expires_at=None,
        like_count=0,
        reply_count=0,
    )


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


# ── TestCreateCommunity ────────────────────────────────────────────────────────

class TestCreateCommunity:

    @pytest.mark.asyncio
    async def test_returns_201_on_success(self, client):
        from src.auth.middleware import get_current_agent
        community = _community()

        with patch(
            "src.routers.communities.community_service.create_community",
            new=AsyncMock(return_value=community),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(
                    "/communities",
                    json={"name": "Test Community", "slug": "test-community"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Community"
        assert data["slug"] == "test-community"

    @pytest.mark.asyncio
    async def test_requires_authentication(self, client):
        resp = await client.post(
            "/communities",
            json={"name": "Test Community", "slug": "test-community"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_409_on_duplicate(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.communities.community_service.create_community",
            new=AsyncMock(side_effect=Exception("duplicate key value violates unique constraint")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(
                    "/communities",
                    json={"name": "Test Community", "slug": "test-community"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_returns_400_on_validation_error(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.communities.community_service.create_community",
            new=AsyncMock(side_effect=ValueError("some validation error")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(
                    "/communities",
                    json={"name": "Test Community", "slug": "test-community"},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400


# ── TestListCommunities ────────────────────────────────────────────────────────

class TestListCommunities:

    @pytest.mark.asyncio
    async def test_returns_200_with_list(self, client):
        communities = [_community(), _community(name="Another", slug="another")]

        with patch(
            "src.routers.communities.community_service.list_communities",
            new=AsyncMock(return_value=communities),
        ):
            resp = await client.get("/communities")

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_public_access(self, client):
        """GET /communities does not require authentication."""
        with patch(
            "src.routers.communities.community_service.list_communities",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get("/communities")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_passes_limit_and_offset(self, client):
        mock_list = AsyncMock(return_value=[])

        with patch(
            "src.routers.communities.community_service.list_communities",
            new=mock_list,
        ):
            await client.get("/communities?limit=10&offset=5")

        mock_list.assert_awaited_once()
        kwargs = mock_list.call_args[1]
        assert kwargs["limit"] == 10
        assert kwargs["offset"] == 5


# ── TestGetCommunity ───────────────────────────────────────────────────────────

class TestGetCommunity:

    @pytest.mark.asyncio
    async def test_returns_200_by_id(self, client):
        community_id = uuid4()
        community = _community(community_id=community_id)

        with patch(
            "src.routers.communities.community_service.get_community",
            new=AsyncMock(return_value=community),
        ):
            resp = await client.get(f"/communities/{community_id}")

        assert resp.status_code == 200
        assert resp.json()["community_id"] == str(community_id)

    @pytest.mark.asyncio
    async def test_returns_404_if_not_found(self, client):
        with patch(
            "src.routers.communities.community_service.get_community",
            new=AsyncMock(side_effect=ValueError("not found")),
        ):
            resp = await client.get(f"/communities/{uuid4()}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_200_by_slug(self, client):
        community = _community(slug="my-community")

        with patch(
            "src.routers.communities.community_service.get_community_by_slug",
            new=AsyncMock(return_value=community),
        ):
            resp = await client.get("/communities/slug/my-community")

        assert resp.status_code == 200
        assert resp.json()["slug"] == "my-community"

    @pytest.mark.asyncio
    async def test_returns_404_on_bad_slug(self, client):
        with patch(
            "src.routers.communities.community_service.get_community_by_slug",
            new=AsyncMock(side_effect=ValueError("not found")),
        ):
            resp = await client.get("/communities/slug/nonexistent")

        assert resp.status_code == 404


# ── TestJoinCommunity ──────────────────────────────────────────────────────────

class TestJoinCommunity:

    @pytest.mark.asyncio
    async def test_returns_200_on_join(self, client):
        from src.auth.middleware import get_current_agent
        community_id = uuid4()
        member = _member(community_id=community_id)

        with patch(
            "src.routers.communities.community_service.join_community",
            new=AsyncMock(return_value=member),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(f"/communities/{community_id}/join")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_requires_authentication(self, client):
        resp = await client.post(f"/communities/{uuid4()}/join")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_400_already_member(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.communities.community_service.join_community",
            new=AsyncMock(side_effect=ValueError("Already a member")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(f"/communities/{uuid4()}/join")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_returns_400_private_community(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.communities.community_service.join_community",
            new=AsyncMock(side_effect=ValueError("Community is private")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(f"/communities/{uuid4()}/join")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400


# ── TestLeaveCommunity ─────────────────────────────────────────────────────────

class TestLeaveCommunity:

    @pytest.mark.asyncio
    async def test_returns_200_on_leave(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.communities.community_service.leave_community",
            new=AsyncMock(return_value=None),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(f"/communities/{uuid4()}/leave")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_requires_authentication(self, client):
        resp = await client.post(f"/communities/{uuid4()}/leave")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_400_sole_admin(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.communities.community_service.leave_community",
            new=AsyncMock(side_effect=ValueError("Cannot leave: you are the sole admin")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(f"/communities/{uuid4()}/leave")
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 400


# ── TestGetMembers ─────────────────────────────────────────────────────────────

class TestGetMembers:

    @pytest.mark.asyncio
    async def test_returns_200_with_member_list(self, client):
        community_id = uuid4()
        members = [_member(community_id=community_id), _member(community_id=community_id)]

        with patch(
            "src.routers.communities.community_service.get_community_members",
            new=AsyncMock(return_value=members),
        ):
            resp = await client.get(f"/communities/{community_id}/members")

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_public_access(self, client):
        with patch(
            "src.routers.communities.community_service.get_community_members",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/communities/{uuid4()}/members")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_returns_list_shape(self, client):
        community_id = uuid4()
        member = _member(community_id=community_id, agent_did=MEMBER_DID)

        with patch(
            "src.routers.communities.community_service.get_community_members",
            new=AsyncMock(return_value=[member]),
        ):
            resp = await client.get(f"/communities/{community_id}/members")

        data = resp.json()
        assert data[0]["agent_did"] == MEMBER_DID
        assert data[0]["role"] == "MEMBER"


# ── TestAddPost ────────────────────────────────────────────────────────────────

class TestAddPost:

    @pytest.mark.asyncio
    async def test_returns_201_on_success(self, client):
        from src.auth.middleware import get_current_agent
        community_id = uuid4()
        post_id      = uuid4()
        cp = _community_post(community_id=community_id, post_id=post_id)

        with patch(
            "src.routers.communities.community_service.add_post_to_community",
            new=AsyncMock(return_value=cp),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(
                    f"/communities/{community_id}/posts",
                    json={"post_id": str(post_id)},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_requires_authentication(self, client):
        resp = await client.post(
            f"/communities/{uuid4()}/posts",
            json={"post_id": str(uuid4())},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_403_if_not_member(self, client):
        from src.auth.middleware import get_current_agent

        with patch(
            "src.routers.communities.community_service.add_post_to_community",
            new=AsyncMock(side_effect=ValueError("Not a member of this community")),
        ):
            app.dependency_overrides[get_current_agent] = lambda: _make_caller()
            try:
                resp = await client.post(
                    f"/communities/{uuid4()}/posts",
                    json={"post_id": str(uuid4())},
                )
            finally:
                app.dependency_overrides.pop(get_current_agent, None)

        assert resp.status_code == 403


# ── TestCommunityFeed ──────────────────────────────────────────────────────────

class TestCommunityFeed:

    @pytest.mark.asyncio
    async def test_returns_200_with_posts(self, client):
        community_id = uuid4()
        posts = [_post_response(), _post_response()]

        with patch(
            "src.routers.communities.community_service.get_community_feed",
            new=AsyncMock(return_value=posts),
        ):
            resp = await client.get(f"/communities/{community_id}/feed")

        assert resp.status_code == 200
        assert len(resp.json()) == 2

    @pytest.mark.asyncio
    async def test_public_access(self, client):
        with patch(
            "src.routers.communities.community_service.get_community_feed",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/communities/{uuid4()}/feed")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_empty_feed_returns_empty_list(self, client):
        with patch(
            "src.routers.communities.community_service.get_community_feed",
            new=AsyncMock(return_value=[]),
        ):
            resp = await client.get(f"/communities/{uuid4()}/feed")
        assert resp.json() == []
