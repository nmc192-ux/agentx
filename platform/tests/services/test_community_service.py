"""
Tests: src/services/community_service.py
Phase 22 — Agent Communities

Covers:
  create_community()        — inserts community + ADMIN member, records activity
  join_community()          — inserts member, increments count, notifies, raises on dup/private
  leave_community()         — removes member, decrements count, sole-admin guard
  list_communities()        — ordered list with pagination
  get_community()           — by ID; raises on missing
  get_community_by_slug()   — by slug; raises on missing
  get_community_members()   — paginated member list
  add_post_to_community()   — link post, batch notify, raise if non-member
  get_community_feed()      — posts from community ordered by date
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services import community_service


# ── Helpers ────────────────────────────────────────────────────────────────────

def _tx_context(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__  = AsyncMock(return_value=None)
    return ctx


def _db_context(conn):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__  = AsyncMock(return_value=None)
    return ctx


def _now():
    return datetime.now(UTC)


def _community_row(
    community_id=None,
    name="AI Research Hub",
    slug="ai-research-hub",
    creator_did="did:agentx:atlas-001",
    visibility="PUBLIC",
    status="ACTIVE",
    member_count=1,
):
    return {
        "community_id": community_id or uuid4(),
        "name":         name,
        "slug":         slug,
        "description":  "A community for AI research",
        "creator_did":  creator_did,
        "visibility":   visibility,
        "status":       status,
        "member_count": member_count,
        "metadata":     "{}",
        "created_at":   _now(),
    }


def _member_row(community_id=None, agent_did="did:agentx:atlas-001", role="MEMBER"):
    return {
        "community_id": community_id or uuid4(),
        "agent_did":    agent_did,
        "role":         role,
        "joined_at":    _now(),
    }


def _post_row(post_id=None, author_did="did:agentx:atlas-001"):
    return {
        "post_id":        post_id or uuid4(),
        "author_did":     author_did,
        "post_type":      "UPDATE",
        "title":          "Test Post",
        "content":        "Hello community!",
        "tags":           [],
        "visibility":     "PUBLIC",
        "status":         "ACTIVE",
        "collective_id":  None,
        "parent_post_id": None,
        "metadata":       "{}",
        "created_at":     _now(),
        "updated_at":     _now(),
        "expires_at":     None,
        "like_count":     0,
        "reply_count":    0,
        "author_name":    "ATLAS",
        "author_trust":   0.95,
    }


def _community_post_row(community_id=None, post_id=None):
    return {
        "community_post_id": uuid4(),
        "community_id":      community_id or uuid4(),
        "post_id":           post_id or uuid4(),
        "created_at":        _now(),
    }


# ── TestCreateCommunity ────────────────────────────────────────────────────────

class TestCreateCommunity:

    @pytest.mark.asyncio
    async def test_create_returns_community_response(self):
        from src.models.community import CommunityCreate, CommunityVisibility
        creator_did = "did:agentx:atlas-001"
        data = CommunityCreate(
            name="AI Research Hub",
            slug="ai-research-hub",
            description="Research",
        )
        comm_id = uuid4()
        row = _community_row(community_id=comm_id, member_count=1)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            None,   # no duplicate
            row,    # INSERT communities RETURNING
            row,    # SELECT after UPDATE
        ])
        conn.execute = AsyncMock(return_value=None)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            result = await community_service.create_community(creator_did, data)

        assert result.name == "AI Research Hub"
        assert result.slug == "ai-research-hub"
        assert result.member_count == 1
        assert result.creator_did == creator_did

    @pytest.mark.asyncio
    async def test_creator_inserted_as_admin(self):
        from src.models.community import CommunityCreate
        creator_did = "did:agentx:atlas-001"
        data = CommunityCreate(name="Test Comm", slug="test-comm")
        row = _community_row()

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, row, row])
        conn.execute = AsyncMock(return_value=None)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            await community_service.create_community(creator_did, data)

        # Second execute call should be INSERT INTO community_members … 'ADMIN'
        insert_call = conn.execute.call_args_list[0]
        assert "ADMIN" in insert_call.args[0]

    @pytest.mark.asyncio
    async def test_member_count_set_to_one(self):
        from src.models.community import CommunityCreate
        data = CommunityCreate(name="My Comm", slug="my-comm")
        row = _community_row(member_count=1)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, row, row])
        conn.execute = AsyncMock(return_value=None)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            result = await community_service.create_community("did:agentx:test", data)

        assert result.member_count == 1

    @pytest.mark.asyncio
    async def test_raises_on_duplicate_name_or_slug(self):
        from src.models.community import CommunityCreate
        data = CommunityCreate(name="Existing Comm", slug="existing-comm")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"community_id": uuid4()})  # conflict

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="already taken"),
        ):
            await community_service.create_community("did:agentx:test", data)

    @pytest.mark.asyncio
    async def test_activity_recorded_when_svc_available(self):
        from src.models.community import CommunityCreate
        data = CommunityCreate(name="Active Comm", slug="active-comm")
        row = _community_row()

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[None, row, row])
        conn.execute = AsyncMock(return_value=None)

        mock_svc = MagicMock()
        mock_svc.record_activity = AsyncMock(return_value=None)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", mock_svc),
        ):
            await community_service.create_community("did:agentx:test", data)

        mock_svc.record_activity.assert_awaited_once()
        call_kwargs = mock_svc.record_activity.call_args.kwargs
        assert call_kwargs["stream_type"] == "community_created"


# ── TestJoinCommunity ──────────────────────────────────────────────────────────

class TestJoinCommunity:

    @pytest.mark.asyncio
    async def test_join_returns_member(self):
        comm_id = uuid4()
        agent_did = "did:agentx:nova-001"
        comm_row = _community_row(community_id=comm_id, creator_did="did:agentx:atlas-001")
        mem_row  = _member_row(community_id=comm_id, agent_did=agent_did)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[comm_row, mem_row])
        conn.execute  = AsyncMock(return_value="INSERT 0 1")

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            result = await community_service.join_community(comm_id, agent_did)

        assert result.agent_did == agent_did
        assert result.role == "MEMBER"

    @pytest.mark.asyncio
    async def test_join_increments_member_count(self):
        comm_id = uuid4()
        agent_did = "did:agentx:nova-001"
        comm_row = _community_row(community_id=comm_id)
        mem_row  = _member_row(community_id=comm_id, agent_did=agent_did)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[comm_row, mem_row])
        conn.execute  = AsyncMock(return_value="INSERT 0 1")

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            await community_service.join_community(comm_id, agent_did)

        # UPDATE member_count call
        update_calls = [
            c for c in conn.execute.call_args_list
            if "member_count" in c.args[0]
        ]
        assert len(update_calls) >= 1

    @pytest.mark.asyncio
    async def test_join_raises_if_already_member(self):
        comm_id  = uuid4()
        comm_row = _community_row(community_id=comm_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=comm_row)
        conn.execute  = AsyncMock(return_value="INSERT 0 0")  # conflict, 0 rows

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Already a member"),
        ):
            await community_service.join_community(comm_id, "did:agentx:nova-001")

    @pytest.mark.asyncio
    async def test_join_raises_if_community_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await community_service.join_community(uuid4(), "did:agentx:nova-001")

    @pytest.mark.asyncio
    async def test_join_raises_if_community_private(self):
        comm_id  = uuid4()
        comm_row = _community_row(community_id=comm_id, visibility="PRIVATE")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=comm_row)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="private"),
        ):
            await community_service.join_community(comm_id, "did:agentx:nova-001")

    @pytest.mark.asyncio
    async def test_join_notifies_creator(self):
        comm_id   = uuid4()
        agent_did = "did:agentx:nova-001"
        creator   = "did:agentx:atlas-001"
        comm_row  = _community_row(community_id=comm_id, creator_did=creator)
        mem_row   = _member_row(community_id=comm_id, agent_did=agent_did)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[comm_row, mem_row])
        conn.execute  = AsyncMock(return_value="INSERT 0 1")

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            await community_service.join_community(comm_id, agent_did)

        # Notification INSERT should be called
        notif_calls = [
            c for c in conn.execute.call_args_list
            if "COMMUNITY_JOIN" in c.args[0]
        ]
        assert len(notif_calls) == 1

    @pytest.mark.asyncio
    async def test_join_no_self_notification(self):
        """Creator joining their own community should not notify themselves."""
        comm_id    = uuid4()
        creator    = "did:agentx:atlas-001"
        comm_row   = _community_row(community_id=comm_id, creator_did=creator)
        mem_row    = _member_row(community_id=comm_id, agent_did=creator)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[comm_row, mem_row])
        conn.execute  = AsyncMock(return_value="INSERT 0 1")

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            await community_service.join_community(comm_id, creator)

        notif_calls = [
            c for c in conn.execute.call_args_list
            if "COMMUNITY_JOIN" in c.args[0]
        ]
        assert len(notif_calls) == 0

    @pytest.mark.asyncio
    async def test_join_activity_recorded(self):
        comm_id  = uuid4()
        agent_did = "did:agentx:nova-001"
        comm_row = _community_row(community_id=comm_id)
        mem_row  = _member_row(community_id=comm_id, agent_did=agent_did)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[comm_row, mem_row])
        conn.execute  = AsyncMock(return_value="INSERT 0 1")

        mock_svc = MagicMock()
        mock_svc.record_activity = AsyncMock(return_value=None)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", mock_svc),
        ):
            await community_service.join_community(comm_id, agent_did)

        mock_svc.record_activity.assert_awaited_once()
        assert mock_svc.record_activity.call_args.kwargs["stream_type"] == "community_joined"


# ── TestLeaveCommunity ─────────────────────────────────────────────────────────

class TestLeaveCommunity:

    @pytest.mark.asyncio
    async def test_leave_removes_member(self):
        comm_id   = uuid4()
        agent_did = "did:agentx:nova-001"
        mem_row   = _member_row(community_id=comm_id, agent_did=agent_did, role="MEMBER")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=mem_row)
        conn.execute  = AsyncMock(return_value=None)

        with patch("src.services.community_service.transaction", return_value=_tx_context(conn)):
            await community_service.leave_community(comm_id, agent_did)

        delete_calls = [c for c in conn.execute.call_args_list if "DELETE" in c.args[0]]
        assert len(delete_calls) == 1

    @pytest.mark.asyncio
    async def test_leave_decrements_member_count(self):
        comm_id   = uuid4()
        agent_did = "did:agentx:nova-001"
        mem_row   = _member_row(community_id=comm_id, agent_did=agent_did, role="MEMBER")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=mem_row)
        conn.execute  = AsyncMock(return_value=None)

        with patch("src.services.community_service.transaction", return_value=_tx_context(conn)):
            await community_service.leave_community(comm_id, agent_did)

        update_calls = [
            c for c in conn.execute.call_args_list
            if "member_count" in c.args[0]
        ]
        assert len(update_calls) == 1

    @pytest.mark.asyncio
    async def test_leave_raises_if_not_member(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # not found

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Not a member"),
        ):
            await community_service.leave_community(uuid4(), "did:agentx:ghost")

    @pytest.mark.asyncio
    async def test_leave_raises_if_sole_admin(self):
        comm_id   = uuid4()
        agent_did = "did:agentx:atlas-001"
        mem_row   = _member_row(community_id=comm_id, agent_did=agent_did, role="ADMIN")

        conn = AsyncMock()
        conn.fetchrow  = AsyncMock(return_value=mem_row)
        conn.fetchval  = AsyncMock(return_value=1)   # only 1 admin

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="sole admin"),
        ):
            await community_service.leave_community(comm_id, agent_did)

    @pytest.mark.asyncio
    async def test_leave_allowed_if_multiple_admins(self):
        comm_id   = uuid4()
        agent_did = "did:agentx:atlas-001"
        mem_row   = _member_row(community_id=comm_id, agent_did=agent_did, role="ADMIN")

        conn = AsyncMock()
        conn.fetchrow  = AsyncMock(return_value=mem_row)
        conn.fetchval  = AsyncMock(return_value=2)   # 2 admins
        conn.execute   = AsyncMock(return_value=None)

        with patch("src.services.community_service.transaction", return_value=_tx_context(conn)):
            await community_service.leave_community(comm_id, agent_did)

        delete_calls = [c for c in conn.execute.call_args_list if "DELETE" in c.args[0]]
        assert len(delete_calls) == 1


# ── TestListCommunities ────────────────────────────────────────────────────────

class TestListCommunities:

    @pytest.mark.asyncio
    async def test_list_returns_communities(self):
        rows = [_community_row(name="A"), _community_row(name="B")]

        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await community_service.list_communities(limit=10, offset=0)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_respects_limit_offset(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            await community_service.list_communities(limit=5, offset=10)

        call_args = conn.fetch.call_args
        assert call_args.args[1] == "ACTIVE"
        assert call_args.args[2] == 5
        assert call_args.args[3] == 10

    @pytest.mark.asyncio
    async def test_list_filters_by_status(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            await community_service.list_communities(status="ARCHIVED")

        call_args = conn.fetch.call_args
        assert "ARCHIVED" in call_args.args


# ── TestGetCommunity ───────────────────────────────────────────────────────────

class TestGetCommunity:

    @pytest.mark.asyncio
    async def test_get_by_id_returns_community(self):
        comm_id = uuid4()
        row = _community_row(community_id=comm_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await community_service.get_community(comm_id)

        assert result.community_id == comm_id

    @pytest.mark.asyncio
    async def test_get_by_id_raises_if_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.community_service.get_db", return_value=_db_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await community_service.get_community(uuid4())

    @pytest.mark.asyncio
    async def test_get_by_slug_returns_community(self):
        row = _community_row(slug="ai-research-hub")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await community_service.get_community_by_slug("ai-research-hub")

        assert result.slug == "ai-research-hub"

    @pytest.mark.asyncio
    async def test_get_by_slug_raises_if_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.community_service.get_db", return_value=_db_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await community_service.get_community_by_slug("ghost-slug")


# ── TestGetCommunityMembers ────────────────────────────────────────────────────

class TestGetCommunityMembers:

    @pytest.mark.asyncio
    async def test_get_members_returns_list(self):
        comm_id = uuid4()
        rows = [_member_row(community_id=comm_id, role="ADMIN"),
                _member_row(community_id=comm_id, role="MEMBER")]

        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await community_service.get_community_members(comm_id)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_members_respects_pagination(self):
        comm_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            await community_service.get_community_members(comm_id, limit=5, offset=10)

        call_args = conn.fetch.call_args
        assert call_args.args[2] == 5
        assert call_args.args[3] == 10

    @pytest.mark.asyncio
    async def test_get_members_empty_community(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await community_service.get_community_members(uuid4())

        assert result == []


# ── TestAddPostToCommunity ─────────────────────────────────────────────────────

class TestAddPostToCommunity:

    @pytest.mark.asyncio
    async def test_add_post_returns_community_post(self):
        comm_id   = uuid4()
        post_id   = uuid4()
        agent_did = "did:agentx:atlas-001"
        mem_row   = _member_row(community_id=comm_id, agent_did=agent_did, role="MEMBER")
        post_row  = _post_row(post_id=post_id, author_did=agent_did)
        cp_row    = _community_post_row(community_id=comm_id, post_id=post_id)
        comm_row  = {"name": "AI Hub"}
        members   = []

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[mem_row, post_row, cp_row, comm_row])
        conn.fetch    = AsyncMock(return_value=members)
        conn.execute  = AsyncMock(return_value=None)
        conn.executemany = AsyncMock(return_value=None)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            result = await community_service.add_post_to_community(comm_id, post_id, agent_did)

        assert result.post_id == post_id
        assert result.community_id == comm_id

    @pytest.mark.asyncio
    async def test_add_post_raises_if_not_member(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # not a member

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="must be a community member"),
        ):
            await community_service.add_post_to_community(uuid4(), uuid4(), "did:agentx:ghost")

    @pytest.mark.asyncio
    async def test_add_post_raises_if_post_not_found(self):
        comm_id   = uuid4()
        agent_did = "did:agentx:atlas-001"
        mem_row   = _member_row(community_id=comm_id, agent_did=agent_did)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[mem_row, None])  # post not found

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Post not found"),
        ):
            await community_service.add_post_to_community(comm_id, uuid4(), agent_did)

    @pytest.mark.asyncio
    async def test_add_post_raises_if_not_author_and_not_admin(self):
        comm_id    = uuid4()
        post_id    = uuid4()
        agent_did  = "did:agentx:nova-001"
        author_did = "did:agentx:atlas-001"
        mem_row    = _member_row(community_id=comm_id, agent_did=agent_did, role="MEMBER")
        post_row   = _post_row(post_id=post_id, author_did=author_did)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[mem_row, post_row])

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="only share your own posts"),
        ):
            await community_service.add_post_to_community(comm_id, post_id, agent_did)

    @pytest.mark.asyncio
    async def test_add_post_admin_can_share_any_post(self):
        comm_id    = uuid4()
        post_id    = uuid4()
        agent_did  = "did:agentx:atlas-001"
        author_did = "did:agentx:nova-001"
        mem_row    = _member_row(community_id=comm_id, agent_did=agent_did, role="ADMIN")
        post_row   = _post_row(post_id=post_id, author_did=author_did)
        cp_row     = _community_post_row(community_id=comm_id, post_id=post_id)
        comm_row   = {"name": "AI Hub"}
        members    = []

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[mem_row, post_row, cp_row, comm_row])
        conn.fetch    = AsyncMock(return_value=members)
        conn.executemany = AsyncMock(return_value=None)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            result = await community_service.add_post_to_community(comm_id, post_id, agent_did)

        assert result.post_id == post_id

    @pytest.mark.asyncio
    async def test_add_post_bulk_notifies_members(self):
        comm_id    = uuid4()
        post_id    = uuid4()
        agent_did  = "did:agentx:atlas-001"
        mem_row    = _member_row(community_id=comm_id, agent_did=agent_did, role="MEMBER")
        post_row   = _post_row(post_id=post_id, author_did=agent_did)
        cp_row     = _community_post_row(community_id=comm_id, post_id=post_id)
        comm_row   = {"name": "AI Hub"}
        other_members = [
            {"agent_did": "did:agentx:nova-001"},
            {"agent_did": "did:agentx:beta-001"},
        ]

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[mem_row, post_row, cp_row, comm_row])
        conn.fetch    = AsyncMock(return_value=other_members)
        conn.executemany = AsyncMock(return_value=None)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            await community_service.add_post_to_community(comm_id, post_id, agent_did)

        conn.executemany.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_add_post_activity_recorded(self):
        comm_id    = uuid4()
        post_id    = uuid4()
        agent_did  = "did:agentx:atlas-001"
        mem_row    = _member_row(community_id=comm_id, agent_did=agent_did, role="MEMBER")
        post_row   = _post_row(post_id=post_id, author_did=agent_did)
        cp_row     = _community_post_row(community_id=comm_id, post_id=post_id)
        comm_row   = {"name": "AI Hub"}

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[mem_row, post_row, cp_row, comm_row])
        conn.fetch    = AsyncMock(return_value=[])
        conn.executemany = AsyncMock(return_value=None)

        mock_svc = MagicMock()
        mock_svc.record_activity = AsyncMock(return_value=None)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", mock_svc),
        ):
            await community_service.add_post_to_community(comm_id, post_id, agent_did)

        mock_svc.record_activity.assert_awaited_once()
        assert mock_svc.record_activity.call_args.kwargs["stream_type"] == "community_posted"


# ── TestGetCommunityFeed ───────────────────────────────────────────────────────

class TestGetCommunityFeed:

    @pytest.mark.asyncio
    async def test_feed_returns_posts(self):
        comm_id = uuid4()
        rows = [_post_row(), _post_row()]

        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await community_service.get_community_feed(comm_id, limit=10)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_feed_respects_limit(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            await community_service.get_community_feed(uuid4(), limit=5)

        call_args = conn.fetch.call_args
        assert 5 in call_args.args

    @pytest.mark.asyncio
    async def test_feed_empty_when_no_posts(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await community_service.get_community_feed(uuid4())

        assert result == []
