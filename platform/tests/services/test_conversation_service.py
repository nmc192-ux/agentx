"""
Tests: src/services/conversation_service.py
Phase 23 — Community Conversations

Covers:
  create_thread()              — inserts thread; records activity; verifies community/post
  get_thread()                 — by ID with comment_count; 404 on missing
  list_threads_by_community()  — ordered list; pagination
  add_comment()                — top-level; nested replies; depth limit; parent scoping
                                 THREAD_REPLY notification; no self-notification
                                 @mention notifications
  get_thread_comments()        — ordered ASC; pagination
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services import conversation_service


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


def _thread_row(thread_id=None, community_id=None, post_id=None,
                creator_did="did:agentx:atlas-001", title="AI Discussion",
                comment_count=0):
    return {
        "thread_id":     thread_id or uuid4(),
        "community_id":  community_id,
        "post_id":       post_id,
        "creator_did":   creator_did,
        "title":         title,
        "comment_count": comment_count,
        "created_at":    _now(),
    }


def _comment_row(comment_id=None, thread_id=None, parent_comment_id=None,
                 author_did="did:agentx:atlas-001", content="Hello!", depth=0):
    return {
        "comment_id":        comment_id or uuid4(),
        "thread_id":         thread_id or uuid4(),
        "parent_comment_id": parent_comment_id,
        "author_did":        author_did,
        "content":           content,
        "depth":             depth,
        "created_at":        _now(),
    }


# ── TestCreateThread ───────────────────────────────────────────────────────────

class TestCreateThread:

    @pytest.mark.asyncio
    async def test_create_returns_thread_response(self):
        from src.models.conversation import ThreadCreate
        comm_id = uuid4()
        row = _thread_row(community_id=comm_id)
        data = ThreadCreate(title="AI Discussion")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"status": "ACTIVE"},  # community check
            row,                   # INSERT RETURNING
        ])

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            result = await conversation_service.create_thread(comm_id, "did:agentx:atlas-001", data)

        assert result.title == "AI Discussion"
        assert result.comment_count == 0

    @pytest.mark.asyncio
    async def test_create_without_community(self):
        from src.models.conversation import ThreadCreate
        row = _thread_row(community_id=None)
        data = ThreadCreate(title="Standalone Thread")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            result = await conversation_service.create_thread(None, "did:agentx:atlas-001", data)

        assert result.community_id is None

    @pytest.mark.asyncio
    async def test_create_raises_if_community_not_found(self):
        from src.models.conversation import ThreadCreate
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # community not found

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await conversation_service.create_thread(uuid4(), "did:agentx:atlas-001", ThreadCreate())

    @pytest.mark.asyncio
    async def test_create_raises_if_community_not_active(self):
        from src.models.conversation import ThreadCreate
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"status": "ARCHIVED"})

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="archived"),
        ):
            await conversation_service.create_thread(uuid4(), "did:agentx:atlas-001", ThreadCreate())

    @pytest.mark.asyncio
    async def test_create_with_post_anchor(self):
        from src.models.conversation import ThreadCreate
        comm_id = uuid4()
        post_id = uuid4()
        row = _thread_row(community_id=comm_id, post_id=post_id)
        data = ThreadCreate(title="Post Discussion", post_id=post_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"status": "ACTIVE"},   # community check
            {"post_id": post_id},   # post check
            row,                    # INSERT RETURNING
        ])

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            result = await conversation_service.create_thread(comm_id, "did:agentx:atlas-001", data)

        assert result.post_id == post_id

    @pytest.mark.asyncio
    async def test_create_raises_if_post_not_found(self):
        from src.models.conversation import ThreadCreate
        comm_id = uuid4()
        post_id = uuid4()
        data = ThreadCreate(post_id=post_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"status": "ACTIVE"},  # community ok
            None,                  # post not found
        ])

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Post not found"),
        ):
            await conversation_service.create_thread(comm_id, "did:agentx:atlas-001", data)

    @pytest.mark.asyncio
    async def test_create_records_activity(self):
        from src.models.conversation import ThreadCreate
        row = _thread_row()
        data = ThreadCreate(title="AI Discussion")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"status": "ACTIVE"}, row])

        mock_svc = MagicMock()
        mock_svc.record_activity = AsyncMock(return_value=None)

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", mock_svc),
        ):
            await conversation_service.create_thread(uuid4(), "did:agentx:atlas-001", data)

        mock_svc.record_activity.assert_awaited_once()
        assert mock_svc.record_activity.call_args.kwargs["stream_type"] == "thread_created"

    @pytest.mark.asyncio
    async def test_create_activity_skipped_when_svc_none(self):
        from src.models.conversation import ThreadCreate
        row = _thread_row()
        data = ThreadCreate()
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"status": "ACTIVE"}, row])

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            result = await conversation_service.create_thread(uuid4(), "did:agentx:atlas-001", data)

        assert result is not None  # no crash


# ── TestGetThread ──────────────────────────────────────────────────────────────

class TestGetThread:

    @pytest.mark.asyncio
    async def test_get_returns_thread_with_comment_count(self):
        thread_id = uuid4()
        row = _thread_row(thread_id=thread_id, comment_count=5)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            result = await conversation_service.get_thread(thread_id)

        assert result.thread_id == thread_id
        assert result.comment_count == 5

    @pytest.mark.asyncio
    async def test_get_raises_if_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.conversation_service.get_db", return_value=_db_context(conn)),
            pytest.raises(ValueError, match="not found"),
        ):
            await conversation_service.get_thread(uuid4())


# ── TestListThreadsByCommuntiy ─────────────────────────────────────────────────

class TestListThreadsByCommunity:

    @pytest.mark.asyncio
    async def test_list_returns_threads(self):
        comm_id = uuid4()
        rows = [_thread_row(community_id=comm_id), _thread_row(community_id=comm_id)]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            result = await conversation_service.list_threads_by_community(comm_id)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_respects_limit_offset(self):
        comm_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            await conversation_service.list_threads_by_community(comm_id, limit=5, offset=10)

        call_args = conn.fetch.call_args
        assert call_args.args[2] == 5
        assert call_args.args[3] == 10

    @pytest.mark.asyncio
    async def test_list_returns_empty(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            result = await conversation_service.list_threads_by_community(uuid4())

        assert result == []


# ── TestAddComment ─────────────────────────────────────────────────────────────

class TestAddComment:

    @pytest.mark.asyncio
    async def test_add_top_level_comment(self):
        from src.models.conversation import CommentCreate
        thread_id = uuid4()
        data = CommentCreate(content="Hello, world!")
        row = _comment_row(thread_id=thread_id, content="Hello, world!")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"thread_id": thread_id},  # thread exists
            row,                        # INSERT RETURNING
        ])
        conn.execute     = AsyncMock(return_value=None)
        conn.executemany = AsyncMock(return_value=None)

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            result = await conversation_service.add_comment(thread_id, "did:agentx:atlas-001", data)

        assert result.content == "Hello, world!"
        assert result.depth == 0

    @pytest.mark.asyncio
    async def test_add_reply_increments_depth(self):
        from src.models.conversation import CommentCreate
        thread_id  = uuid4()
        parent_id  = uuid4()
        data = CommentCreate(content="A reply", parent_comment_id=parent_id)
        parent_row = _comment_row(comment_id=parent_id, thread_id=thread_id, depth=0)
        reply_row  = _comment_row(thread_id=thread_id, depth=1, parent_comment_id=parent_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"thread_id": thread_id},  # thread exists
            parent_row,                 # parent lookup
            reply_row,                  # INSERT RETURNING
        ])
        conn.execute     = AsyncMock(return_value=None)
        conn.executemany = AsyncMock(return_value=None)

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            result = await conversation_service.add_comment(thread_id, "did:agentx:nova-001", data)

        assert result.depth == 1

    @pytest.mark.asyncio
    async def test_add_comment_at_max_depth(self):
        """Depth 4 is allowed; depth 5 would exceed the limit."""
        from src.models.conversation import CommentCreate
        thread_id = uuid4()
        parent_id = uuid4()
        data = CommentCreate(content="Deep reply", parent_comment_id=parent_id)
        parent_row = _comment_row(comment_id=parent_id, thread_id=thread_id, depth=4)
        result_row = _comment_row(thread_id=thread_id, depth=5, parent_comment_id=parent_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"thread_id": thread_id}, parent_row])
        conn.execute  = AsyncMock(return_value=None)

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Maximum comment depth reached"),
        ):
            await conversation_service.add_comment(thread_id, "did:agentx:nova-001", data)

    @pytest.mark.asyncio
    async def test_add_comment_depth_4_is_allowed(self):
        from src.models.conversation import CommentCreate
        thread_id = uuid4()
        parent_id = uuid4()
        data = CommentCreate(content="Almost at limit", parent_comment_id=parent_id)
        parent_row = _comment_row(comment_id=parent_id, thread_id=thread_id, depth=3)
        result_row = _comment_row(thread_id=thread_id, depth=4, parent_comment_id=parent_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"thread_id": thread_id}, parent_row, result_row])
        conn.execute     = AsyncMock(return_value=None)
        conn.executemany = AsyncMock(return_value=None)

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            result = await conversation_service.add_comment(thread_id, "did:agentx:nova-001", data)

        assert result.depth == 4

    @pytest.mark.asyncio
    async def test_add_comment_raises_if_thread_not_found(self):
        from src.models.conversation import CommentCreate
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="Thread not found"),
        ):
            await conversation_service.add_comment(uuid4(), "did:agentx:atlas-001",
                                                   CommentCreate(content="Hi"))

    @pytest.mark.asyncio
    async def test_add_comment_raises_if_parent_from_different_thread(self):
        from src.models.conversation import CommentCreate
        thread_id       = uuid4()
        other_thread_id = uuid4()
        parent_id       = uuid4()
        data = CommentCreate(content="Wrong parent", parent_comment_id=parent_id)
        parent_row = _comment_row(comment_id=parent_id, thread_id=other_thread_id, depth=0)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[
            {"thread_id": thread_id},  # thread exists
            parent_row,                 # parent from different thread
        ])

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            pytest.raises(ValueError, match="does not belong to this thread"),
        ):
            await conversation_service.add_comment(thread_id, "did:agentx:atlas-001", data)

    @pytest.mark.asyncio
    async def test_add_reply_sends_thread_reply_notification(self):
        from src.models.conversation import CommentCreate
        thread_id   = uuid4()
        parent_id   = uuid4()
        author_did  = "did:agentx:nova-001"
        parent_author = "did:agentx:atlas-001"
        data = CommentCreate(content="Reply!", parent_comment_id=parent_id)
        parent_row = _comment_row(comment_id=parent_id, thread_id=thread_id,
                                   author_did=parent_author, depth=0)
        reply_row  = _comment_row(thread_id=thread_id, depth=1, parent_comment_id=parent_id,
                                   author_did=author_did)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"thread_id": thread_id}, parent_row, reply_row])
        conn.execute     = AsyncMock(return_value=None)
        conn.executemany = AsyncMock(return_value=None)

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            await conversation_service.add_comment(thread_id, author_did, data)

        notif_calls = [c for c in conn.execute.call_args_list if "THREAD_REPLY" in c.args[0]]
        assert len(notif_calls) == 1

    @pytest.mark.asyncio
    async def test_no_self_thread_reply_notification(self):
        """An agent replying to their own comment should not get a notification."""
        from src.models.conversation import CommentCreate
        thread_id  = uuid4()
        parent_id  = uuid4()
        agent_did  = "did:agentx:atlas-001"
        data = CommentCreate(content="Self reply", parent_comment_id=parent_id)
        parent_row = _comment_row(comment_id=parent_id, thread_id=thread_id,
                                   author_did=agent_did, depth=0)
        reply_row  = _comment_row(thread_id=thread_id, depth=1, parent_comment_id=parent_id,
                                   author_did=agent_did)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"thread_id": thread_id}, parent_row, reply_row])
        conn.execute     = AsyncMock(return_value=None)
        conn.executemany = AsyncMock(return_value=None)

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            await conversation_service.add_comment(thread_id, agent_did, data)

        notif_calls = [c for c in conn.execute.call_args_list if "THREAD_REPLY" in c.args[0]]
        assert len(notif_calls) == 0

    @pytest.mark.asyncio
    async def test_add_comment_detects_mention(self):
        from src.models.conversation import CommentCreate
        thread_id  = uuid4()
        author_did = "did:agentx:atlas-001"
        content    = "Hey @did:agentx:nova-001, check this out!"
        data = CommentCreate(content=content)
        row = _comment_row(thread_id=thread_id, author_did=author_did, content=content)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"thread_id": thread_id}, row])
        conn.execute     = AsyncMock(return_value=None)
        conn.executemany = AsyncMock(return_value=None)

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            await conversation_service.add_comment(thread_id, author_did, data)

        conn.executemany.assert_awaited_once()
        mention_rows = conn.executemany.call_args.args[1]
        mentioned_dids = [r[0] for r in mention_rows]
        assert "did:agentx:nova-001" in mentioned_dids

    @pytest.mark.asyncio
    async def test_mention_skips_self(self):
        from src.models.conversation import CommentCreate
        thread_id  = uuid4()
        author_did = "did:agentx:atlas-001"
        content    = "I am @did:agentx:atlas-001 and this is fine"
        data = CommentCreate(content=content)
        row = _comment_row(thread_id=thread_id, author_did=author_did, content=content)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"thread_id": thread_id}, row])
        conn.execute     = AsyncMock(return_value=None)
        conn.executemany = AsyncMock(return_value=None)

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            await conversation_service.add_comment(thread_id, author_did, data)

        # executemany not called (no non-self mentions)
        conn.executemany.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_add_comment_records_activity(self):
        from src.models.conversation import CommentCreate
        thread_id = uuid4()
        data = CommentCreate(content="Activity test")
        row = _comment_row(thread_id=thread_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[{"thread_id": thread_id}, row])
        conn.execute     = AsyncMock(return_value=None)
        conn.executemany = AsyncMock(return_value=None)

        mock_svc = MagicMock()
        mock_svc.record_activity = AsyncMock(return_value=None)

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", mock_svc),
        ):
            await conversation_service.add_comment(thread_id, "did:agentx:atlas-001", data)

        mock_svc.record_activity.assert_awaited_once()
        assert mock_svc.record_activity.call_args.kwargs["stream_type"] == "comment_added"


# ── TestGetThreadComments ──────────────────────────────────────────────────────

class TestGetThreadComments:

    @pytest.mark.asyncio
    async def test_get_comments_returns_list(self):
        thread_id = uuid4()
        rows = [_comment_row(thread_id=thread_id), _comment_row(thread_id=thread_id)]
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            result = await conversation_service.get_thread_comments(thread_id)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_comments_respects_pagination(self):
        thread_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            await conversation_service.get_thread_comments(thread_id, limit=10, offset=5)

        call_args = conn.fetch.call_args
        assert call_args.args[2] == 10
        assert call_args.args[3] == 5

    @pytest.mark.asyncio
    async def test_get_comments_empty(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            result = await conversation_service.get_thread_comments(uuid4())

        assert result == []

    @pytest.mark.asyncio
    async def test_get_comments_ordered_asc(self):
        """Verify the SQL query uses ASC ordering."""
        thread_id = uuid4()
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            await conversation_service.get_thread_comments(thread_id)

        sql = conn.fetch.call_args.args[0]
        assert "ASC" in sql
