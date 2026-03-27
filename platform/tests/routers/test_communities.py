"""
Tests: src/routers/communities.py
Phase 22 — Agent Communities

Covers:
  POST   /communities                     — create (auth, 409 on dup)
  GET    /communities                     — list (public, pagination)
  GET    /communities/slug/{slug}         — by slug
  GET    /communities/{community_id}      — by ID (404 on missing)
  POST   /communities/{community_id}/join  — join (auth, 400 on dup/private)
  POST   /communities/{community_id}/leave — leave (auth, 400 on sole admin)
  GET    /communities/{community_id}/members — list members (public)
  POST   /communities/{community_id}/posts   — add post (auth, 403 non-member)
  GET    /communities/{community_id}/feed    — community feed (public)
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


def _community_response(community_id=None, slug="ai-hub", name="AI Hub"):
    from src.models.community import CommunityResponse, CommunityVisibility, CommunityStatus
    return CommunityResponse(
        community_id=community_id or uuid.uuid4(),
        name=name,
        slug=slug,
        description="A research community",
        creator_did="did:agentx:atlas-001",
        visibility=CommunityVisibility.PUBLIC,
        status=CommunityStatus.ACTIVE,
        member_count=1,
        metadata={},
        created_at=_now(),
    )


def _member_response(community_id=None, agent_did="did:agentx:nova-001"):
    from src.models.community import CommunityMember, MemberRole
    return CommunityMember(
        community_id=community_id or uuid.uuid4(),
        agent_did=agent_did,
        role=MemberRole.MEMBER,
        joined_at=_now(),
    )


def _community_post_response(community_id=None, post_id=None):
    from src.models.community import CommunityPost
    return CommunityPost(
        community_post_id=uuid.uuid4(),
        community_id=community_id or uuid.uuid4(),
        post_id=post_id or uuid.uuid4(),
        created_at=_now(),
    )


def _post_response():
    from src.models.post import PostResponse
    return PostResponse(
        post_id=uuid.uuid4(),
        author_did="did:agentx:atlas-001",
        post_type="UPDATE",
        title="Test Post",
        content="Hello community!",
        tags=[],
        visibility="PUBLIC",
        status="ACTIVE",
        collective_id=None,
        parent_post_id=None,
        metadata={},
        created_at=_now(),
        updated_at=_now(),
        expires_at=None,
        like_count=0,
        reply_count=0,
        author_name="ATLAS",
        author_trust=0.95,
    )


@pytest.fixture
async def client():
    from httpx import ASGITransport
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


# ── TestCreateCommunity ────────────────────────────────────────────────────────

class TestCreateCommunity:

    @pytest.mark.asyncio
    async def test_create_returns_201(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller()
        community = _community_response()

        with patch("src.routers.communities.community_service.create_community",
                   new=AsyncMock(return_value=community)):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post("/communities", json={
                "name": "AI Hub",
                "slug": "ai-hub",
                "description": "A research community",
            })

        app.dependency_overrides = {}
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "AI Hub"
        assert data["slug"] == "ai-hub"

    @pytest.mark.asyncio
    async def test_create_requires_auth(self, client):
        response = await client.post("/communities", json={
            "name": "AI Hub",
            "slug": "ai-hub",
        })
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_returns_409_on_duplicate(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller()

        with patch("src.routers.communities.community_service.create_community",
                   new=AsyncMock(side_effect=ValueError("already taken"))):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post("/communities", json={
                "name": "Duplicate",
                "slug": "duplicate",
            })

        app.dependency_overrides = {}
        assert response.status_code == 409
        assert "already taken" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_validates_slug_format(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller()

        app.dependency_overrides[get_current_agent] = lambda: caller
        response = await client.post("/communities", json={
            "name": "Bad Slug",
            "slug": "Bad Slug!!!",  # invalid: uppercase + spaces + punctuation
        })
        app.dependency_overrides = {}
        assert response.status_code == 422


# ── TestListCommunities ────────────────────────────────────────────────────────

class TestListCommunities:

    @pytest.mark.asyncio
    async def test_list_returns_200(self, client):
        communities = [_community_response(), _community_response()]

        with patch("src.routers.communities.community_service.list_communities",
                   new=AsyncMock(return_value=communities)):
            response = await client.get("/communities")

        assert response.status_code == 200
        assert len(response.json()) == 2

    @pytest.mark.asyncio
    async def test_list_is_public(self, client):
        with patch("src.routers.communities.community_service.list_communities",
                   new=AsyncMock(return_value=[])):
            response = await client.get("/communities")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_respects_limit_offset(self, client):
        mock_list = AsyncMock(return_value=[])

        with patch("src.routers.communities.community_service.list_communities", new=mock_list):
            await client.get("/communities?limit=5&offset=10")

        call_kwargs = mock_list.call_args.kwargs
        assert call_kwargs["limit"] == 5
        assert call_kwargs["offset"] == 10

    @pytest.mark.asyncio
    async def test_list_returns_empty_list(self, client):
        with patch("src.routers.communities.community_service.list_communities",
                   new=AsyncMock(return_value=[])):
            response = await client.get("/communities")

        assert response.status_code == 200
        assert response.json() == []


# ── TestGetCommunity ───────────────────────────────────────────────────────────

class TestGetCommunity:

    @pytest.mark.asyncio
    async def test_get_by_id_returns_200(self, client):
        comm_id   = uuid.uuid4()
        community = _community_response(community_id=comm_id)

        with patch("src.routers.communities.community_service.get_community",
                   new=AsyncMock(return_value=community)):
            response = await client.get(f"/communities/{comm_id}")

        assert response.status_code == 200
        assert response.json()["community_id"] == str(comm_id)

    @pytest.mark.asyncio
    async def test_get_by_id_returns_404_when_missing(self, client):
        with patch("src.routers.communities.community_service.get_community",
                   new=AsyncMock(side_effect=ValueError("not found"))):
            response = await client.get(f"/communities/{uuid.uuid4()}")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_by_slug_returns_200(self, client):
        community = _community_response(slug="ai-hub")

        with patch("src.routers.communities.community_service.get_community_by_slug",
                   new=AsyncMock(return_value=community)):
            response = await client.get("/communities/slug/ai-hub")

        assert response.status_code == 200
        assert response.json()["slug"] == "ai-hub"

    @pytest.mark.asyncio
    async def test_get_by_slug_returns_404_when_missing(self, client):
        with patch("src.routers.communities.community_service.get_community_by_slug",
                   new=AsyncMock(side_effect=ValueError("not found"))):
            response = await client.get("/communities/slug/ghost-slug")

        assert response.status_code == 404


# ── TestJoinCommunity ──────────────────────────────────────────────────────────

class TestJoinCommunity:

    @pytest.mark.asyncio
    async def test_join_returns_200(self, client):
        from src.auth.middleware import get_current_agent
        caller = _make_caller()
        comm_id = uuid.uuid4()
        member  = _member_response(community_id=comm_id, agent_did=caller.did)

        with patch("src.routers.communities.community_service.join_community",
                   new=AsyncMock(return_value=member)):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(f"/communities/{comm_id}/join", json={})

        app.dependency_overrides = {}
        assert response.status_code == 200
        assert response.json()["agent_did"] == caller.did

    @pytest.mark.asyncio
    async def test_join_requires_auth(self, client):
        response = await client.post(f"/communities/{uuid.uuid4()}/join", json={})
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_join_returns_400_if_already_member(self, client):
        from src.auth.middleware import get_current_agent
        caller  = _make_caller()
        comm_id = uuid.uuid4()

        with patch("src.routers.communities.community_service.join_community",
                   new=AsyncMock(side_effect=ValueError("Already a member"))):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(f"/communities/{comm_id}/join", json={})

        app.dependency_overrides = {}
        assert response.status_code == 400
        assert "Already a member" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_join_returns_400_if_private(self, client):
        from src.auth.middleware import get_current_agent
        caller  = _make_caller()
        comm_id = uuid.uuid4()

        with patch("src.routers.communities.community_service.join_community",
                   new=AsyncMock(side_effect=ValueError("Community is private"))):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(f"/communities/{comm_id}/join", json={})

        app.dependency_overrides = {}
        assert response.status_code == 400
        assert "private" in response.json()["detail"]


# ── TestLeaveCommunity ─────────────────────────────────────────────────────────

class TestLeaveCommunity:

    @pytest.mark.asyncio
    async def test_leave_returns_204(self, client):
        from src.auth.middleware import get_current_agent
        caller  = _make_caller()
        comm_id = uuid.uuid4()

        with patch("src.routers.communities.community_service.leave_community",
                   new=AsyncMock(return_value=None)):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(f"/communities/{comm_id}/leave")

        app.dependency_overrides = {}
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_leave_requires_auth(self, client):
        response = await client.post(f"/communities/{uuid.uuid4()}/leave")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_leave_returns_400_if_sole_admin(self, client):
        from src.auth.middleware import get_current_agent
        caller  = _make_caller()
        comm_id = uuid.uuid4()

        with patch("src.routers.communities.community_service.leave_community",
                   new=AsyncMock(side_effect=ValueError("sole admin"))):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(f"/communities/{comm_id}/leave")

        app.dependency_overrides = {}
        assert response.status_code == 400
        assert "sole admin" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_leave_returns_400_if_not_member(self, client):
        from src.auth.middleware import get_current_agent
        caller  = _make_caller()
        comm_id = uuid.uuid4()

        with patch("src.routers.communities.community_service.leave_community",
                   new=AsyncMock(side_effect=ValueError("Not a member"))):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(f"/communities/{comm_id}/leave")

        app.dependency_overrides = {}
        assert response.status_code == 400


# ── TestGetCommunityMembers ────────────────────────────────────────────────────

class TestGetCommunityMembers:

    @pytest.mark.asyncio
    async def test_members_returns_200(self, client):
        comm_id = uuid.uuid4()
        members = [_member_response(community_id=comm_id)]

        with patch("src.routers.communities.community_service.get_community_members",
                   new=AsyncMock(return_value=members)):
            response = await client.get(f"/communities/{comm_id}/members")

        assert response.status_code == 200
        assert len(response.json()) == 1

    @pytest.mark.asyncio
    async def test_members_is_public(self, client):
        with patch("src.routers.communities.community_service.get_community_members",
                   new=AsyncMock(return_value=[])):
            response = await client.get(f"/communities/{uuid.uuid4()}/members")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_members_respects_pagination(self, client):
        mock_fn = AsyncMock(return_value=[])
        comm_id = uuid.uuid4()

        with patch("src.routers.communities.community_service.get_community_members", new=mock_fn):
            await client.get(f"/communities/{comm_id}/members?limit=5&offset=10")

        call_kwargs = mock_fn.call_args.kwargs
        assert call_kwargs["limit"] == 5
        assert call_kwargs["offset"] == 10


# ── TestAddPostToCommunity ─────────────────────────────────────────────────────

class TestAddPostToCommunity:

    @pytest.mark.asyncio
    async def test_add_post_returns_201(self, client):
        from src.auth.middleware import get_current_agent
        caller  = _make_caller()
        comm_id = uuid.uuid4()
        post_id = uuid.uuid4()
        cp      = _community_post_response(community_id=comm_id, post_id=post_id)

        with patch("src.routers.communities.community_service.add_post_to_community",
                   new=AsyncMock(return_value=cp)):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/communities/{comm_id}/posts",
                json={"post_id": str(post_id)},
            )

        app.dependency_overrides = {}
        assert response.status_code == 201
        assert response.json()["post_id"] == str(post_id)

    @pytest.mark.asyncio
    async def test_add_post_requires_auth(self, client):
        response = await client.post(
            f"/communities/{uuid.uuid4()}/posts",
            json={"post_id": str(uuid.uuid4())},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_add_post_returns_403_if_not_member(self, client):
        from src.auth.middleware import get_current_agent
        caller  = _make_caller()
        comm_id = uuid.uuid4()

        with patch("src.routers.communities.community_service.add_post_to_community",
                   new=AsyncMock(side_effect=ValueError("must be a community member"))):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/communities/{comm_id}/posts",
                json={"post_id": str(uuid.uuid4())},
            )

        app.dependency_overrides = {}
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_add_post_returns_403_if_not_author(self, client):
        from src.auth.middleware import get_current_agent
        caller  = _make_caller()
        comm_id = uuid.uuid4()

        with patch("src.routers.communities.community_service.add_post_to_community",
                   new=AsyncMock(side_effect=ValueError("only share your own posts"))):
            app.dependency_overrides[get_current_agent] = lambda: caller
            response = await client.post(
                f"/communities/{comm_id}/posts",
                json={"post_id": str(uuid.uuid4())},
            )

        app.dependency_overrides = {}
        assert response.status_code == 403


# ── TestGetCommunityFeed ───────────────────────────────────────────────────────

class TestGetCommunityFeed:

    @pytest.mark.asyncio
    async def test_feed_returns_200(self, client):
        comm_id = uuid.uuid4()
        posts   = [_post_response(), _post_response()]

        with patch("src.routers.communities.community_service.get_community_feed",
                   new=AsyncMock(return_value=posts)):
            response = await client.get(f"/communities/{comm_id}/feed")

        assert response.status_code == 200
        assert len(response.json()) == 2

    @pytest.mark.asyncio
    async def test_feed_is_public(self, client):
        with patch("src.routers.communities.community_service.get_community_feed",
                   new=AsyncMock(return_value=[])):
            response = await client.get(f"/communities/{uuid.uuid4()}/feed")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_feed_respects_limit(self, client):
        mock_fn = AsyncMock(return_value=[])
        comm_id = uuid.uuid4()

        with patch("src.routers.communities.community_service.get_community_feed", new=mock_fn):
            await client.get(f"/communities/{comm_id}/feed?limit=10")

        call_kwargs = mock_fn.call_args.kwargs
        assert call_kwargs["limit"] == 10

    @pytest.mark.asyncio
    async def test_feed_returns_empty_list(self, client):
        with patch("src.routers.communities.community_service.get_community_feed",
                   new=AsyncMock(return_value=[])):
            response = await client.get(f"/communities/{uuid.uuid4()}/feed")

        assert response.status_code == 200
        assert response.json() == []
