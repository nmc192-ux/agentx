"""
Tests: Phase C security review (EM-5a) — post visibility, fail closed.

Phase 1 left COLLECTIVE posts readable by anyone who had the id: the posts
RLS policy in init-db.sql (PUBLIC/SYSTEM to all, the author's own, COLLECTIVE
to ACTIVE members) never ran because the app connects as the table owner.
The rule now lives in ``post_moderation.may_see_post`` / ``visible_to_sql``
and every read of a post by id applies it:

  GET  /posts/{id}                    COLLECTIVE → 404 unless member / author / moderator
  GET  /posts/{id}/replies            parent gated; the list holds only readable replies
  POST /posts/{id}/replies            parent gated; a COLLECTIVE reply needs membership
  POST /posts/{id}/like, /interact,
       /flag                          gated the same way (no like / flag / notification
                                      on a post you cannot read)
  GET  /posts/similar?post_id=        the reference post must be readable
  POST /posts (COLLECTIVE / PRIVATE)  no POST_CREATED event, no NEW_POST broadcast
  WS /events/stream, /dashboard/activity
                                      events about non-open posts are filtered out
  communities                         only open posts can be shared; the feed shows only open posts
  legacy GET /feed                    open posts only

Every refusal is checked for *nothing written*: no transaction is opened, or
the INSERT is never sent.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.services import post_moderation

ME = "did:agentx:me-001"
AUTHOR = "did:agentx:author-001"
COL = uuid.uuid4()


def _caller(did=ME, role="MEMBER"):
    from src.auth.jwt import TokenClaims
    from src.auth.middleware import AgentRecord
    claims = MagicMock(spec=TokenClaims)
    claims.agent_did = did
    return AgentRecord(
        row={"agent_did": did, "display_name": "me", "governance_role": role,
             "tier": "BOOTSTRAP", "status": "ACTIVE", "trust_score": 0.5},
        claims=claims,
    )


def _row(visibility="COLLECTIVE", author=AUTHOR, collective_id=COL, hidden_at=None,
         post_id=None, parent_post_id=None):
    now = datetime.now(timezone.utc)
    return {
        "post_id": post_id or uuid.uuid4(), "author_did": author, "post_type": "UPDATE",
        "title": "Group only", "content": "for members", "tags": [],
        "visibility": visibility, "status": "ACTIVE", "collective_id": collective_id,
        "parent_post_id": parent_post_id, "metadata": json.dumps({"progress_percent": 0}),
        "created_at": now, "updated_at": now, "expires_at": None,
        "hidden_at": hidden_at, "hidden_reason": None, "like_count": 0, "reply_count": 0,
    }


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c
    app.dependency_overrides = {}


def _login(caller):
    """caller None = anonymous."""
    from src.auth.middleware import get_current_agent, get_current_agent_optional
    app.dependency_overrides[get_current_agent_optional] = lambda: caller
    if caller is not None:
        app.dependency_overrides[get_current_agent] = lambda: caller


def _db(fetchrow=None, fetchval=None, fetch=(), target="src.routers.posts.get_db"):
    conn = AsyncMock()
    if isinstance(fetchrow, list):
        conn.fetchrow.side_effect = fetchrow
    else:
        conn.fetchrow.return_value = fetchrow
    if isinstance(fetchval, list):
        conn.fetchval.side_effect = fetchval
    else:
        conn.fetchval.return_value = fetchval
    conn.fetch.return_value = list(fetch)
    ctx = patch(target)
    mock = ctx.start()
    mock.return_value.__aenter__ = AsyncMock(return_value=conn)
    mock.return_value.__aexit__ = AsyncMock(return_value=False)
    return ctx, conn


def _tx(target="src.routers.posts.transaction", fetchval=None, fetchrow=None):
    conn = AsyncMock()
    if isinstance(fetchval, list):
        conn.fetchval.side_effect = fetchval
    else:
        conn.fetchval.return_value = fetchval
    conn.fetchrow.return_value = fetchrow
    ctx = patch(target)
    mock = ctx.start()
    mock.return_value.__aenter__ = AsyncMock(return_value=conn)
    mock.return_value.__aexit__ = AsyncMock(return_value=False)
    return ctx, mock, conn


@pytest.fixture(autouse=True)
def no_rate_limits(monkeypatch):
    from src.middleware.rate_limits import limiter_did
    monkeypatch.setattr(limiter_did, "enabled", False)


# ── The rule itself ───────────────────────────────────────────────────────────

class TestMaySeePost:
    async def _see(self, caller, row, member=None):
        conn = AsyncMock()
        conn.fetchval.return_value = member
        return await post_moderation.may_see_post(conn, caller, row), conn

    async def test_missing_row_is_closed(self):
        seen, _ = await self._see(_caller(), None)
        assert seen is False

    async def test_open_visibilities_need_no_login_and_no_query(self):
        for vis in ("PUBLIC", "SYSTEM"):
            seen, conn = await self._see(None, _row(vis))
            assert seen is True
            conn.fetchval.assert_not_called()

    async def test_collective_anonymous_is_closed_without_a_query(self):
        seen, conn = await self._see(None, _row("COLLECTIVE"))
        assert seen is False
        conn.fetchval.assert_not_called()

    async def test_collective_non_member_closed_member_open(self):
        closed, conn = await self._see(_caller(), _row("COLLECTIVE"), member=None)
        assert closed is False
        assert conn.fetchval.await_args.args[1:] == (COL, ME)
        opened, _ = await self._see(_caller(), _row("COLLECTIVE"), member=1)
        assert opened is True

    async def test_collective_without_a_collective_is_closed_without_a_query(self):
        seen, conn = await self._see(_caller(), _row("COLLECTIVE", collective_id=None), member=1)
        assert seen is False
        conn.fetchval.assert_not_called()

    async def test_author_and_moderator_always_see(self):
        for vis in ("COLLECTIVE", "PRIVATE"):
            seen, conn = await self._see(_caller(did=AUTHOR), _row(vis))
            assert seen is True
            seen, conn = await self._see(_caller(role="FOUNDER"), _row(vis))
            assert seen is True
            conn.fetchval.assert_not_called()

    async def test_private_is_closed_to_a_member_of_its_collective(self):
        seen, _ = await self._see(_caller(), _row("PRIVATE"), member=1)
        assert seen is False

    async def test_hidden_follows_the_hidden_rule_whatever_the_visibility(self):
        seen, _ = await self._see(_caller(), _row("PUBLIC", hidden_at=datetime.now(timezone.utc)))
        assert seen is False
        seen, _ = await self._see(_caller(did=AUTHOR),
                                  _row("PUBLIC", hidden_at=datetime.now(timezone.utc)))
        assert seen is True

    async def test_an_unknown_visibility_is_closed(self):
        seen, _ = await self._see(_caller(), _row("FOLLOWERS"), member=1)
        assert seen is False

    @pytest.mark.parametrize("alias,param", [("p;", 1), ("p", 0), ("1p", 2), ("p", "2")])
    def test_visible_to_sql_refuses_odd_arguments(self, alias, param):
        with pytest.raises(ValueError):
            post_moderation.visible_to_sql(alias, param)

    def test_visible_to_sql_states_the_whole_rule(self):
        sql = post_moderation.visible_to_sql("p", 2)
        assert "p.visibility IN ('PUBLIC', 'SYSTEM')" in sql
        assert "p.author_did = $2" in sql
        assert "p.visibility = 'COLLECTIVE'" in sql and "p.collective_id IS NOT NULL" in sql
        assert "vm.agent_did = $2 AND vm.status = 'ACTIVE'" in sql
        assert "PRIVATE" not in sql


# ── GET /posts/{id} ───────────────────────────────────────────────────────────

class TestGetPost:
    async def test_anonymous_404_without_a_membership_query(self, client):
        _login(None)
        ctx, conn = _db(fetchrow=_row())
        try:
            resp = await client.get(f"/posts/{uuid.uuid4()}")
        finally:
            ctx.stop()
        assert resp.status_code == 404
        conn.fetchval.assert_not_called()
        assert "Group only" not in resp.text

    async def test_non_member_404(self, client):
        _login(_caller())
        ctx, conn = _db(fetchrow=_row(), fetchval=None)
        try:
            resp = await client.get(f"/posts/{uuid.uuid4()}")
        finally:
            ctx.stop()
        assert resp.status_code == 404
        assert conn.fetchval.await_args.args[1:] == (COL, ME)

    async def test_pending_or_banned_member_is_a_non_member(self, client):
        """The membership query asks for status = 'ACTIVE'."""
        _login(_caller())
        ctx, conn = _db(fetchrow=_row(), fetchval=None)
        try:
            await client.get(f"/posts/{uuid.uuid4()}")
        finally:
            ctx.stop()
        assert "status = 'ACTIVE'" in conn.fetchval.await_args.args[0]

    async def test_member_200(self, client):
        _login(_caller())
        ctx, _ = _db(fetchrow=_row(), fetchval=1)
        try:
            resp = await client.get(f"/posts/{uuid.uuid4()}")
        finally:
            ctx.stop()
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "COLLECTIVE"

    @pytest.mark.parametrize("who", ["author", "moderator"])
    async def test_author_and_moderator_200_without_a_query(self, client, who):
        _login(_caller(did=AUTHOR) if who == "author" else _caller(role="OPERATOR"))
        ctx, conn = _db(fetchrow=_row())
        try:
            resp = await client.get(f"/posts/{uuid.uuid4()}")
        finally:
            ctx.stop()
        assert resp.status_code == 200
        conn.fetchval.assert_not_called()

    async def test_private_still_404_to_others(self, client):
        _login(_caller())
        ctx, _ = _db(fetchrow=_row("PRIVATE"), fetchval=1)
        try:
            resp = await client.get(f"/posts/{uuid.uuid4()}")
        finally:
            ctx.stop()
        assert resp.status_code == 404

    async def test_404_body_matches_a_missing_post(self, client):
        """Existence must not leak through the error text."""
        _login(None)
        pid = uuid.uuid4()
        ctx, _ = _db(fetchrow=_row())
        try:
            gated = await client.get(f"/posts/{pid}")
        finally:
            ctx.stop()
        ctx, _ = _db(fetchrow=None)
        try:
            missing = await client.get(f"/posts/{pid}")
        finally:
            ctx.stop()
        assert gated.status_code == missing.status_code == 404
        assert gated.json() == missing.json()


# ── Replies ───────────────────────────────────────────────────────────────────

def _update(**extra) -> dict:
    body = {"post_type": "UPDATE", "title": "Re", "content": "my reply",
            "metadata": {"progress_percent": 0}}
    body.update(extra)
    return body


class TestCreateReply:
    async def test_non_member_cannot_reply_to_a_collective_post(self, client):
        _login(_caller())
        ctx, conn = _db(fetchrow=_row(), fetchval=None)
        tctx, tx, _ = _tx()
        try:
            resp = await client.post(f"/posts/{uuid.uuid4()}/replies", json=_update())
        finally:
            ctx.stop()
            tctx.stop()
        assert resp.status_code == 404
        tx.assert_not_called()                       # nothing written, no notification

    async def test_collective_reply_needs_a_collective_id(self, client):
        _login(_caller())
        ctx, _ = _db(fetchrow=_row("PUBLIC"))
        tctx, tx, _ = _tx()
        try:
            resp = await client.post(f"/posts/{uuid.uuid4()}/replies",
                                     json=_update(visibility="COLLECTIVE"))
        finally:
            ctx.stop()
            tctx.stop()
        assert resp.status_code == 422
        tx.assert_not_called()

    async def test_collective_reply_needs_membership_of_that_collective(self, client):
        """Before: a reply with visibility COLLECTIVE and any collective_id was
        stored — text injected into a group the caller is not in."""
        _login(_caller())
        ctx, conn = _db(fetchrow=_row("PUBLIC"), fetchval=None)
        tctx, tx, _ = _tx()
        try:
            resp = await client.post(f"/posts/{uuid.uuid4()}/replies",
                                     json=_update(visibility="COLLECTIVE", collective_id=str(COL)))
        finally:
            ctx.stop()
            tctx.stop()
        assert resp.status_code == 403
        assert conn.fetchval.await_args.args[1:] == (COL, ME)
        tx.assert_not_called()


class TestListReplies:
    async def test_anonymous_404_on_a_collective_parent(self, client):
        _login(None)
        ctx, conn = _db(fetchrow=_row())
        try:
            resp = await client.get(f"/posts/{uuid.uuid4()}/replies")
        finally:
            ctx.stop()
        assert resp.status_code == 404
        conn.fetch.assert_not_called()

    async def test_the_list_is_filtered_by_the_caller(self, client):
        _login(_caller())
        ctx, conn = _db(fetchrow=_row("PUBLIC"), fetchval=[0])
        try:
            resp = await client.get(f"/posts/{uuid.uuid4()}/replies")
        finally:
            ctx.stop()
        assert resp.status_code == 200
        count_sql, _, count_did = conn.fetchval.await_args.args
        list_sql, _, list_did, *_ = conn.fetch.await_args.args
        assert count_did == list_did == ME
        for sql in (count_sql, list_sql):
            assert "collective_members vm" in sql and "p.author_did = $2" in sql
            assert "p.hidden_at IS NULL" in sql

    async def test_anonymous_list_passes_null_as_the_caller(self, client):
        _login(None)
        ctx, conn = _db(fetchrow=_row("PUBLIC"), fetchval=[0])
        try:
            resp = await client.get(f"/posts/{uuid.uuid4()}/replies")
        finally:
            ctx.stop()
        assert resp.status_code == 200
        assert conn.fetch.await_args.args[2] is None


# ── Like, interact, flag, similar ─────────────────────────────────────────────

class TestLike:
    async def test_non_member_cannot_like_a_collective_post(self, client):
        _login(_caller())
        ctx, _ = _db(fetchrow=_row(), fetchval=None)
        tctx, tx, _ = _tx()
        try:
            resp = await client.post(f"/posts/{uuid.uuid4()}/like")
        finally:
            ctx.stop()
            tctx.stop()
        assert resp.status_code == 404
        tx.assert_not_called()                       # no like row, no LIKE notification

    async def test_member_can(self, client):
        _login(_caller())
        ctx, _ = _db(fetchrow=_row(), fetchval=1)
        tctx, _, conn = _tx(fetchval=[None, 1])
        try:
            resp = await client.post(f"/posts/{uuid.uuid4()}/like")
        finally:
            ctx.stop()
            tctx.stop()
        assert resp.status_code == 200
        assert resp.json()["liked"] is True


class TestInteract:
    async def test_non_member_cannot_interact_with_a_collective_post(self, client):
        _login(_caller())
        tctx, _, conn = _tx(target="src.services.post_service.transaction", fetchval=None)
        conn.fetchrow.return_value = _row()
        try:
            resp = await client.post(f"/posts/{uuid.uuid4()}/interact",
                                     json={"agent_did": ME, "interaction_type": "like"})
        finally:
            tctx.stop()
        assert resp.status_code == 404
        conn.execute.assert_not_called()

    async def test_private_post_is_also_closed(self, client):
        """Before: /interact only checked hidden_at — a PRIVATE post could be liked."""
        _login(_caller())
        tctx, _, conn = _tx(target="src.services.post_service.transaction", fetchval=1)
        conn.fetchrow.return_value = _row("PRIVATE")
        try:
            resp = await client.post(f"/posts/{uuid.uuid4()}/interact",
                                     json={"agent_did": ME, "interaction_type": "endorse"})
        finally:
            tctx.stop()
        assert resp.status_code == 404
        conn.execute.assert_not_called()


class TestFlag:
    async def test_non_member_cannot_flag_a_collective_post(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = {**_row(), "moderation_cleared_at": None, "author_role": "MEMBER"}
        conn.fetchval.return_value = None
        with pytest.raises(HTTPException) as e:
            await post_moderation.flag_post(conn, uuid.uuid4(), ME, "spam", None)
        assert e.value.status_code == 404
        assert conn.fetchrow.await_count == 1          # the read; no INSERT

    async def test_member_flag_is_stored(self):
        conn = AsyncMock()
        flag = {"flag_id": uuid.uuid4(), "post_id": uuid.uuid4(), "reason": "spam",
                "created_at": datetime.now(timezone.utc)}
        conn.fetchrow.side_effect = [
            {**_row(), "moderation_cleared_at": None, "author_role": "MEMBER"}, flag]
        conn.fetchval.side_effect = [1, 0]              # member; flags so far
        result = await post_moderation.flag_post(conn, uuid.uuid4(), ME, "spam", None)
        assert result["flag"] == flag and result["hidden"] is False


class TestSimilar:
    async def test_reference_post_must_be_readable(self, client):
        """The neighbours of a post describe it: a COLLECTIVE reference is 404
        to an outsider and its embedding is never looked up."""
        _login(_caller())
        ctx, _ = _db(fetchrow=_row(), fetchval=None)
        router = MagicMock()
        router.get_post_embedding = AsyncMock(return_value=[0.1] * 4)
        router.find_similar = AsyncMock(return_value=[])
        try:
            with patch("src.routers.posts.semantic_router", router):
                resp = await client.get(f"/posts/similar?post_id={uuid.uuid4()}")
        finally:
            ctx.stop()
        assert resp.status_code == 404
        router.get_post_embedding.assert_not_called()


# ── Announcements ─────────────────────────────────────────────────────────────

class TestNotAnnounced:
    @pytest.mark.parametrize("visibility", ["COLLECTIVE", "PRIVATE"])
    async def test_a_non_open_post_sends_no_event_and_no_broadcast(self, client, visibility):
        _login(_caller())
        ctx, _ = _db(fetchval=1)                         # membership (COLLECTIVE)
        tctx, _, conn = _tx(fetchval=[uuid.uuid4(), None])  # agent_id; not a duplicate
        conn.fetchrow.return_value = _row(visibility, author=ME,
                                          collective_id=COL if visibility == "COLLECTIVE" else None)
        emit = AsyncMock()
        broadcast = AsyncMock(return_value=0)
        body = _update(visibility=visibility)
        if visibility == "COLLECTIVE":
            body["collective_id"] = str(COL)
        try:
            with patch("src.routers.posts.emit_event", emit), \
                 patch("src.routers.posts.cache_delete", AsyncMock()), \
                 patch.object(post_moderation, "hold_if_solicitation", AsyncMock(return_value=None)), \
                 patch("src.routers.posts.connection_manager.broadcast_global", broadcast):
                resp = await client.post("/posts", json=body)
        finally:
            ctx.stop()
            tctx.stop()
        assert resp.status_code == 201, resp.text
        emit.assert_not_called()
        broadcast.assert_not_called()

    async def test_a_public_post_is_still_announced(self, client):
        _login(_caller())
        tctx, _, conn = _tx(fetchval=[uuid.uuid4(), None])
        conn.fetchrow.return_value = _row("PUBLIC", author=ME, collective_id=None)
        emit = AsyncMock()
        broadcast = AsyncMock(return_value=0)
        try:
            with patch("src.routers.posts.emit_event", emit), \
                 patch("src.routers.posts.cache_delete", AsyncMock()), \
                 patch.object(post_moderation, "hold_if_solicitation", AsyncMock(return_value=None)), \
                 patch("src.routers.posts.connection_manager.broadcast_global", broadcast):
                resp = await client.post("/posts", json=_update())
        finally:
            tctx.stop()
        assert resp.status_code == 201, resp.text
        emit.assert_awaited_once()
        broadcast.assert_awaited_once()


# ── The public event readers ──────────────────────────────────────────────────

class TestEventsFilter:
    def test_filter_skips_hidden_and_non_open_posts(self):
        from src.services.events import EVENT_NOT_ABOUT_HIDDEN_POST as sql
        assert "hp.hidden_at IS NOT NULL" in sql
        assert "hp.visibility NOT IN ('PUBLIC', 'SYSTEM')" in sql
        # found by primary key, and the payload is cast only when it is a UUID
        assert "hp.post_id = CASE WHEN events.payload->>'post_id'" in sql
        assert "::uuid END" in sql

    def test_both_anonymous_readers_use_it(self):
        from pathlib import Path
        src = Path(__file__).resolve().parent.parent / "src"
        for rel in ("routers/events.py", "routers/dashboard.py"):
            text = (src / rel).read_text()
            assert "EVENT_NOT_ABOUT_HIDDEN_POST" in text, rel
            assert "FROM events" in text


# ── Communities and the legacy feed ───────────────────────────────────────────

class TestCommunities:
    async def test_only_open_posts_can_be_shared(self):
        from src.services import community_service
        tctx, _, conn = _tx(target="src.services.community_service.transaction")
        conn.fetchrow.side_effect = [{"role": "MEMBER"}, None]   # member; post not found by the gated read
        try:
            with pytest.raises(ValueError, match="Post not found"):
                await community_service.add_post_to_community(uuid.uuid4(), uuid.uuid4(), ME)
        finally:
            tctx.stop()
        post_sql = conn.fetchrow.await_args_list[1].args[0]
        assert "visibility IN ('PUBLIC', 'SYSTEM')" in post_sql and "hidden_at IS NULL" in post_sql
        assert conn.fetchrow.await_count == 2                     # no INSERT

    async def test_the_community_feed_shows_open_posts_only(self):
        from src.services import community_service
        ctx, conn = _db(fetch=[], target="src.services.community_service.get_db")
        try:
            assert await community_service.get_community_feed(uuid.uuid4()) == []
        finally:
            ctx.stop()
        assert "p.visibility IN ('PUBLIC', 'SYSTEM')" in conn.fetch.await_args.args[0]


class TestChannels:
    """Channels pin posts the way communities share them: same rule."""

    async def test_only_open_posts_can_be_pinned(self):
        from src.services import channel_service
        tctx, _, conn = _tx(target="src.services.channel_service.transaction")
        conn.fetchrow.side_effect = [{"community_id": uuid.uuid4()}, {"role": "MEMBER"}]
        conn.fetchval.return_value = None                          # not found by the gated read
        try:
            with pytest.raises(ValueError, match="Post not found"):
                await channel_service.add_post_to_channel(uuid.uuid4(), uuid.uuid4(), ME)
        finally:
            tctx.stop()
        post_sql = conn.fetchval.await_args.args[0]
        assert "visibility IN ('PUBLIC', 'SYSTEM')" in post_sql and "hidden_at IS NULL" in post_sql
        conn.execute.assert_not_called()                           # no INSERT, no count bump

    async def test_the_channel_feed_shows_open_posts_only(self):
        from src.services import channel_service
        ctx, conn = _db(fetch=[], target="src.services.channel_service.get_db")
        try:
            assert await channel_service.get_channel_feed(uuid.uuid4()) == []
        finally:
            ctx.stop()
        assert "p.visibility IN ('PUBLIC', 'SYSTEM')" in conn.fetch.await_args.args[0]


def test_legacy_feed_shows_open_posts_only():
    import inspect
    from src.routers import posts
    sql = inspect.getsource(posts.get_feed)
    assert "AND visibility IN ('PUBLIC', 'SYSTEM')" in sql
    assert "AND hidden_at IS NULL" in sql
