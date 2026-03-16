"""
Tests: src/services/community_service.py
Phase 22 — Agent Communities

Covers:
  create_community()
  join_community()
  leave_community()
  list_communities()
  get_community()
  get_community_by_slug()
  get_community_members()
  add_post_to_community()
  get_community_feed()

All DB calls fully mocked via patched get_db / transaction context managers.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services.community_service import (
    add_post_to_community,
    create_community,
    get_community,
    get_community_by_slug,
    get_community_feed,
    get_community_members,
    join_community,
    leave_community,
    list_communities,
)
from src.models.community import CommunityCreate


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


def _community_row(
    community_id=None,
    name="Test Community",
    slug="test-community",
    creator_did="did:agentx:creator-001",
    visibility="PUBLIC",
    status="ACTIVE",
    member_count=1,
):
    return {
        "community_id": community_id or uuid4(),
        "name":         name,
        "slug":         slug,
        "description":  "A test community",
        "creator_did":  creator_did,
        "visibility":   visibility,
        "status":       status,
        "member_count": member_count,
        "metadata":     "{}",
        "created_at":   datetime.now(UTC),
    }


def _member_row(
    community_id=None,
    agent_did="did:agentx:member-001",
    role="MEMBER",
):
    return {
        "community_id": community_id or uuid4(),
        "agent_did":    agent_did,
        "role":         role,
        "joined_at":    datetime.now(UTC),
    }


def _post_row(post_id=None, author_did="did:agentx:author-001"):
    return {
        "post_id":        post_id or uuid4(),
        "author_did":     author_did,
        "post_type":      "UPDATE",
        "title":          "Test Post",
        "content":        "Post content",
        "tags":           [],
        "visibility":     "PUBLIC",
        "status":         "ACTIVE",
        "collective_id":  None,
        "parent_post_id": None,
        "metadata":       "{}",
        "created_at":     datetime.now(UTC),
        "updated_at":     datetime.now(UTC),
        "expires_at":     None,
        "like_count":     0,
        "reply_count":    0,
        "author_name":    "Author",
        "author_trust":   0.8,
    }


def _community_post_row(community_id=None, post_id=None):
    return {
        "community_post_id": uuid4(),
        "community_id":      community_id or uuid4(),
        "post_id":           post_id or uuid4(),
        "created_at":        datetime.now(UTC),
    }


# ── TestCreateCommunity ────────────────────────────────────────────────────────

class TestCreateCommunity:

    @pytest.mark.asyncio
    async def test_creates_community_and_returns_response(self):
        community_id = uuid4()
        row = _community_row(community_id=community_id)
        data = CommunityCreate(name="Test Community", slug="test-community")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute  = AsyncMock()

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            result = await create_community("did:agentx:creator-001", data)

        assert result.name == "Test Community"
        assert result.slug == "test-community"
        assert result.creator_did == "did:agentx:creator-001"

    @pytest.mark.asyncio
    async def test_creator_added_as_admin(self):
        row = _community_row()
        data = CommunityCreate(name="Test Community", slug="test-community")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute  = AsyncMock()

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            await create_community("did:agentx:creator-001", data)

        # execute called twice: INSERT member + UPDATE member_count
        calls = conn.execute.call_args_list
        insert_call = calls[0][0][0]
        assert "INSERT INTO community_members" in insert_call
        assert "ADMIN" in insert_call or "'ADMIN'" in str(calls[0])

    @pytest.mark.asyncio
    async def test_member_count_initialized_to_1(self):
        row = _community_row()
        data = CommunityCreate(name="Test Community", slug="test-community")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute  = AsyncMock()

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            await create_community("did:agentx:creator-001", data)

        # Second execute call updates member_count to 1
        update_call = conn.execute.call_args_list[1][0][0]
        assert "member_count = 1" in update_call

    @pytest.mark.asyncio
    async def test_records_activity_when_service_available(self):
        row = _community_row()
        data = CommunityCreate(name="Test Community", slug="test-community")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute  = AsyncMock()

        mock_svc = MagicMock()
        mock_svc.record_activity = AsyncMock()

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", mock_svc),
        ):
            await create_community("did:agentx:creator-001", data)

        mock_svc.record_activity.assert_awaited_once()
        call_kwargs = mock_svc.record_activity.call_args[1]
        assert call_kwargs["stream_type"] == "community_created"

    @pytest.mark.asyncio
    async def test_activity_stream_failure_does_not_raise(self):
        row = _community_row()
        data = CommunityCreate(name="Test Community", slug="test-community")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        conn.execute  = AsyncMock()

        mock_svc = MagicMock()
        mock_svc.record_activity = AsyncMock(side_effect=RuntimeError("stream down"))

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", mock_svc),
        ):
            # Should not raise despite stream failure
            result = await create_community("did:agentx:creator-001", data)
        assert result.name == "Test Community"


# ── TestJoinCommunity ──────────────────────────────────────────────────────────

class TestJoinCommunity:

    @pytest.mark.asyncio
    async def test_joins_public_active_community(self):
        community_id = uuid4()
        comm = _community_row(community_id=community_id, creator_did="did:agentx:creator-001")
        member = _member_row(community_id=community_id, agent_did="did:agentx:joiner-001")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[comm, member])
        conn.execute  = AsyncMock(return_value="INSERT 0 1")
        conn.fetchval = AsyncMock()

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            result = await join_community(community_id, "did:agentx:joiner-001")

        assert result.agent_did == "did:agentx:joiner-001"
        assert result.role == "MEMBER"

    @pytest.mark.asyncio
    async def test_raises_if_community_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            with pytest.raises(ValueError, match="not found"):
                await join_community(uuid4(), "did:agentx:joiner-001")

    @pytest.mark.asyncio
    async def test_raises_if_community_not_active(self):
        comm = _community_row(status="ARCHIVED")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=comm)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            with pytest.raises(ValueError, match="not active"):
                await join_community(uuid4(), "did:agentx:joiner-001")

    @pytest.mark.asyncio
    async def test_raises_if_community_private(self):
        comm = _community_row(visibility="PRIVATE")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=comm)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            with pytest.raises(ValueError, match="private"):
                await join_community(uuid4(), "did:agentx:joiner-001")

    @pytest.mark.asyncio
    async def test_raises_if_already_member(self):
        comm = _community_row()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=comm)
        conn.execute  = AsyncMock(return_value="INSERT 0 0")  # conflict

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            with pytest.raises(ValueError, match="Already a member"):
                await join_community(uuid4(), "did:agentx:joiner-001")

    @pytest.mark.asyncio
    async def test_notifies_creator_on_join(self):
        community_id = uuid4()
        comm = _community_row(
            community_id=community_id,
            creator_did="did:agentx:creator-001",
        )
        member = _member_row(community_id=community_id, agent_did="did:agentx:joiner-002")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[comm, member])
        conn.execute  = AsyncMock(return_value="INSERT 0 1")

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            await join_community(community_id, "did:agentx:joiner-002")

        # Notification INSERT should have been called
        execute_calls = conn.execute.call_args_list
        notif_calls = [c for c in execute_calls if "COMMUNITY_JOIN" in str(c)]
        assert len(notif_calls) == 1

    @pytest.mark.asyncio
    async def test_no_self_notification(self):
        """Creator joining own community should NOT trigger notification."""
        community_id = uuid4()
        creator_did = "did:agentx:creator-001"
        comm = _community_row(community_id=community_id, creator_did=creator_did)
        member = _member_row(community_id=community_id, agent_did=creator_did)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[comm, member])
        conn.execute  = AsyncMock(return_value="INSERT 0 1")

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            await join_community(community_id, creator_did)

        execute_calls = conn.execute.call_args_list
        notif_calls = [c for c in execute_calls if "COMMUNITY_JOIN" in str(c)]
        assert len(notif_calls) == 0


# ── TestLeaveCommunity ─────────────────────────────────────────────────────────

class TestLeaveCommunity:

    @pytest.mark.asyncio
    async def test_leaves_community_as_member(self):
        community_id = uuid4()
        member = _member_row(community_id=community_id, role="MEMBER")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=member)
        conn.execute  = AsyncMock()

        with patch("src.services.community_service.transaction", return_value=_tx_context(conn)):
            await leave_community(community_id, "did:agentx:member-001")

        # DELETE was called
        delete_calls = [c for c in conn.execute.call_args_list if "DELETE" in str(c)]
        assert len(delete_calls) == 1

    @pytest.mark.asyncio
    async def test_raises_if_not_member(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("src.services.community_service.transaction", return_value=_tx_context(conn)):
            with pytest.raises(ValueError, match="Not a member"):
                await leave_community(uuid4(), "did:agentx:nonmember-001")

    @pytest.mark.asyncio
    async def test_raises_if_sole_admin(self):
        community_id = uuid4()
        admin_member = _member_row(community_id=community_id, role="ADMIN")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=admin_member)
        conn.fetchval = AsyncMock(return_value=1)  # only 1 admin

        with patch("src.services.community_service.transaction", return_value=_tx_context(conn)):
            with pytest.raises(ValueError, match="sole admin"):
                await leave_community(community_id, "did:agentx:admin-001")

    @pytest.mark.asyncio
    async def test_admin_can_leave_if_other_admins_exist(self):
        community_id = uuid4()
        admin_member = _member_row(community_id=community_id, role="ADMIN")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=admin_member)
        conn.fetchval = AsyncMock(return_value=2)  # 2 admins
        conn.execute  = AsyncMock()

        with patch("src.services.community_service.transaction", return_value=_tx_context(conn)):
            await leave_community(community_id, "did:agentx:admin-001")

        delete_calls = [c for c in conn.execute.call_args_list if "DELETE" in str(c)]
        assert len(delete_calls) == 1


# ── TestListCommunities ────────────────────────────────────────────────────────

class TestListCommunities:

    @pytest.mark.asyncio
    async def test_returns_list_of_communities(self):
        rows = [_community_row(), _community_row(name="Another", slug="another")]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await list_communities()

        assert len(result) == 2
        assert all(hasattr(c, "community_id") for c in result)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_none(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await list_communities()

        assert result == []

    @pytest.mark.asyncio
    async def test_passes_limit_and_offset(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            await list_communities(limit=10, offset=5)

        args = conn.fetch.call_args[0]
        assert 10 in args
        assert 5 in args

    @pytest.mark.asyncio
    async def test_filters_by_status(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            await list_communities(status="ARCHIVED")

        args = conn.fetch.call_args[0]
        assert "ARCHIVED" in args


# ── TestGetCommunity ───────────────────────────────────────────────────────────

class TestGetCommunity:

    @pytest.mark.asyncio
    async def test_returns_community_by_id(self):
        community_id = uuid4()
        row = _community_row(community_id=community_id)
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await get_community(community_id)

        assert result.community_id == community_id

    @pytest.mark.asyncio
    async def test_raises_if_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            with pytest.raises(ValueError, match="not found"):
                await get_community(uuid4())

    @pytest.mark.asyncio
    async def test_returns_community_by_slug(self):
        row = _community_row(slug="my-community")
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await get_community_by_slug("my-community")

        assert result.slug == "my-community"

    @pytest.mark.asyncio
    async def test_raises_if_slug_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            with pytest.raises(ValueError, match="not found"):
                await get_community_by_slug("nonexistent-slug")


# ── TestGetMembers ─────────────────────────────────────────────────────────────

class TestGetMembers:

    @pytest.mark.asyncio
    async def test_returns_member_list(self):
        community_id = uuid4()
        rows = [
            _member_row(community_id=community_id, agent_did="did:agentx:a1"),
            _member_row(community_id=community_id, agent_did="did:agentx:a2"),
        ]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await get_community_members(community_id)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_members(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await get_community_members(uuid4())

        assert result == []

    @pytest.mark.asyncio
    async def test_pagination_params_passed(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            await get_community_members(uuid4(), limit=10, offset=20)

        args = conn.fetch.call_args[0]
        assert 10 in args
        assert 20 in args


# ── TestAddPostToCommunity ─────────────────────────────────────────────────────

class TestAddPostToCommunity:

    @pytest.mark.asyncio
    async def test_adds_post_to_community(self):
        community_id = uuid4()
        post_id      = uuid4()
        member       = _member_row(community_id=community_id, role="MEMBER")
        post         = {"post_id": post_id, "status": "ACTIVE"}
        cp_row       = _community_post_row(community_id=community_id, post_id=post_id)
        comm_row     = {"name": "Test Community"}

        conn = AsyncMock()
        conn.fetchrow   = AsyncMock(side_effect=[member, post, cp_row, comm_row])
        conn.fetch      = AsyncMock(return_value=[])  # no other members
        conn.execute    = AsyncMock()
        conn.executemany = AsyncMock()

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            result = await add_post_to_community(community_id, post_id, "did:agentx:member-001")

        assert result.post_id == post_id
        assert result.community_id == community_id

    @pytest.mark.asyncio
    async def test_raises_if_not_member(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            with pytest.raises(ValueError, match="Not a member"):
                await add_post_to_community(uuid4(), uuid4(), "did:agentx:outsider-001")

    @pytest.mark.asyncio
    async def test_raises_if_post_not_found(self):
        community_id = uuid4()
        member = _member_row(community_id=community_id, role="MEMBER")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[member, None])

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            with pytest.raises(ValueError, match="Post not found"):
                await add_post_to_community(community_id, uuid4(), "did:agentx:member-001")

    @pytest.mark.asyncio
    async def test_notifies_other_members(self):
        community_id = uuid4()
        post_id      = uuid4()
        member       = _member_row(community_id=community_id, role="MEMBER")
        post         = {"post_id": post_id, "status": "ACTIVE"}
        cp_row       = _community_post_row(community_id=community_id, post_id=post_id)
        comm_row     = {"name": "Test Community"}
        other_members = [
            {"agent_did": "did:agentx:other-001"},
            {"agent_did": "did:agentx:other-002"},
        ]

        conn = AsyncMock()
        conn.fetchrow    = AsyncMock(side_effect=[member, post, cp_row, comm_row])
        conn.fetch       = AsyncMock(return_value=other_members)
        conn.execute     = AsyncMock()
        conn.executemany = AsyncMock()

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", None),
        ):
            await add_post_to_community(community_id, post_id, "did:agentx:member-001")

        conn.executemany.assert_called_once()

    @pytest.mark.asyncio
    async def test_records_activity_on_post_shared(self):
        community_id = uuid4()
        post_id      = uuid4()
        member       = _member_row(community_id=community_id, role="MEMBER")
        post         = {"post_id": post_id, "status": "ACTIVE"}
        cp_row       = _community_post_row(community_id=community_id, post_id=post_id)
        comm_row     = {"name": "Test Community"}

        conn = AsyncMock()
        conn.fetchrow    = AsyncMock(side_effect=[member, post, cp_row, comm_row])
        conn.fetch       = AsyncMock(return_value=[])
        conn.execute     = AsyncMock()
        conn.executemany = AsyncMock()

        mock_svc = MagicMock()
        mock_svc.record_activity = AsyncMock()

        with (
            patch("src.services.community_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.community_service.activity_stream_svc", mock_svc),
        ):
            await add_post_to_community(community_id, post_id, "did:agentx:member-001")

        mock_svc.record_activity.assert_awaited_once()
        kwargs = mock_svc.record_activity.call_args[1]
        assert kwargs["stream_type"] == "community_posted"


# ── TestCommunityFeed ──────────────────────────────────────────────────────────

class TestCommunityFeed:

    @pytest.mark.asyncio
    async def test_returns_post_list(self):
        community_id = uuid4()
        rows = [_post_row(), _post_row()]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await get_community_feed(community_id)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_posts(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            result = await get_community_feed(uuid4())

        assert result == []

    @pytest.mark.asyncio
    async def test_limit_respected(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.community_service.get_db", return_value=_db_context(conn)):
            await get_community_feed(uuid4(), limit=10)

        args = conn.fetch.call_args[0]
        assert 10 in args
