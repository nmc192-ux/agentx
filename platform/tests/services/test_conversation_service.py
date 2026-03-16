"""
Tests: src/services/conversation_service.py
Phase 23 — Community Conversations

Covers:
  create_thread()
  get_thread()
  list_threads_by_community()
  add_comment()
  get_thread_comments()
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.services.conversation_service import (
    add_comment,
    create_thread,
    get_thread,
    get_thread_comments,
    list_threads_by_community,
)
from src.models.conversation import CommentCreate, ThreadCreate


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


def _thread_row(thread_id=None, community_id=None, post_id=None,
                creator_did="did:agentx:creator-001", title="Test Thread",
                comment_count=0):
    return {
        "thread_id":     thread_id or uuid4(),
        "community_id":  community_id,
        "post_id":       post_id,
        "creator_did":   creator_did,
        "title":         title,
        "comment_count": comment_count,
        "created_at":    datetime.now(UTC),
    }


def _comment_row(comment_id=None, thread_id=None, parent_comment_id=None,
                 author_did="did:agentx:author-001", content="Hello world",
                 depth=0):
    return {
        "comment_id":        comment_id or uuid4(),
        "thread_id":         thread_id or uuid4(),
        "parent_comment_id": parent_comment_id,
        "author_did":        author_did,
        "content":           content,
        "depth":             depth,
        "created_at":        datetime.now(UTC),
    }


# ── TestCreateThread ───────────────────────────────────────────────────────────

class TestCreateThread:

    @pytest.mark.asyncio
    async def test_creates_thread_and_returns_response(self):
        community_id = uuid4()
        thread_id    = uuid4()
        row = _thread_row(thread_id=thread_id, community_id=community_id, title="My Thread")
        data = ThreadCreate(title="My Thread")

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=community_id)  # community exists
        conn.fetchrow = AsyncMock(return_value=row)

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            result = await create_thread(
                community_id=community_id,
                creator_did="did:agentx:creator-001",
                data=data,
            )

        assert result.thread_id == thread_id
        assert result.title == "My Thread"
        assert result.comment_count == 0

    @pytest.mark.asyncio
    async def test_raises_if_community_not_found(self):
        data = ThreadCreate(title="Orphaned Thread")

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=None)  # community missing

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            with pytest.raises(ValueError, match="Community not found"):
                await create_thread(
                    community_id=uuid4(),
                    creator_did="did:agentx:creator-001",
                    data=data,
                )

    @pytest.mark.asyncio
    async def test_creates_thread_without_community(self):
        """Thread can be created with community_id=None (post-anchored)."""
        thread_id = uuid4()
        row = _thread_row(thread_id=thread_id, community_id=None)
        data = ThreadCreate(title="Post Thread")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            result = await create_thread(
                community_id=None,
                creator_did="did:agentx:creator-001",
                data=data,
            )

        assert result.thread_id == thread_id
        assert result.community_id is None

    @pytest.mark.asyncio
    async def test_records_activity_on_success(self):
        community_id = uuid4()
        row = _thread_row(community_id=community_id)
        data = ThreadCreate(title="Active Thread")

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=community_id)
        conn.fetchrow = AsyncMock(return_value=row)

        mock_svc = MagicMock()
        mock_svc.record_activity = AsyncMock()

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", mock_svc),
        ):
            await create_thread(
                community_id=community_id,
                creator_did="did:agentx:creator-001",
                data=data,
            )

        mock_svc.record_activity.assert_awaited_once()
        call_kwargs = mock_svc.record_activity.call_args[1]
        assert call_kwargs["stream_type"] == "thread_created"
        assert call_kwargs["ref_entity_type"] == "thread"

    @pytest.mark.asyncio
    async def test_raises_if_post_not_found(self):
        post_id = uuid4()
        data = ThreadCreate(title="Post-anchored Thread", post_id=post_id)

        conn = AsyncMock()
        # fetchval calls: community check returns None (no community), then post check returns None
        conn.fetchval = AsyncMock(return_value=None)  # post not found

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            with pytest.raises(ValueError, match="Post not found"):
                await create_thread(
                    community_id=None,
                    creator_did="did:agentx:creator-001",
                    data=data,
                )

    @pytest.mark.asyncio
    async def test_soft_fails_on_activity_stream_error(self):
        community_id = uuid4()
        row = _thread_row(community_id=community_id)
        data = ThreadCreate(title="Resilient Thread")

        conn = AsyncMock()
        conn.fetchval = AsyncMock(return_value=community_id)
        conn.fetchrow = AsyncMock(return_value=row)

        mock_svc = MagicMock()
        mock_svc.record_activity = AsyncMock(side_effect=RuntimeError("stream down"))

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", mock_svc),
        ):
            # Should not raise despite activity stream failure
            result = await create_thread(
                community_id=community_id,
                creator_did="did:agentx:creator-001",
                data=data,
            )

        assert result is not None


# ── TestGetThread ──────────────────────────────────────────────────────────────

class TestGetThread:

    @pytest.mark.asyncio
    async def test_returns_thread_by_id(self):
        thread_id = uuid4()
        row = _thread_row(thread_id=thread_id, comment_count=5)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            result = await get_thread(thread_id)

        assert result.thread_id == thread_id
        assert result.comment_count == 5

    @pytest.mark.asyncio
    async def test_raises_if_not_found(self):
        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            with pytest.raises(ValueError, match="Thread not found"):
                await get_thread(uuid4())

    @pytest.mark.asyncio
    async def test_includes_community_id(self):
        community_id = uuid4()
        thread_id    = uuid4()
        row = _thread_row(thread_id=thread_id, community_id=community_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            result = await get_thread(thread_id)

        assert result.community_id == community_id

    @pytest.mark.asyncio
    async def test_uses_get_db_not_transaction(self):
        thread_id = uuid4()
        row = _thread_row(thread_id=thread_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)

        mock_get_db  = MagicMock(return_value=_db_context(conn))
        mock_tx      = MagicMock()

        with (
            patch("src.services.conversation_service.get_db", mock_get_db),
            patch("src.services.conversation_service.transaction", mock_tx),
        ):
            await get_thread(thread_id)

        mock_get_db.assert_called_once()
        mock_tx.assert_not_called()


# ── TestListThreads ────────────────────────────────────────────────────────────

class TestListThreads:

    @pytest.mark.asyncio
    async def test_returns_list_of_threads(self):
        community_id = uuid4()
        rows = [_thread_row(community_id=community_id), _thread_row(community_id=community_id)]

        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            result = await list_threads_by_community(community_id=community_id)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_list_if_none(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            result = await list_threads_by_community(community_id=uuid4())

        assert result == []

    @pytest.mark.asyncio
    async def test_respects_limit_and_offset(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            await list_threads_by_community(community_id=uuid4(), limit=10, offset=20)

        args = conn.fetch.call_args[0]
        # $2=limit, $3=offset — positional args after SQL string
        assert 10 in args
        assert 20 in args

    @pytest.mark.asyncio
    async def test_ordered_by_created_at_desc(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            await list_threads_by_community(community_id=uuid4())

        sql = conn.fetch.call_args[0][0]
        assert "DESC" in sql


# ── TestAddComment ─────────────────────────────────────────────────────────────

class TestAddComment:

    @pytest.mark.asyncio
    async def test_adds_top_level_comment(self):
        thread_id  = uuid4()
        comment_id = uuid4()
        thread_row = {"thread_id": thread_id}
        comment_row = _comment_row(comment_id=comment_id, thread_id=thread_id, depth=0)
        data = CommentCreate(content="Top level comment")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[thread_row, comment_row])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            result = await add_comment(thread_id=thread_id, author_did="did:agentx:author-001", data=data)

        assert result.comment_id == comment_id
        assert result.depth == 0

    @pytest.mark.asyncio
    async def test_adds_reply_with_correct_depth(self):
        thread_id  = uuid4()
        parent_id  = uuid4()
        comment_id = uuid4()
        parent_author = "did:agentx:parent-author"
        author_did    = "did:agentx:replier-001"

        thread_row  = {"thread_id": thread_id}
        parent_row  = {
            "comment_id": parent_id,
            "thread_id":  thread_id,
            "author_did": parent_author,
            "depth":      1,
        }
        comment_row = _comment_row(comment_id=comment_id, thread_id=thread_id, depth=2)
        data = CommentCreate(content="Reply comment", parent_comment_id=parent_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[thread_row, parent_row, comment_row])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            result = await add_comment(thread_id=thread_id, author_did=author_did, data=data)

        assert result.depth == 2

    @pytest.mark.asyncio
    async def test_raises_on_depth_exceeded(self):
        thread_id = uuid4()
        parent_id = uuid4()

        thread_row = {"thread_id": thread_id}
        parent_row = {
            "comment_id": parent_id,
            "thread_id":  thread_id,
            "author_did": "did:agentx:deep-author",
            "depth":      4,   # adding reply would make depth 5 → exceeds limit
        }
        data = CommentCreate(content="Too deep", parent_comment_id=parent_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[thread_row, parent_row])

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            with pytest.raises(ValueError, match="Maximum comment depth reached"):
                await add_comment(thread_id=thread_id, author_did="did:agentx:author", data=data)

    @pytest.mark.asyncio
    async def test_raises_on_wrong_thread_parent(self):
        thread_id      = uuid4()
        other_thread   = uuid4()
        parent_id      = uuid4()

        thread_row = {"thread_id": thread_id}
        parent_row = {
            "comment_id": parent_id,
            "thread_id":  other_thread,  # belongs to a different thread
            "author_did": "did:agentx:other",
            "depth":      0,
        }
        data = CommentCreate(content="Misplaced reply", parent_comment_id=parent_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[thread_row, parent_row])

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            with pytest.raises(ValueError, match="different thread"):
                await add_comment(thread_id=thread_id, author_did="did:agentx:author", data=data)

    @pytest.mark.asyncio
    async def test_raises_if_thread_not_found(self):
        data = CommentCreate(content="Orphaned comment")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=None)  # thread not found

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            with pytest.raises(ValueError, match="Thread not found"):
                await add_comment(thread_id=uuid4(), author_did="did:agentx:author", data=data)

    @pytest.mark.asyncio
    async def test_sends_thread_reply_notification(self):
        thread_id     = uuid4()
        parent_id     = uuid4()
        comment_id    = uuid4()
        parent_author = "did:agentx:parent-author"
        author_did    = "did:agentx:replier-001"

        thread_row  = {"thread_id": thread_id}
        parent_row  = {
            "comment_id": parent_id,
            "thread_id":  thread_id,
            "author_did": parent_author,
            "depth":      0,
        }
        comment_row = _comment_row(comment_id=comment_id, thread_id=thread_id, depth=1)
        data = CommentCreate(content="Replying to you", parent_comment_id=parent_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[thread_row, parent_row, comment_row])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            await add_comment(thread_id=thread_id, author_did=author_did, data=data)

        # At least one execute call should contain THREAD_REPLY
        all_sqls = [str(call[0][0]) for call in conn.execute.call_args_list]
        assert any("THREAD_REPLY" in sql for sql in all_sqls)

    @pytest.mark.asyncio
    async def test_no_self_reply_notification(self):
        """Replying to own comment should not trigger THREAD_REPLY notification."""
        thread_id  = uuid4()
        parent_id  = uuid4()
        author_did = "did:agentx:self"

        thread_row  = {"thread_id": thread_id}
        parent_row  = {
            "comment_id": parent_id,
            "thread_id":  thread_id,
            "author_did": author_did,  # same as replier
            "depth":      0,
        }
        comment_row = _comment_row(thread_id=thread_id, author_did=author_did, depth=1)
        data = CommentCreate(content="Replying to myself", parent_comment_id=parent_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[thread_row, parent_row, comment_row])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            await add_comment(thread_id=thread_id, author_did=author_did, data=data)

        # No THREAD_REPLY notification
        all_sqls = [str(call[0][0]) for call in conn.execute.call_args_list]
        assert not any("THREAD_REPLY" in sql for sql in all_sqls)

    @pytest.mark.asyncio
    async def test_sends_mention_notification(self):
        thread_id    = uuid4()
        comment_id   = uuid4()
        author_did   = "did:agentx:author-001"
        mentioned    = "did:agentx:mentioned-001"

        thread_row  = {"thread_id": thread_id}
        comment_row = _comment_row(
            comment_id=comment_id,
            thread_id=thread_id,
            content=f"Hey @{mentioned} check this out",
        )
        data = CommentCreate(content=f"Hey @{mentioned} check this out")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[thread_row, comment_row])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            await add_comment(thread_id=thread_id, author_did=author_did, data=data)

        all_sqls = [str(call[0][0]) for call in conn.execute.call_args_list]
        assert any("MENTION" in sql for sql in all_sqls)

    @pytest.mark.asyncio
    async def test_no_self_mention_notification(self):
        """Self-mentions should be skipped."""
        thread_id  = uuid4()
        author_did = "did:agentx:self-001"

        thread_row  = {"thread_id": thread_id}
        comment_row = _comment_row(
            thread_id=thread_id,
            content=f"I mention @{author_did} myself",
        )
        data = CommentCreate(content=f"I mention @{author_did} myself")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[thread_row, comment_row])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            await add_comment(thread_id=thread_id, author_did=author_did, data=data)

        all_sqls = [str(call[0][0]) for call in conn.execute.call_args_list]
        assert not any("MENTION" in sql for sql in all_sqls)

    @pytest.mark.asyncio
    async def test_records_activity_on_success(self):
        thread_id  = uuid4()
        comment_id = uuid4()
        author_did = "did:agentx:author-001"

        thread_row  = {"thread_id": thread_id}
        comment_row = _comment_row(comment_id=comment_id, thread_id=thread_id)
        data = CommentCreate(content="Activity comment")

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[thread_row, comment_row])
        conn.execute  = AsyncMock()

        mock_svc = MagicMock()
        mock_svc.record_activity = AsyncMock()

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", mock_svc),
        ):
            await add_comment(thread_id=thread_id, author_did=author_did, data=data)

        mock_svc.record_activity.assert_awaited_once()
        call_kwargs = mock_svc.record_activity.call_args[1]
        assert call_kwargs["stream_type"] == "comment_added"

    @pytest.mark.asyncio
    async def test_depth_4_is_valid(self):
        """Depth 4 (parent.depth=3 → new depth=4) should succeed."""
        thread_id  = uuid4()
        parent_id  = uuid4()
        comment_id = uuid4()

        thread_row  = {"thread_id": thread_id}
        parent_row  = {
            "comment_id": parent_id,
            "thread_id":  thread_id,
            "author_did": "did:agentx:other",
            "depth":      3,   # depth 3 + 1 = 4, which is the limit (not exceeded)
        }
        comment_row = _comment_row(comment_id=comment_id, thread_id=thread_id, depth=4)
        data = CommentCreate(content="Max depth comment", parent_comment_id=parent_id)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(side_effect=[thread_row, parent_row, comment_row])
        conn.execute  = AsyncMock()

        with (
            patch("src.services.conversation_service.transaction", return_value=_tx_context(conn)),
            patch("src.services.conversation_service.activity_stream_svc", None),
        ):
            result = await add_comment(
                thread_id=thread_id,
                author_did="did:agentx:author",
                data=data,
            )

        assert result.depth == 4


# ── TestGetThreadComments ──────────────────────────────────────────────────────

class TestGetThreadComments:

    @pytest.mark.asyncio
    async def test_returns_comments_list(self):
        thread_id = uuid4()
        rows = [
            _comment_row(thread_id=thread_id),
            _comment_row(thread_id=thread_id),
        ]

        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=rows)

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            result = await get_thread_comments(thread_id=thread_id)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            result = await get_thread_comments(thread_id=uuid4())

        assert result == []

    @pytest.mark.asyncio
    async def test_ordered_by_created_at_asc(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            await get_thread_comments(thread_id=uuid4())

        sql = conn.fetch.call_args[0][0]
        assert "ASC" in sql

    @pytest.mark.asyncio
    async def test_respects_limit_and_offset(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.conversation_service.get_db", return_value=_db_context(conn)):
            await get_thread_comments(thread_id=uuid4(), limit=5, offset=15)

        args = conn.fetch.call_args[0]
        assert 5 in args
        assert 15 in args

    @pytest.mark.asyncio
    async def test_uses_get_db_not_transaction(self):
        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[])

        mock_get_db = MagicMock(return_value=_db_context(conn))
        mock_tx     = MagicMock()

        with (
            patch("src.services.conversation_service.get_db", mock_get_db),
            patch("src.services.conversation_service.transaction", mock_tx),
        ):
            await get_thread_comments(thread_id=uuid4())

        mock_get_db.assert_called_once()
        mock_tx.assert_not_called()
